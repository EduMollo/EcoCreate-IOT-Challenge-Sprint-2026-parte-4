"""
Pipeline do CLYVO Copilot — orquestra as camadas em um único "insight"

    leituras + prontuário + eventos do tutor
        -> C1 features (baseline individual, z-scores, clínico)
        -> C2 risco (IsolationForest + RandomForest | heurística se não treinado)
        -> C3 regras (protocolos; regra vence modelo)
        -> C4 serviços recomendados
        -> IoB perfil do tutor
        -> C5 LLM + RAG (redige)  -> guardrails (valida)  -> template se falhar
        -> insight persistido (auditável) e aguardando aprovação do veterinário
"""

from datetime import date, datetime, timedelta

from . import db, guardrails, iob, llm, recommender, rules
from . import features as F
from .rag import KnowledgeBase
from .risk_model import heuristic_predict, load_or_none

SPECIES_LABEL = {"dog": "cão", "cat": "gato"}

_model = None
_model_checked = False
_kb = None


def get_model(reload: bool = False):
    global _model, _model_checked
    if reload or not _model_checked:
        _model = load_or_none()
        _model_checked = True
    return _model


def get_kb() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


def _model_action(risk: dict, today: date) -> dict:
    return {
        "code": "MODEL_PRIORITY", "category": "telemetria",
        "title": "Avaliação prioritária — risco preditivo elevado",
        "reason": f"Score {risk['risk_score']} ({risk['risk_level']}); "
                  f"P(atenção em 7 dias) = {risk['prob_attention_7d']:.0%}; anomalia = {risk['anomaly_score']:.2f}",
        "priority": 2, "priority_label": "Alta",
        "due_date": (today + timedelta(days=1)).isoformat(), "source": "model",
    }


def build_context(pet, feats, tel, risk, actions, services, profile, clin, today: date) -> dict:
    return {
        "today": today.strftime("%d/%m/%Y"),
        "pet": {
            "name": pet["name"], "species_label": SPECIES_LABEL.get(pet["species"], pet["species"]),
            "breed": pet.get("breed"), "sex": pet.get("sex"), "neutered": bool(pet.get("neutered")),
            "age_years": clin["age_years"], "weight_kg": clin["weight_kg"],
        },
        "tutor": {
            "name": pet.get("tutor_name"),
            **{k: profile[k] for k in ("preferred_channel", "preferred_hour", "engagement",
                                        "engagement_score", "tone_hint", "nudges")},
        },
        "risk": risk,
        "telemetry": {
            "z": {k: feats.get(k) for k in F.TELEMETRY_FEATURES},
            "recent": tel["recent"], "baseline": tel["baseline"],
            "baseline_source": tel["baseline_source"], "n_readings": tel["n_readings"],
        },
        "clinical": {k: clin[k] for k in ("days_since_last_consult", "vaccine_overdue_days", "med_adherence_pct")},
        "actions": [{k: a[k] for k in ("title", "reason", "priority", "priority_label", "due_date", "category", "source")}
                    for a in actions],
        "services": [{k: s[k] for k in ("name", "price_brl", "why")} for s in services],
    }


def analyze_pet(pet_id: int, llm_mode: str = None, persist: bool = True, today: date = None) -> dict:
    today = today or date.today()
    pet = db.get_pet(pet_id)
    if not pet:
        raise ValueError(f"pet {pet_id} não encontrado")

    readings = db.get_readings(pet_id, limit=200)
    vaccines = db.get_vaccines(pet_id)
    consultations = db.get_consultations(pet_id)
    medications = db.get_medications(pet_id)
    events = db.get_tutor_events(pet["tutor_id"])

    # C1 — features
    tel = F.telemetry_features(readings, pet["species"])
    clin = F.clinical_features(pet, vaccines, consultations, medications, today)
    feats = {k: v for k, v in tel.items() if k not in ("baseline", "recent", "baseline_source")} | clin

    # C2 — risco
    model = get_model()
    risk = model.predict(feats) if model else heuristic_predict(feats)

    # C3 — regras (regra vence modelo)
    latest = readings[-1] if readings else None
    actions = rules.evaluate(pet, vaccines, consultations, medications, latest, feats, today)
    if risk["risk_level"] in ("Alto", "Crítico") and not any(
            a["category"] == "telemetria" and a["priority"] <= 2 for a in actions):
        actions.append(_model_action(risk, today))
        actions.sort(key=lambda a: (a["priority"], a["due_date"] or "9999"))

    # IoB + C4
    profile = iob.tutor_profile(pet, events)
    services = recommender.recommend(pet, feats, risk, actions, profile)

    # C5 — redação + guardrails
    ctx = build_context(pet, feats, tel, risk, actions, services, profile, clin, today)
    gen = llm.generate(ctx, get_kb(), mode=llm_mode)
    g_tutor = guardrails.validate_tutor_message(gen["tutor_message"], pet["name"])
    g_vet = guardrails.validate_vet_briefing(gen["vet_briefing"])
    guard = {"tutor": g_tutor, "vet": g_vet, "blocked": False}
    if not (g_tutor["ok"] and g_vet["ok"]) and gen["mode"] != "template":
        fallback = llm.template_generate(ctx)
        guard["blocked"] = True
        guard["blocked_mode"] = gen["mode"]
        gen = {**gen, "tutor_message": fallback["tutor_message"], "vet_briefing": fallback["vet_briefing"],
               "mode": "template", "error": "saída do LLM bloqueada pelo guardrail; usando template"}
        guard["tutor_after"] = guardrails.validate_tutor_message(gen["tutor_message"], pet["name"])

    insight = {
        "pet_id": pet_id, "pet_name": pet["name"], "species": pet["species"], "tutor_name": pet.get("tutor_name"),
        "ts": datetime.now().isoformat(timespec="seconds"),
        "risk": risk, "actions": actions, "services": services, "tutor_profile": profile,
        "tutor_message": guardrails.with_disclaimer(gen["tutor_message"]),
        "vet_briefing": gen["vet_briefing"],
        "llm_mode": gen["mode"], "llm_model": gen.get("model"), "llm_error": gen.get("error"),
        "rag_sources": gen.get("rag_sources", []), "llm_usage": gen.get("usage"),
        "guardrail": guard,
        "features": {**feats, "telemetry": {"recent": tel["recent"], "baseline": tel["baseline"],
                                            "baseline_source": tel["baseline_source"]},
                     "tutor_profile": profile},
        "approved": 0, "sent_at": None,
    }
    if persist:
        insight["id"] = db.save_insight(pet_id, insight)
    return insight


def analyze_all(llm_mode: str = "offline") -> list[dict]:
    """Roda o Copilot em todos os pets (usado no seed e no painel de triagem)."""
    return [analyze_pet(p["id"], llm_mode=llm_mode) for p in db.list_pets()]
