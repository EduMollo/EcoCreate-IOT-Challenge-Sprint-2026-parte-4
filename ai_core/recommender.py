"""
C4 — Recomendação de serviços (content-based)

Constrói um vetor de "tags de contexto" do pet (espécie, faixa etária,
nível de risco, fatores de risco, categorias das ações pendentes e
engajamento do tutor) e o compara por similaridade de cosseno com as tags
de cada serviço do catálogo (services.yaml). Serviços que atendem ações de
prioridade 1–2 recebem um boost — a regra manda, o recomendador ordena.
"""

import math
import os
from functools import lru_cache

import yaml

from .features import age_group

SERVICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services.yaml")

TAG_LABELS = {
    "telemetria": "sinais dos sensores", "risco_moderado": "risco moderado", "risco_alto": "risco alto",
    "risco_critico": "risco crítico", "febre": "temperatura elevada", "cardiaco": "frequência cardíaca alterada",
    "respiratorio": "saturação reduzida", "atividade": "queda de atividade", "checkup": "check-up pendente",
    "vacina": "vacina pendente", "vermifugo": "vermifugação pendente", "medicamento": "adesão a medicamento",
    "pos_procedimento": "retorno pendente", "engajamento_baixo": "tutor com baixo engajamento",
    "conveniencia": "menor atrito para o tutor", "senior": "pet sênior", "adulto": "pet adulto",
    "filhote": "filhote", "rotina": "rotina preventiva", "peso": "controle de peso",
}

# Boost por categoria de ação de alta prioridade -> tag de serviço
CATEGORY_TO_TAG = {
    "telemetria": "telemetria", "vacina": "vacina", "vermifugo": "vermifugo", "checkup": "checkup",
    "medicamento": "medicamento", "pos_procedimento": "pos_procedimento",
}


@lru_cache(maxsize=1)
def load_services() -> list[dict]:
    with open(SERVICES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["services"]


def build_context_tags(pet: dict, features: dict, risk: dict, actions: list[dict], tutor_profile: dict) -> set[str]:
    tags = {age_group(features.get("age_years", 0.0))}

    level = (risk.get("risk_level") or "").lower()
    if level.startswith("mod"):
        tags.add("risco_moderado")
    elif level.startswith("alt"):
        tags.update({"risco_alto", "telemetria"})
    elif level.startswith("cr"):
        tags.update({"risco_critico", "telemetria"})

    if (features.get("temp_z") or 0) >= 1.5:
        tags.add("febre")
    if abs(features.get("hr_z") or 0) >= 1.5:
        tags.add("cardiaco")
    if (features.get("spo2_z") or 0) <= -1.5:
        tags.add("respiratorio")
    if (features.get("act_z") or 0) <= -1.5:
        tags.add("atividade")

    for a in actions:
        tag = CATEGORY_TO_TAG.get(a["category"])
        if tag:
            tags.add(tag)
            if a["priority"] >= 3:
                tags.add("rotina")

    if tutor_profile.get("engagement") == "baixo":
        tags.update({"engajamento_baixo", "conveniencia"})
    return tags


def _cosine(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def recommend(pet: dict, features: dict, risk: dict, actions: list[dict],
              tutor_profile: dict, k: int = 3) -> list[dict]:
    ctx = build_context_tags(pet, features, risk, actions, tutor_profile)
    high_priority_tags = {CATEGORY_TO_TAG.get(a["category"]) for a in actions if a["priority"] <= 2}
    high_priority_tags.discard(None)

    scored = []
    for s in load_services():
        if pet["species"] not in s.get("species", []):
            continue
        stags = set(s["tags"])
        score = _cosine(ctx, stags)
        boost = 0.35 if stags & high_priority_tags else 0.0
        overlap = ctx & stags
        if score + boost <= 0:
            continue
        scored.append({
            "code": s["code"],
            "name": s["name"],
            "description": s["description"],
            "price_brl": s["price_brl"],
            "score": round(min(1.0, score + boost), 3),
            "why": [TAG_LABELS.get(t, t) for t in sorted(overlap)],
            "source": "recommender",
        })
    scored.sort(key=lambda x: -x["score"])
    return scored[:k]
