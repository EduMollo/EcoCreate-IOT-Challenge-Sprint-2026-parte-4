"""
CLYVO VET - Dashboard Web + API do CLYVO Copilot
Disruptive Architectures: IoT, IoB & Generative IA - Sprint 3
FIAP 2026

Evolução do servidor do Sprint 2:
  - mantém  POST /api/sensor-data, GET /api/history, SSE /stream
  - persiste as leituras em SQLite (clyvo.db) em vez de buffer em memória
  - a cada N leituras de um pet, roda o CLYVO Copilot (ai_core/pipeline.py)
    e transmite o "insight" por SSE
  - expõe a API do Copilot: triagem, análise sob demanda, aprovação
    (human-in-the-loop), eventos IoB, métricas do modelo
"""

import json
import os
import queue
import sys
import threading
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

load_dotenv()

from ai_core import db, pipeline  # noqa: E402
from ai_core.features import telemetry_features  # noqa: E402
from ai_core.risk_model import MODEL_PATH, load_metrics, train as train_model  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = Flask(__name__)

ANALYZE_EVERY = int(os.getenv("CLYVO_ANALYZE_EVERY", "10"))
DEFAULT_PET = os.getenv("CLYVO_DEFAULT_PET", "Thor")
MAX_BUFFER = 100

# ─── SSE ──────────────────────────────────────────────────────────────────────
sse_clients: list[queue.Queue] = []
sse_lock = threading.Lock()
sensor_buffer: list[dict] = []          # compatibilidade com o Sprint 2 (últimas leituras, todos os pets)


def broadcast(data: dict):
    payload = f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    with sse_lock:
        dead = []
        for q in sse_clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)


# ─── Copilot: gatilho por volume de leituras ──────────────────────────────────
reading_counters: dict[int, int] = {}
analyzing: set[int] = set()
counter_lock = threading.Lock()


def run_analysis(pet_id: int, llm_mode: str | None = None) -> dict | None:
    try:
        insight = pipeline.analyze_pet(pet_id, llm_mode=llm_mode)
        broadcast({"type": "insight", **insight})
        return insight
    except Exception as exc:  # noqa: BLE001 — a análise nunca derruba o servidor de telemetria
        broadcast({"type": "status", "level": "error", "message": f"Copilot falhou para pet {pet_id}: {exc}"})
        print(f"[Copilot] erro pet {pet_id}: {exc}")
        return None
    finally:
        with counter_lock:
            analyzing.discard(pet_id)


def maybe_analyze(pet_id: int, force: bool = False):
    with counter_lock:
        reading_counters[pet_id] = reading_counters.get(pet_id, 0) + 1
        due = force or reading_counters[pet_id] >= ANALYZE_EVERY
        if not due or pet_id in analyzing:
            return
        reading_counters[pet_id] = 0
        analyzing.add(pet_id)
    threading.Thread(target=run_analysis, args=(pet_id,), daemon=True).start()


def resolve_pet(data: dict) -> dict | None:
    if data.get("pet_id"):
        return db.get_pet(int(data["pet_id"]))
    if data.get("pet_name"):
        pet = db.get_pet_by_name(data["pet_name"])
        if pet:
            return pet
    pets = db.list_pets()
    return db.get_pet_by_name(DEFAULT_PET) or (pets[0] if pets else None)


def slim(insight: dict) -> dict:
    """Versão leve do insight para listas (triagem)."""
    keys = ("id", "pet_id", "pet_name", "species", "tutor_name", "ts", "risk_score", "risk_level",
            "anomaly_score", "prob_attention_7d", "llm_mode", "approved", "sent_at")
    out = {k: insight.get(k) for k in keys}
    out["top_action"] = (insight.get("actions") or [{}])[0].get("title") if insight.get("actions") else None
    out["top_priority"] = (insight.get("actions") or [{}])[0].get("priority_label") if insight.get("actions") else None
    out["n_actions"] = len(insight.get("actions") or [])
    return out


# ─── Páginas ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")


# ─── Telemetria (Sprint 2, agora persistida) ──────────────────────────────────
@app.route("/api/sensor-data", methods=["POST"])
def receive_sensor_data():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Payload inválido"}), 400
    pet = resolve_pet(data)
    if not pet:
        return jsonify({"error": "Nenhum pet cadastrado"}), 400

    data.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    data.update({"pet_id": pet["id"], "pet_name": pet["name"], "species": pet["species"], "type": "reading"})
    data.setdefault("source", "sensor")
    db.insert_reading(pet["id"], data)

    sensor_buffer.append(data)
    if len(sensor_buffer) > MAX_BUFFER:
        sensor_buffer.pop(0)
    broadcast(data)
    maybe_analyze(pet["id"])
    return jsonify({"status": "ok", "pet_id": pet["id"]}), 200


