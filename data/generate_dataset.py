"""
Gerador de dados sintéticos — seed fixa, reprodutível

1) Popula clyvo.db com tutores, pets, prontuário (vacinas, consultas,
   medicamentos), telemetria histórica (baseline individual) e eventos de
   comportamento do tutor (IoB).
2) Gera data/training_dataset.csv com episódios rotulados para treinar o
   modelo preditivo (ai_core/risk_model.py).

Uso:
    python data/generate_dataset.py --reset          # DB + CSV
    python data/generate_dataset.py --csv-only       # só o CSV
"""

import argparse
import math
import os
import random
import sys
from datetime import date, datetime, timedelta

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ai_core import db  # noqa: E402
from ai_core.features import FEATURE_ORDER, SPECIES_PRIOR  # noqa: E402

SEED = 42
CSV_PATH = os.path.join(ROOT, "data", "training_dataset.csv")

TUTORS = [
    ("Mariana Souza", "whatsapp", 19, "médio"), ("Carlos Lima", "whatsapp", 20, "alto"),
    ("Fernanda Alves", "whatsapp", 12, "baixo"), ("Rafael Costa", "app", 8, "alto"),
    ("Juliana Prado", "whatsapp", 18, "médio"), ("Paulo Mendes", "sms", 21, "baixo"),
    ("Ana Beatriz Rocha", "whatsapp", 19, "alto"), ("Lucas Ferreira", "app", 22, "médio"),
    ("Camila Duarte", "whatsapp", 9, "médio"), ("Bruno Carvalho", "whatsapp", 20, "baixo"),
    ("Patrícia Nunes", "email", 7, "médio"), ("Diego Martins", "whatsapp", 18, "alto"),
]

DOG_BREEDS = ["SRD", "Labrador", "Golden Retriever", "Poodle", "Shih Tzu", "Bulldog Francês",
              "Border Collie", "Dachshund", "Spitz Alemão", "Pastor Alemão"]
CAT_BREEDS = ["SRD", "Siamês", "Persa", "Maine Coon", "Ragdoll", "Bengal"]
PET_NAMES = ["Thor", "Mel", "Bob", "Nina", "Simba", "Luna", "Max", "Amora", "Zeus", "Lola", "Fred",
             "Mia", "Bento", "Pipoca", "Theo", "Maya", "Rex", "Belinha", "Chico", "Nala", "Duke",
             "Cacau", "Nino", "Kiara"]

ENGAGEMENT_PROFILE = {
    "alto":  {"sent": 10, "open": 0.9, "reply": 0.7, "book": 3, "no_show": 0, "med_ok": 0.9},
    "médio": {"sent": 8,  "open": 0.6, "reply": 0.4, "book": 2, "no_show": 1, "med_ok": 0.7},
    "baixo": {"sent": 9,  "open": 0.25, "reply": 0.1, "book": 1, "no_show": 2, "med_ok": 0.4},
}


# ─── Utilitários ──────────────────────────────────────────────────────────────
def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def d(days_ago: int, today: date) -> str:
    return (today - timedelta(days=days_ago)).isoformat()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ─── Telemetria histórica (baseline individual) ───────────────────────────────
def gen_readings(rng: random.Random, species: str, offsets: dict, n: int = 60, step_min: int = 30,
                 drift: dict | None = None, drift_last: int = 12, end: datetime | None = None) -> list[dict]:
    """Séries com baseline PRÓPRIO do pet (prior da espécie + offset individual) e ruído.
    `drift` aplica uma deriva progressiva nas últimas `drift_last` leituras (ex.: febre)."""
    prior = SPECIES_PRIOR[species]
    end = end or datetime.now()
    base = {k: prior[k][0] + offsets.get(k, 0.0) for k in prior}
    noise = {"temp": 0.12, "hr": 4.0, "spo2": 0.4, "act": 0.06}
    out = []
    for i in range(n):
        ts = end - timedelta(minutes=step_min * (n - 1 - i))
        prog = 0.0
        if drift and i >= n - drift_last:
            prog = (i - (n - drift_last) + 1) / drift_last
        wave = math.sin(i / 6)          # oscilação fisiológica lenta e discreta
        temp = base["temp"] + 0.05 * wave + rng.gauss(0, noise["temp"]) + (prog * drift.get("temp", 0) if drift else 0)
        hr = base["hr"] + 2.5 * wave + rng.gauss(0, noise["hr"]) + (prog * drift.get("hr", 0) if drift else 0)
        spo2 = base["spo2"] + 0.1 * wave + rng.gauss(0, noise["spo2"]) + (prog * drift.get("spo2", 0) if drift else 0)
        hour = ts.hour
        circ = 0.15 if 7 <= hour <= 21 else -0.15          # pets se mexem menos à noite
        act = base["act"] + circ + rng.gauss(0, noise["act"]) + (prog * drift.get("act", 0) if drift else 0)
        out.append({
            "timestamp": ts.isoformat(timespec="seconds"),
            "temperature_c": round(temp, 2), "humidity_pct": round(55 + 5 * wave + rng.gauss(0, 1), 1),
            "heart_rate_bpm": round(hr), "spo2_pct": round(clamp(spo2, 85, 100), 1),
            "activity_score": round(clamp(act, 0, 1), 3), "source": "seed",
        })
    return out


