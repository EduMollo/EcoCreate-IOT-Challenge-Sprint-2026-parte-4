"""
C0 — Persistência (SQLite)

No Sprint 2 as leituras viviam em um buffer em memória (100 itens) e em
logs/sensor_history.json. O Sprint 3 precisa de histórico por pet para
calcular baseline individual, além de prontuário, vacinas, medicamentos e
comportamento do tutor (IoB). SQLite: zero infraestrutura, roda do .zip.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get(
    "CLYVO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "clyvo.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tutors (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    phone             TEXT,
    preferred_channel TEXT DEFAULT 'whatsapp',
    preferred_hour    INTEGER DEFAULT 19,
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pets (
    id         INTEGER PRIMARY KEY,
    tutor_id   INTEGER NOT NULL REFERENCES tutors(id),
    name       TEXT NOT NULL,
    species    TEXT NOT NULL CHECK (species IN ('dog','cat')),
    breed      TEXT,
    sex        TEXT,
    neutered   INTEGER DEFAULT 0,
    birth_date TEXT,
    weight_kg  REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Telemetria: vem do iot_sensor_simulation.py / ESP32 (Sprint 2) e do
-- activity_score derivado do pet_detection.py (YOLO, Sprint 3).
CREATE TABLE IF NOT EXISTS readings (
    id             INTEGER PRIMARY KEY,
    pet_id         INTEGER NOT NULL REFERENCES pets(id),
    ts             TEXT NOT NULL,
    temperature_c  REAL,
    humidity_pct   REAL,
    heart_rate_bpm REAL,
    spo2_pct       REAL,
    activity_score REAL,
    source         TEXT DEFAULT 'sensor'
);
CREATE INDEX IF NOT EXISTS idx_readings_pet_ts ON readings(pet_id, ts);

CREATE TABLE IF NOT EXISTS vaccines (
    id         INTEGER PRIMARY KEY,
    pet_id     INTEGER NOT NULL REFERENCES pets(id),
    vaccine    TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    next_due   TEXT,
    lot        TEXT
);

CREATE TABLE IF NOT EXISTS consultations (
    id         INTEGER PRIMARY KEY,
    pet_id     INTEGER NOT NULL REFERENCES pets(id),
    date       TEXT NOT NULL,
    reason     TEXT,
    diagnosis  TEXT,
    procedure  TEXT,
    return_due TEXT,
    returned   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS medications (
    id                INTEGER PRIMARY KEY,
    pet_id            INTEGER NOT NULL REFERENCES pets(id),
    name              TEXT NOT NULL,
    start_date        TEXT NOT NULL,
    end_date          TEXT,
    frequency_per_day INTEGER DEFAULT 1,
    doses_expected    INTEGER DEFAULT 0,
    doses_confirmed   INTEGER DEFAULT 0
);

-- IoB (Internet of Behaviors): como o tutor reage às comunicações.
-- event_type: message_sent | opened | replied | appointment_booked | no_show | med_confirmed | med_missed
CREATE TABLE IF NOT EXISTS tutor_events (
    id         INTEGER PRIMARY KEY,
    tutor_id   INTEGER NOT NULL REFERENCES tutors(id),
    pet_id     INTEGER REFERENCES pets(id),
    event_type TEXT NOT NULL,
    channel    TEXT,
    ts         TEXT NOT NULL,
    meta       TEXT
);

-- Saída do Copilot. Cada linha é uma decisão auditável.
-- llm_mode: claude | template
CREATE TABLE IF NOT EXISTS insights (
    id                INTEGER PRIMARY KEY,
    pet_id            INTEGER NOT NULL REFERENCES pets(id),
    ts                TEXT NOT NULL,
    risk_score        REAL,
    risk_level        TEXT,
    anomaly_score     REAL,
    prob_attention_7d REAL,
    top_factors_json  TEXT,
    actions_json      TEXT,
    services_json     TEXT,
    tutor_message     TEXT,
    vet_briefing      TEXT,
    llm_mode          TEXT,
    guardrail_json    TEXT,
    features_json     TEXT,
    approved          INTEGER DEFAULT 0,
    sent_at           TEXT
);
"""


@contextmanager
def get_conn(path: str = None):
    conn = sqlite3.connect(path or DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str = None):
    with get_conn(path) as c:
        c.executescript(SCHEMA)


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ─── Leitura ──────────────────────────────────────────────────────────────────
def list_pets() -> list[dict]:
    with get_conn() as c:
        return _rows(c.execute(
            "SELECT p.*, t.name AS tutor_name, t.preferred_channel, t.preferred_hour "
            "FROM pets p JOIN tutors t ON t.id = p.tutor_id ORDER BY p.id"))