@app.route("/api/activity", methods=["POST"])
def receive_activity():
    """Atividade derivada da visão computacional (pet_detection.py) — sensor comportamental."""
    data = request.get_json(force=True, silent=True) or {}
    if "activity_score" not in data:
        return jsonify({"error": "activity_score obrigatório"}), 400
    pet = resolve_pet(data)
    if not pet:
        return jsonify({"error": "Nenhum pet cadastrado"}), 400
    reading = {"timestamp": data.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
               "activity_score": float(data["activity_score"]), "source": "vision"}
    db.insert_reading(pet["id"], reading)
    broadcast({"type": "activity", "pet_id": pet["id"], "pet_name": pet["name"], **reading})
    maybe_analyze(pet["id"])
    return jsonify({"status": "ok"}), 200


@app.route("/api/history")
def history():
    pet = resolve_pet({"pet_id": request.args.get("pet_id"), "pet_name": request.args.get("pet_name")})
    if not pet:
        return jsonify([])
    rows = db.get_readings(pet["id"], limit=int(request.args.get("limit", 40)))
    out = []
    for r in rows:
        if r.get("temperature_c") is None:
            continue
        out.append({"type": "reading", "timestamp": r["ts"], "pet_id": pet["id"], "pet_name": pet["name"],
                    "species": pet["species"], "temperature_c": r["temperature_c"], "humidity_pct": r["humidity_pct"],
                    "heart_rate_bpm": r["heart_rate_bpm"], "spo2_pct": r["spo2_pct"],
                    "activity_score": r["activity_score"], "alerts": [], "source": r["source"]})
    return jsonify(out)


# ─── Pets ─────────────────────────────────────────────────────────────────────
@app.route("/api/pets")
def pets():
    latest = {i["pet_id"]: slim(i) for i in db.list_latest_insights()}
    return jsonify([{**p, "latest_insight": latest.get(p["id"])} for p in db.list_pets()])


@app.route("/api/pets/<int:pet_id>")
def pet_detail(pet_id):
    pet = db.get_pet(pet_id)
    if not pet:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify({
        "pet": pet, "vaccines": db.get_vaccines(pet_id), "consultations": db.get_consultations(pet_id),
        "medications": db.get_medications(pet_id), "readings_count": db.count_readings(pet_id),
        "latest_insight": db.get_latest_insight(pet_id),
    })


@app.route("/api/pets/<int:pet_id>/baseline")
def pet_baseline(pet_id):
    """Baseline individual (usado pelo simulador para calibrar o 'normal' do pet)."""
    pet = db.get_pet(pet_id)
    if not pet:
        return jsonify({"error": "não encontrado"}), 404
    tel = telemetry_features(db.get_readings(pet_id, 200), pet["species"])
    return jsonify({"pet_id": pet_id, "pet_name": pet["name"], "species": pet["species"],
                    "baseline": tel["baseline"], "baseline_source": tel["baseline_source"], "n_readings": tel["n_readings"]})


@app.route("/api/pets/lookup")
def pet_lookup():
    pet = db.get_pet_by_name(request.args.get("name", ""))
    return (jsonify(pet), 200) if pet else (jsonify({"error": "não encontrado"}), 404)


# ─── Copilot ──────────────────────────────────────────────────────────────────
@app.route("/api/triage")
def triage():
    return jsonify([slim(i) for i in db.list_latest_insights()])


@app.route("/api/insights/latest")
def latest_insight():
    pet = resolve_pet({"pet_id": request.args.get("pet_id"), "pet_name": request.args.get("pet_name")})
    ins = db.get_latest_insight(pet["id"]) if pet else None
    return jsonify(ins or {})


@app.route("/api/insights/<int:insight_id>")
def insight_detail(insight_id):
    ins = db.get_insight(insight_id)
    return (jsonify(ins), 200) if ins else (jsonify({"error": "não encontrado"}), 404)


@app.route("/api/analyze/<int:pet_id>", methods=["POST"])
def analyze(pet_id):
    body = request.get_json(silent=True) or {}
    with counter_lock:
        if pet_id in analyzing:
            return jsonify({"status": "busy"}), 409
        analyzing.add(pet_id)
        reading_counters[pet_id] = 0
    insight = run_analysis(pet_id, llm_mode=body.get("llm_mode"))
    if insight is None:
        return jsonify({"error": "falha na análise"}), 500
    return jsonify(insight)