# ─── Eventos IoB ──────────────────────────────────────────────────────────────
def gen_tutor_events(rng: random.Random, tutor_id: int, pet_id: int, channel: str, hour: int,
                     engagement: str, today: date) -> list[tuple]:
    p = ENGAGEMENT_PROFILE[engagement]
    ev = []
    for _ in range(p["sent"]):
        day = rng.randint(3, 90)
        base = datetime.combine(today - timedelta(days=day), datetime.min.time()).replace(hour=10)
        ev.append((tutor_id, pet_id, "message_sent", channel, base.isoformat(timespec="seconds")))
        if rng.random() < p["open"]:
            t = base.replace(hour=clamp(hour + rng.randint(-1, 1), 6, 23))
            ev.append((tutor_id, pet_id, "opened", channel, t.isoformat(timespec="seconds")))
            if rng.random() < p["reply"]:
                ev.append((tutor_id, pet_id, "replied", channel, (t + timedelta(minutes=rng.randint(2, 90))).isoformat(timespec="seconds")))
    for _ in range(p["book"]):
        ev.append((tutor_id, pet_id, "appointment_booked", channel, d(rng.randint(5, 120), today) + "T11:00:00"))
    for _ in range(p["no_show"]):
        ev.append((tutor_id, pet_id, "no_show", None, d(rng.randint(5, 120), today) + "T15:00:00"))
    for _ in range(12):
        kind = "med_confirmed" if rng.random() < p["med_ok"] else "med_missed"
        ev.append((tutor_id, pet_id, kind, "app", d(rng.randint(1, 40), today) + f"T{hour:02d}:05:00"))
    return ev


