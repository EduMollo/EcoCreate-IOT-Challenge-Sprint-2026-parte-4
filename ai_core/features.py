"""
C1 — Feature engineering: baseline individual + z-score

Substitui o threshold fixo de _check_alerts() do Sprint 2. Em vez de
comparar o pet contra uma faixa populacional, comparamos contra o
histórico DELE (EWMA), gerando z-scores e tendências (slopes).

    "Thor está 2,4σ acima do baseline dele" ≠ "Thor está 39,4°C"

Também produz as features clínicas (idade, vacinas, adesão a medicamentos)
que alimentam o modelo preditivo junto com a telemetria.
"""

import math
from datetime import date, datetime

# Coluna do banco -> prefixo curto usado nos nomes de feature
METRICS = {
    "temperature_c":  "temp",
    "heart_rate_bpm": "hr",
    "spo2_pct":       "spo2",
    "activity_score": "act",
}

TELEMETRY_FEATURES = [
    "temp_z", "hr_z", "spo2_z", "act_z",
    "temp_slope", "hr_slope", "spo2_slope", "act_slope",
]
CLINICAL_FEATURES = [
    "age_years", "weight_kg", "is_cat",
    "days_since_last_consult", "vaccine_overdue_days", "med_adherence_pct",
]
FEATURE_ORDER = TELEMETRY_FEATURES + CLINICAL_FEATURES

# Rótulos legíveis (usados na explicação do risco e no briefing clínico)
FEATURE_LABELS = {
    "temp_z":  "Temperatura vs. baseline individual",
    "hr_z":    "Frequência cardíaca vs. baseline individual",
    "spo2_z":  "SpO₂ vs. baseline individual",
    "act_z":   "Nível de atividade vs. baseline individual",
    "temp_slope": "Tendência da temperatura (janela recente)",
    "hr_slope":   "Tendência da frequência cardíaca (janela recente)",
    "spo2_slope": "Tendência da SpO₂ (janela recente)",
    "act_slope":  "Tendência da atividade (janela recente)",
    "age_years":  "Idade",
    "weight_kg":  "Peso",
    "is_cat":     "Espécie (gato)",
    "days_since_last_consult": "Dias desde a última consulta",
    "vaccine_overdue_days":    "Dias de atraso vacinal",
    "med_adherence_pct":       "Adesão a medicamentos",
}

# Prior populacional por espécie — usado APENAS como baseline de partida
# enquanto o pet não tem histórico suficiente (cold start).
SPECIES_PRIOR = {
    "dog": {"temp": (38.5, 0.35), "hr": (90.0, 15.0),  "spo2": (97.5, 1.0), "act": (0.50, 0.15)},
    "cat": {"temp": (38.8, 0.35), "hr": (160.0, 25.0), "spo2": (97.5, 1.0), "act": (0.45, 0.15)},
}

RECENT_K = 10          # tamanho da janela "recente"
MIN_BASELINE = 15      # leituras mínimas para confiar no baseline individual
EWMA_ALPHA = 0.1


# ─── Estatística básica ───────────────────────────────────────────────────────
def ewma_stats(values: list[float], alpha: float = EWMA_ALPHA) -> tuple[float, float]:
    """Média e desvio-padrão exponencialmente ponderados (mais peso no recente)."""
    if not values:
        return float("nan"), float("nan")
    mean = values[0]
    var = 0.0
    for v in values[1:]:
        diff = v - mean
        mean += alpha * diff
        var = (1 - alpha) * (var + alpha * diff * diff)
    return mean, math.sqrt(max(var, 1e-12))


def linear_slope(values: list[float]) -> float:
    """Variação total prevista pela reta de mínimos quadrados ao longo da janela."""
    n = len(values)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return (num / den) * (n - 1)


def _column(readings: list[dict], col: str) -> list[float]:
    return [float(r[col]) for r in readings if r.get(col) is not None]