@app.route("/api/insights/<int:insight_id>/approve", methods=["POST"])
def approve(insight_id):
    """Human-in-the-loop: o veterinário aprova e a mensagem é liberada ao tutor (evento IoB)."""
    ins = db.approve_insight(insight_id)
    if not ins:
        return jsonify({"error": "não encontrado"}), 404
    pet = db.get_pet(ins["pet_id"])
    db.log_tutor_event(pet["tutor_id"], "message_sent", pet_id=pet["id"],
                       channel=pet.get("preferred_channel"), meta={"insight_id": insight_id})
    broadcast({"type": "status", "level": "ok", "message": f"Mensagem para {pet['tutor_name']} ({pet['name']}) aprovada e enviada"})
    return jsonify(ins)


@app.route("/api/tutor-events", methods=["POST"])
def tutor_event():
    """Simula a resposta do tutor (IoB): opened | replied | appointment_booked | no_show | med_confirmed | med_missed."""
    body = request.get_json(force=True, silent=True) or {}
    pet = db.get_pet(int(body.get("pet_id", 0))) if body.get("pet_id") else None
    if not pet or body.get("event_type") not in (
            "opened", "replied", "appointment_booked", "no_show", "med_confirmed", "med_missed"):
        return jsonify({"error": "pet_id e event_type válidos são obrigatórios"}), 400
    db.log_tutor_event(pet["tutor_id"], body["event_type"], pet_id=pet["id"],
                       channel=body.get("channel") or pet.get("preferred_channel"))
    broadcast({"type": "status", "level": "ok",
               "message": f"IoB: {pet['tutor_name']} → {body['event_type']} ({pet['name']})"})
    return jsonify({"status": "ok"})


@app.route("/api/model/metrics")
def model_metrics():
    return jsonify(load_metrics() or {"error": "modelo não treinado"})


@app.route("/api/model/train", methods=["POST"])
def model_train():
    metrics = train_model()
    pipeline.get_model(reload=True)
    return jsonify(metrics)


@app.route("/api/health")
def health():
    return jsonify({
        "db": db.DB_PATH, "seeded": db.is_seeded(), "pets": len(db.list_pets()),
        "model_loaded": pipeline.get_model() is not None,
        "llm_mode": os.getenv("CLYVO_LLM_MODE", "auto"),
        "llm_credentials": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")),
        "llm_model": os.getenv("CLYVO_LLM_MODEL", "claude-opus-5"),
        "knowledge_chunks": len(pipeline.get_kb()), "analyze_every": ANALYZE_EVERY,
    })


@app.route("/stream")
def stream():
    def generate():
        q: queue.Queue = queue.Queue(maxsize=100)
        with sse_lock:
            sse_clients.append(q)
        try:
            for entry in sensor_buffer[-10:]:
                yield f"data: {json.dumps(entry, ensure_ascii=False, default=str)}\n\n"
            while True:
                try:
                    yield q.get(timeout=25)
                except queue.Empty:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            pass
        finally:
            with sse_lock:
                if q in sse_clients:
                    sse_clients.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─── Bootstrap ────────────────────────────────────────────────────────────────
def ensure_ready():
    os.makedirs("logs", exist_ok=True)
    db.init_db()
    if not db.is_seeded():
        print("  Banco vazio — gerando dados sintéticos (seed fixa)...")
        from data.generate_dataset import generate_training_dataset, seed_database
        seed_database(reset=False)
        generate_training_dataset()
    if not os.path.exists(MODEL_PATH):
        print("  Modelo não encontrado — treinando (scikit-learn)...")
        m = train_model()
        print(f"  RandomForest AUC={m['random_forest']['roc_auc']}  IsolationForest AUC={m['isolation_forest']['roc_auc_as_detector']}")
    pipeline.get_model(reload=True)
    print(f"  Base de conhecimento (RAG): {len(pipeline.get_kb())} trechos")
    if not db.list_latest_insights():
        print("  Primeira triagem (modo template, em background)...")
        threading.Thread(target=pipeline.analyze_all, kwargs={"llm_mode": "offline"}, daemon=True).start()


if __name__ == "__main__":
    print("=" * 56)
    print("  CLYVO VET — Dashboard + CLYVO Copilot (Sprint 3)")
    print("=" * 56)
    ensure_ready()
    has_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    print(f"  LLM: {'Claude (' + os.getenv('CLYVO_LLM_MODEL', 'claude-opus-5') + ')' if has_key else 'modo template (sem ANTHROPIC_API_KEY)'}")
    print(f"  Copilot roda a cada {ANALYZE_EVERY} leituras por pet")
    print("  Acesse: http://localhost:5000")
    print("=" * 56)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