# ─── Seed do banco ────────────────────────────────────────────────────────────
def seed_database(reset: bool = True, today: date | None = None, verbose: bool = True) -> None:
    today = today or date.today()
    rng = random.Random(SEED)

    if reset:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db.DB_PATH + suffix)
            except FileNotFoundError:
                pass
    db.init_db()

    with db.get_conn() as c:
        for name, channel, hour, _eng in TUTORS:
            c.execute("INSERT INTO tutors (name, phone, preferred_channel, preferred_hour) VALUES (?,?,?,?)",
                      (name, f"+55 11 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}", channel, hour))

    # ── Pets-vitrine (comportamentos distintos para a demo) ──────────────────
    showcase = [
        # name, tutor_idx, species, breed, sex, neutered, birth(days_ago), weight, offsets, drift
        ("Thor", 0, "dog", "Golden Retriever", "M", 1, 5 * 365 + 180, 32.0, {"temp": -0.2, "hr": -12, "spo2": 0.3, "act": 0.12}, None),
        ("Mel", 1, "cat", "SRD", "F", 1, 10 * 365, 4.2, {"temp": -0.1, "hr": -10, "act": -0.05}, {"temp": 0.9, "hr": 32, "act": -0.22}),
        ("Bob", 2, "dog", "Bulldog Francês", "M", 0, 7 * 365 + 120, 13.0, {"temp": 0.1, "hr": 8, "act": -0.08}, None),
        ("Nina", 3, "dog", "Border Collie", "F", 1, 3 * 365 + 290, 18.0, {"temp": 0.0, "hr": -5, "act": 0.2}, None),
        ("Simba", 4, "cat", "Maine Coon", "M", 1, 6 * 365 + 210, 7.1, {"temp": 0.0, "hr": 5, "act": 0.0}, None),
        ("Luna", 5, "dog", "Labrador", "F", 1, 11 * 365 + 70, 29.0, {"temp": -0.1, "hr": -8, "act": -0.1}, {"act": -0.2, "spo2": -1.2}),
    ]
    pets = []
    for name, ti, sp, breed, sex, neut, born_ago, wt, offs, drift in showcase:
        pets.append(dict(name=name, tutor_idx=ti, species=sp, breed=breed, sex=sex, neutered=neut,
                         birth=d(born_ago, today), weight=wt, offsets=offs, drift=drift))
    # ── Pets aleatórios ──────────────────────────────────────────────────────
    for name in PET_NAMES[len(showcase):]:
        sp = "cat" if rng.random() < 0.35 else "dog"
        breed = rng.choice(CAT_BREEDS if sp == "cat" else DOG_BREEDS)
        born_ago = int(rng.choice([rng.uniform(90, 365), rng.uniform(365, 7 * 365), rng.uniform(7 * 365, 14 * 365)]))
        wt = round(rng.uniform(3, 6.5), 1) if sp == "cat" else round(rng.choice([rng.uniform(4, 10), rng.uniform(10, 25), rng.uniform(25, 40)]), 1)
        offs = {"temp": rng.uniform(-0.25, 0.25), "hr": rng.uniform(-15, 15), "spo2": rng.uniform(-0.5, 0.5), "act": rng.uniform(-0.12, 0.12)}
        drift = None
        if rng.random() < 0.15:  # alguns com deriva leve/moderada
            drift = rng.choice([{"temp": 0.6, "act": -0.12}, {"hr": 25}, {"act": -0.25}, {"spo2": -1.5}])
        pets.append(dict(name=name, tutor_idx=rng.randrange(len(TUTORS)), species=sp, breed=breed,
                         sex=rng.choice("MF"), neutered=int(rng.random() < 0.7), birth=d(born_ago, today),
                         weight=wt, offsets=offs, drift=drift))

    n_read = 0
    with db.get_conn() as c:
        for i, p in enumerate(pets, start=1):
            tutor_id = p["tutor_idx"] + 1
            c.execute("INSERT INTO pets (id, tutor_id, name, species, breed, sex, neutered, birth_date, weight_kg) VALUES (?,?,?,?,?,?,?,?,?)",
                      (i, tutor_id, p["name"], p["species"], p["breed"], p["sex"], p["neutered"], p["birth"], p["weight"]))

            # Telemetria
            for r in gen_readings(rng, p["species"], p["offsets"], drift=p["drift"]):
                c.execute("INSERT INTO readings (pet_id, ts, temperature_c, humidity_pct, heart_rate_bpm, spo2_pct, activity_score, source) VALUES (?,?,?,?,?,?,?,?)",
                          (i, r["timestamp"], r["temperature_c"], r["humidity_pct"], r["heart_rate_bpm"], r["spo2_pct"], r["activity_score"], r["source"]))
                n_read += 1

            # Prontuário — vitrines com cenário fixo, restante aleatório
            poly = "V10" if p["species"] == "dog" else "V4"
            if p["name"] == "Thor":
                _vac(c, i, poly, 350, today); _vac(c, i, "Antirrábica", 400, today)
                _med(c, i, "Vermífugo (praziquantel)", 100, 100, 1, 1, 1, today)
                _med(c, i, "Condroitina + Glicosamina", 40, None, 1, 40, 26, today)
                _cons(c, i, 240, "Check-up anual", "Sem alterações", None, None, today)
            elif p["name"] == "Mel":
                _vac(c, i, poly, 120, today); _vac(c, i, "Antirrábica", 120, today)
                _med(c, i, "Vermífugo", 40, 40, 1, 1, 1, today)
                _cons(c, i, 200, "Check-up sênior", "Discreta perda de massa muscular", None, None, today)
            elif p["name"] == "Bob":
                _vac(c, i, poly, 200, today); _vac(c, i, "Antirrábica", 200, today)
                _med(c, i, "Vermífugo", 60, 60, 1, 1, 1, today)
                _med(c, i, "Antialérgico (uso contínuo)", 30, None, 1, 30, 12, today)
                _cons(c, i, 45, "Dermatite alérgica", "Dermatite atópica em acompanhamento", None, None, today)
            elif p["name"] == "Nina":
                _vac(c, i, poly, 90, today); _vac(c, i, "Antirrábica", 90, today)
                _med(c, i, "Vermífugo", 30, 30, 1, 1, 1, today)
                _cons(c, i, 90, "Check-up anual", "Saudável", None, None, today)
            elif p["name"] == "Simba":
                _vac(c, i, poly, 490, today); _vac(c, i, "Antirrábica", 150, today)
                _med(c, i, "Vermífugo", 70, 70, 1, 1, 1, today)
                _cons(c, i, 150, "Vacinação", None, None, None, today)
            elif p["name"] == "Luna":
                _vac(c, i, poly, 100, today); _vac(c, i, "Antirrábica", 100, today)
                _med(c, i, "Vermífugo", 50, 50, 1, 1, 1, today)
                _cons(c, i, 20, "Halitose e tártaro", "Doença periodontal grau 2", "Limpeza dentária", 2, today, returned=0)
                _med(c, i, "Anti-inflamatório pós-procedimento", 20, 13, 2, 14, 12, today)
            else:
                ok = rng.random() < 0.75
                _vac(c, i, poly, rng.randint(30, 340) if ok else rng.randint(380, 520), today)
                _vac(c, i, "Antirrábica", rng.randint(30, 340) if rng.random() < 0.8 else rng.randint(380, 480), today)
                if rng.random() < 0.85:
                    _med(c, i, "Vermífugo", rng.randint(10, 150), None, 1, 1, 1, today)
                if rng.random() < 0.6:
                    _cons(c, i, rng.randint(20, 500), "Consulta de rotina", None, None, None, today)
                if rng.random() < 0.35:
                    exp = 30
                    _med(c, i, rng.choice(["Suplemento articular", "Antialérgico", "Cardioprotetor"]), 30, None, 1, exp, int(exp * rng.uniform(0.3, 1.0)), today)

            # IoB
            _name, channel, hour, eng = TUTORS[p["tutor_idx"]]
            for ev in gen_tutor_events(rng, tutor_id, i, channel, hour, eng, today):
                c.execute("INSERT INTO tutor_events (tutor_id, pet_id, event_type, channel, ts) VALUES (?,?,?,?,?)", ev)

    if verbose:
        print(f"  DB: {len(TUTORS)} tutores, {len(pets)} pets, {n_read} leituras -> {db.DB_PATH}")