def get_pet(pet_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute(
            "SELECT p.*, t.name AS tutor_name, t.phone, t.preferred_channel, t.preferred_hour "
            "FROM pets p JOIN tutors t ON t.id = p.tutor_id WHERE p.id = ?", (pet_id,)).fetchone()
        return dict(r) if r else None


def get_pet_by_name(name: str) -> dict | None:
    with get_conn() as c:
        r = c.execute("SELECT id FROM pets WHERE lower(name) = lower(?) LIMIT 1", (name,)).fetchone()
    return get_pet(r["id"]) if r else None


def get_readings(pet_id: int, limit: int = 200) -> list[dict]:
    """Retorna as últimas `limit` leituras, ordenadas da mais antiga para a mais recente."""
    with get_conn() as c:
        rows = _rows(c.execute(
            "SELECT * FROM readings WHERE pet_id = ? ORDER BY ts DESC, id DESC LIMIT ?", (pet_id, limit)))
    return list(reversed(rows))


def get_vaccines(pet_id: int) -> list[dict]:
    with get_conn() as c:
        return _rows(c.execute("SELECT * FROM vaccines WHERE pet_id = ? ORDER BY applied_at", (pet_id,)))


def get_consultations(pet_id: int) -> list[dict]:
    with get_conn() as c:
        return _rows(c.execute("SELECT * FROM consultations WHERE pet_id = ? ORDER BY date", (pet_id,)))


def get_medications(pet_id: int) -> list[dict]:
    with get_conn() as c:
        return _rows(c.execute("SELECT * FROM medications WHERE pet_id = ? ORDER BY start_date", (pet_id,)))


def get_tutor_events(tutor_id: int, limit: int = 500) -> list[dict]:
    with get_conn() as c:
        return _rows(c.execute(
            "SELECT * FROM tutor_events WHERE tutor_id = ? ORDER BY ts DESC LIMIT ?", (tutor_id, limit)))


def get_latest_insight(pet_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute("SELECT * FROM insights WHERE pet_id = ? ORDER BY ts DESC, id DESC LIMIT 1", (pet_id,)).fetchone()
    return _decode_insight(dict(r)) if r else None


def get_insight(insight_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
    return _decode_insight(dict(r)) if r else None


def list_latest_insights() -> list[dict]:
    """Um insight (o mais recente) por pet — base do painel de triagem."""
    with get_conn() as c:
        rows = _rows(c.execute("""
            SELECT i.*, p.name AS pet_name, p.species, t.name AS tutor_name
            FROM insights i
            JOIN pets p ON p.id = i.pet_id
            JOIN tutors t ON t.id = p.tutor_id
            WHERE i.id IN (SELECT MAX(id) FROM insights GROUP BY pet_id)
            ORDER BY i.risk_score DESC"""))
    return [_decode_insight(r) for r in rows]


def _decode_insight(row: dict) -> dict:
    for k in ("top_factors_json", "actions_json", "services_json", "guardrail_json", "features_json"):
        raw = row.pop(k, None)
        try:
            row[k[:-5]] = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            row[k[:-5]] = None
    return row


# ─── Escrita ──────────────────────────────────────────────────────────────────
def insert_reading(pet_id: int, reading: dict) -> int:
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO readings (pet_id, ts, temperature_c, humidity_pct, heart_rate_bpm, spo2_pct, activity_score, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pet_id, reading.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
             reading.get("temperature_c"), reading.get("humidity_pct"), reading.get("heart_rate_bpm"),
             reading.get("spo2_pct"), reading.get("activity_score"), reading.get("source", "sensor")))
        return cur.lastrowid


def count_readings(pet_id: int) -> int:
    with get_conn() as c:
        return c.execute("SELECT COUNT(*) FROM readings WHERE pet_id = ?", (pet_id,)).fetchone()[0]


def save_insight(pet_id: int, insight: dict) -> int:
    with get_conn() as c:
        cur = c.execute("""
            INSERT INTO insights (pet_id, ts, risk_score, risk_level, anomaly_score, prob_attention_7d,
                                  top_factors_json, actions_json, services_json, tutor_message, vet_briefing,
                                  llm_mode, guardrail_json, features_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pet_id, insight["ts"], insight["risk"]["risk_score"], insight["risk"]["risk_level"],
             insight["risk"]["anomaly_score"], insight["risk"]["prob_attention_7d"],
             json.dumps(insight["risk"]["top_factors"], ensure_ascii=False),
             json.dumps(insight["actions"], ensure_ascii=False),
             json.dumps(insight["services"], ensure_ascii=False),
             insight["tutor_message"], insight["vet_briefing"], insight["llm_mode"],
             json.dumps(insight["guardrail"], ensure_ascii=False),
             json.dumps(insight["features"], ensure_ascii=False)))
        return cur.lastrowid


def approve_insight(insight_id: int) -> dict | None:
    """Human-in-the-loop: veterinário aprova → mensagem é liberada ao tutor."""
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as c:
        c.execute("UPDATE insights SET approved = 1, sent_at = ? WHERE id = ?", (now, insight_id))
    return get_insight(insight_id)


def log_tutor_event(tutor_id: int, event_type: str, pet_id: int = None,
                    channel: str = None, meta: dict = None, ts: str = None) -> int:
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO tutor_events (tutor_id, pet_id, event_type, channel, ts, meta) VALUES (?,?,?,?,?,?)",
            (tutor_id, pet_id, event_type, channel, ts or datetime.now().isoformat(timespec="seconds"),
             json.dumps(meta, ensure_ascii=False) if meta else None))
        return cur.lastrowid


def is_seeded() -> bool:
    with get_conn() as c:
        try:
            return c.execute("SELECT COUNT(*) FROM pets").fetchone()[0] > 0
        except sqlite3.OperationalError:
            return False