# ─── Telemetria ───────────────────────────────────────────────────────────────
def telemetry_features(readings: list[dict], species: str = "dog", recent_k: int = RECENT_K) -> dict:
    """
    readings: ordenadas da mais antiga para a mais recente.
    Retorna z-scores e slopes por métrica + metadados para explicação.
    """
    prior = SPECIES_PRIOR.get(species, SPECIES_PRIOR["dog"])
    out: dict = {"n_readings": len(readings), "baseline_source": {}, "baseline": {}, "recent": {}}

    for col, key in METRICS.items():
        series = _column(readings, col)
        pm, ps = prior[key]

        if not series:
            out[f"{key}_z"] = 0.0
            out[f"{key}_slope"] = 0.0
            out["baseline_source"][key] = "none"
            out["baseline"][key] = {"mean": pm, "std": ps}
            out["recent"][key] = None
            continue

        recent = series[-recent_k:]
        history = series[:-recent_k] if len(series) > recent_k else []

        if len(history) >= MIN_BASELINE:
            bm, bs = ewma_stats(history)
            bs = max(bs, 0.25 * ps)          # evita σ colapsado em séries muito estáveis
            source = "individual"
        elif history:
            # Mistura prior + pouco histórico (transição suave de cold start)
            hm, hs = ewma_stats(history)
            w = len(history) / MIN_BASELINE
            bm = w * hm + (1 - w) * pm
            bs = max(w * hs + (1 - w) * ps, 0.25 * ps)
            source = "blended"
        else:
            bm, bs, source = pm, ps, "prior"

        recent_mean = sum(recent) / len(recent)
        out[f"{key}_z"] = round((recent_mean - bm) / bs, 3)
        # slope em σ do baseline: adimensional, comparável entre métricas e com o dataset de treino.
        # Denominador com piso mais alto que o do z-score: tendência é mais sensível a ruído.
        out[f"{key}_slope"] = round(linear_slope(recent) / max(bs, 0.5 * ps), 3)
        out["baseline_source"][key] = source
        out["baseline"][key] = {"mean": round(bm, 2), "std": round(bs, 3)}
        out["recent"][key] = round(recent_mean, 2)

    return out


# ─── Clínico ──────────────────────────────────────────────────────────────────
def _to_date(s) -> date | None:
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.fromisoformat(str(s)[:19]).date()
    except ValueError:
        return None


def age_years(birth_date, today: date = None) -> float:
    b = _to_date(birth_date)
    if not b:
        return 0.0
    today = today or date.today()
    return round((today - b).days / 365.25, 2)


def clinical_features(pet: dict, vaccines: list[dict], consultations: list[dict],
                      medications: list[dict], today: date = None) -> dict:
    today = today or date.today()

    # Dias desde a última consulta (sem consulta = 730, "nunca visto")
    dates = [d for d in (_to_date(c.get("date")) for c in consultations) if d]
    days_since = (today - max(dates)).days if dates else 730

    # Maior atraso vacinal entre as vacinas com next_due definido
    overdue = 0
    for v in vaccines:
        nd = _to_date(v.get("next_due"))
        if nd and nd < today:
            overdue = max(overdue, (today - nd).days)

    # Adesão média nos medicamentos ativos/recentes com doses esperadas
    ratios = []
    for m in medications:
        exp = m.get("doses_expected") or 0
        if exp > 0:
            ratios.append(min(1.0, (m.get("doses_confirmed") or 0) / exp))
    adherence = round(100 * sum(ratios) / len(ratios), 1) if ratios else 100.0

    return {
        "age_years": age_years(pet.get("birth_date"), today),
        "weight_kg": float(pet.get("weight_kg") or 0.0),
        "is_cat": 1 if pet.get("species") == "cat" else 0,
        "days_since_last_consult": days_since,
        "vaccine_overdue_days": overdue,
        "med_adherence_pct": adherence,
    }


# ─── Vetor para o modelo ──────────────────────────────────────────────────────
def to_vector(features: dict, order: list[str] = FEATURE_ORDER) -> list[float]:
    vec = []
    for f in order:
        v = features.get(f, 0.0)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        if math.isnan(v) or math.isinf(v):
            v = 0.0
        vec.append(v)
    return vec


def age_group(years: float) -> str:
    if years < 1:
        return "filhote"
    if years >= 7:
        return "senior"
    return "adulto"