def _vac(c, pet_id, name, applied_ago, today):
    applied = today - timedelta(days=applied_ago)
    c.execute("INSERT INTO vaccines (pet_id, vaccine, applied_at, next_due, lot) VALUES (?,?,?,?,?)",
              (pet_id, name, applied.isoformat(), (applied + timedelta(days=365)).isoformat(), f"L{applied_ago:04d}"))


def _med(c, pet_id, name, start_ago, end_ago, freq, expected, confirmed, today):
    c.execute("INSERT INTO medications (pet_id, name, start_date, end_date, frequency_per_day, doses_expected, doses_confirmed) VALUES (?,?,?,?,?,?,?)",
              (pet_id, name, d(start_ago, today), d(end_ago, today) if end_ago is not None else None, freq, expected, confirmed))


def _cons(c, pet_id, days_ago, reason, diagnosis, procedure, return_days_ago, today, returned=1):
    return_due = d(return_days_ago, today) if return_days_ago is not None else None
    c.execute("INSERT INTO consultations (pet_id, date, reason, diagnosis, procedure, return_due, returned) VALUES (?,?,?,?,?,?,?)",
              (pet_id, d(days_ago, today), reason, diagnosis, procedure, return_due, returned if return_due else 1))


# ─── Dataset de treino ────────────────────────────────────────────────────────
PATTERNS = ["febre", "cardio", "respiratorio", "letargia", "misto"]
PATTERN_W = [0.30, 0.15, 0.15, 0.25, 0.15]


def sample_episode(rng: random.Random) -> dict:
    is_cat = rng.random() < 0.35
    age = rng.choices([rng.uniform(0.2, 1), rng.uniform(1, 7), rng.uniform(7, 15)], [0.15, 0.55, 0.30])[0]
    weight = rng.gauss(4.5, 1.0) if is_cat else rng.choice([rng.uniform(4, 10), rng.uniform(10, 25), rng.uniform(25, 40)])
    overdue = 0 if rng.random() < 0.6 else int(rng.expovariate(1 / 45))
    adherence = 100.0 if rng.random() < 0.5 else round(rng.uniform(30, 95), 1)
    days_since = int(rng.choices([rng.uniform(0, 180), rng.uniform(180, 400), rng.uniform(400, 730)], [0.5, 0.3, 0.2])[0])

    logit = (-1.7 + 0.9 * (age >= 8) + 0.5 * (age < 1) + 0.7 * (overdue > 30)
             + 0.8 * (adherence < 70) + 0.4 * (days_since > 400))
    sick = rng.random() < sigmoid(logit)

    # z e slope são adimensionais (σ do baseline individual) — mesma escala de features.py
    z = {k: rng.gauss(0, 0.75) for k in ("temp_z", "hr_z", "spo2_z", "act_z")}
    s = {k: rng.gauss(0, 0.55) for k in ("temp_slope", "hr_slope", "spo2_slope", "act_slope")}
    pattern = "normal"
    if sick:
        pattern = rng.choices(PATTERNS, PATTERN_W)[0]
        if pattern == "febre":
            z["temp_z"] = rng.gauss(2.2, 0.7); s["temp_slope"] = rng.gauss(1.2, 0.5); z["act_z"] = rng.gauss(-1.2, 0.8)
        elif pattern == "cardio":
            z["hr_z"] = rng.gauss(2.3, 0.8); s["hr_slope"] = rng.gauss(1.3, 0.5)
        elif pattern == "respiratorio":
            z["spo2_z"] = rng.gauss(-2.2, 0.7); s["spo2_slope"] = rng.gauss(-1.2, 0.5); z["act_z"] = rng.gauss(-1.0, 0.8)
        elif pattern == "letargia":
            z["act_z"] = rng.gauss(-2.3, 0.7); s["act_slope"] = rng.gauss(-1.0, 0.5); z["temp_z"] = rng.gauss(0.6, 0.6)
        else:
            z["temp_z"] = rng.gauss(1.6, 0.6); z["hr_z"] = rng.gauss(1.6, 0.6); z["act_z"] = rng.gauss(-1.6, 0.6)
    elif rng.random() < 0.10:  # pico espúrio isolado em pet saudável (ruído realista)
        k = rng.choice(["temp_z", "hr_z", "spo2_z", "act_z"])
        z[k] = rng.gauss(1.8, 0.5) * (-1 if k in ("spo2_z", "act_z") else 1)

    label = int(sick)
    if rng.random() < 0.07:   # ruído de rótulo
        label = 1 - label

    row = {**{k: round(v, 3) for k, v in z.items()}, **{k: round(v, 3) for k, v in s.items()},
           "age_years": round(age, 2), "weight_kg": round(max(1.0, weight), 1), "is_cat": int(is_cat),
           "days_since_last_consult": days_since, "vaccine_overdue_days": overdue,
           "med_adherence_pct": adherence, "needs_attention_7d": label, "pattern": pattern}
    return row


def generate_training_dataset(n_rows: int = 2000, path: str = CSV_PATH, verbose: bool = True) -> pd.DataFrame:
    rng = random.Random(SEED + 1)
    df = pd.DataFrame([sample_episode(rng) for _ in range(n_rows)])
    df = df[FEATURE_ORDER + ["needs_attention_7d", "pattern"]]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    if verbose:
        print(f"  CSV: {len(df)} episódios, {df['needs_attention_7d'].mean():.1%} positivos -> {path}")
    return df


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Gera dados sintéticos do CLYVO VET")
    ap.add_argument("--reset", action="store_true", help="apaga e recria o clyvo.db")
    ap.add_argument("--rows", type=int, default=2000, help="episódios no dataset de treino")
    ap.add_argument("--csv-only", action="store_true")
    ap.add_argument("--db-only", action="store_true")
    args = ap.parse_args()

    print("CLYVO VET — gerador de dados sintéticos (seed fixa)")
    if not args.csv_only:
        seed_database(reset=args.reset or not db.is_seeded())
    if not args.db_only:
        generate_training_dataset(args.rows)
