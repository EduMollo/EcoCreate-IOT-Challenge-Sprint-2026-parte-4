"""
C3 — Motor de regras clínicas

Protocolos determinísticos e auditáveis (protocols.yaml). Aqui não há
aprendizado: se a vacina venceu, venceu. A IA prioriza e comunica; ela
não revoga protocolo.

Cada regra emite uma "ação" no formato:
    {code, category, title, reason, priority, priority_label, due_date, source}
priority: 1 = Urgente, 2 = Alta, 3 = Média, 4 = Rotina
"""

import os
from datetime import date, timedelta
from functools import lru_cache

import yaml

from .features import _to_date as to_date, age_years

PROTOCOLS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "protocols.yaml")
PRIORITY_LABELS = {1: "Urgente", 2: "Alta", 3: "Média", 4: "Rotina"}


@lru_cache(maxsize=1)
def load_protocols() -> dict:
    with open(PROTOCOLS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _action(code, category, title, reason, priority, due: date | None) -> dict:
    return {
        "code": code,
        "category": category,
        "title": title,
        "reason": reason,
        "priority": priority,
        "priority_label": PRIORITY_LABELS[priority],
        "due_date": due.isoformat() if due else None,
        "source": "rule",
    }


def _matches(name: str, patterns: list[str]) -> bool:
    n = (name or "").lower()
    return any(p.lower() in n for p in patterns)


def _fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


# ─── Regras ───────────────────────────────────────────────────────────────────
def rule_telemetry_safety(pet, latest_reading, P, today) -> list[dict]:
    """R6 — limite absoluto ultrapassado (herdado do Sprint 2). Sempre P1."""
    if not latest_reading:
        return []
    lim = P["telemetry"].get(pet["species"], P["telemetry"]["dog"])
    breaches = []
    t = latest_reading.get("temperature_c")
    hr = latest_reading.get("heart_rate_bpm")
    spo2 = latest_reading.get("spo2_pct")
    if t is not None and not (lim["temp"][0] <= t <= lim["temp"][1]):
        breaches.append(f"temperatura {t:.1f}°C fora de {lim['temp'][0]}–{lim['temp'][1]}°C")
    if hr is not None and not (lim["hr"][0] <= hr <= lim["hr"][1]):
        breaches.append(f"FC {hr:.0f} bpm fora de {lim['hr'][0]}–{lim['hr'][1]} bpm")
    if spo2 is not None and spo2 < lim["spo2_min"]:
        breaches.append(f"SpO₂ {spo2:.1f}% abaixo de {lim['spo2_min']}%")
    if not breaches:
        return []
    return [_action("TELEMETRY_SAFETY", "telemetria",
                    "Contato imediato com o tutor — limite absoluto ultrapassado",
                    "; ".join(breaches), 1, today)]


def rule_telemetry_drift(features, P, today) -> list[dict]:
    """R7 — desvio sustentado do baseline INDIVIDUAL (ponte entre C1 e C3)."""
    z_lim = P["telemetry"]["drift_z"]
    labels = {"temp": "temperatura", "hr": "frequência cardíaca", "spo2": "SpO₂", "act": "atividade"}
    drift = []
    for key, label in labels.items():
        z = features.get(f"{key}_z", 0.0) or 0.0
        if abs(z) >= z_lim:
            drift.append(f"{label} {z:+.1f}σ vs. baseline individual")
    if not drift:
        return []
    return [_action("TELEMETRY_DRIFT", "telemetria",
                    "Avaliação veterinária — desvio do baseline individual",
                    "; ".join(drift), 2, today + timedelta(days=1))]


def rule_vaccines(pet, vaccines, P, today) -> list[dict]:
    """R1 — protocolo vacinal por espécie."""
    cfg = P["vaccines"]
    out = []
    for proto in cfg["protocols"].get(pet["species"], []):
        matches = [v for v in vaccines if _matches(v.get("vaccine"), proto["match"])]
        if not matches:
            if age_years(pet.get("birth_date"), today) < 0.25:
                continue  # filhote muito novo: protocolo inicial começa na primeira consulta
            out.append(_action(f"VAC_MISSING_{proto['code']}", "vacina",
                               f"Regularizar {proto['name']}", "Sem registro no prontuário", 2, today))
            continue
        last = max(matches, key=lambda v: to_date(v["applied_at"]) or date.min)
        due = to_date(last.get("next_due")) or (to_date(last["applied_at"]) + timedelta(days=proto["interval_days"]))
        if due < today:
            days = (today - due).days
            out.append(_action(f"VAC_OVERDUE_{proto['code']}", "vacina",
                               f"Aplicar {proto['name']} — atrasada {days} dias",
                               f"Venceu em {_fmt(due)}", 2 if days > 30 else 3, today))
        elif (due - today).days <= cfg["due_soon_days"]:
            out.append(_action(f"VAC_DUE_{proto['code']}", "vacina",
                               f"Agendar {proto['name']}", f"Vence em {_fmt(due)}", 3, due))
    return out


def rule_deworming(medications, P, today) -> list[dict]:
    """R2 — vermifugação periódica."""
    cfg = P["deworming"]
    worm = [m for m in medications if _matches(m.get("name"), cfg["match"])]
    if not worm:
        return [_action("DEWORM_MISSING", "vermifugo", "Iniciar protocolo de vermifugação",
                        "Sem registro no prontuário", 3, today)]
    last = max(to_date(m["start_date"]) for m in worm)
    due = last + timedelta(days=cfg["interval_days"])
    if due <= today:
        return [_action("DEWORM_DUE", "vermifugo", "Vermifugação de rotina",
                        f"Última em {_fmt(last)}; intervalo de {cfg['interval_days']} dias", 3, today)]
    return []


def rule_checkup(pet, consultations, P, today) -> list[dict]:
    """R3 — check-up por faixa etária."""
    cfg = P["checkup"]
    yrs = age_years(pet.get("birth_date"), today)
    if yrs < 1:
        interval, label = cfg["puppy_interval_days"], "filhote"
    elif yrs >= cfg["senior_age_years"]:
        interval, label = cfg["senior_interval_days"], "sênior"
    else:
        interval, label = cfg["adult_interval_days"], "adulto"
    dates = [d for d in (to_date(c.get("date")) for c in consultations) if d]
    if not dates:
        return [_action("CHECKUP_FIRST", "checkup", "Primeira consulta de rotina",
                        "Sem consultas registradas", 3, today)]
    due = max(dates) + timedelta(days=interval)
    if due <= today:
        return [_action("CHECKUP_DUE", "checkup", f"Check-up {label} de rotina",
                        f"Última consulta em {_fmt(max(dates))}; intervalo {label}: {interval} dias", 3 if label != "sênior" else 2, today)]
    return []


def rule_medication_adherence(medications, P, today) -> list[dict]:
    """R4 — adesão a medicamentos ativos ou recentes."""
    cfg = P["medication"]
    out = []
    for m in medications:
        exp = m.get("doses_expected") or 0
        if exp <= 0:
            continue
        end = to_date(m.get("end_date"))
        if end and (today - end).days > cfg["lookback_days"]:
            continue
        pct = 100 * (m.get("doses_confirmed") or 0) / exp
        if pct < cfg["min_adherence_pct"]:
            out.append(_action(f"MED_ADHERENCE_{m['id']}", "medicamento",
                               f"Reforçar adesão: {m['name']}",
                               f"{pct:.0f}% das doses confirmadas (mínimo {cfg['min_adherence_pct']}%)",
                               2 if pct < 50 else 3, today))
    return out


def rule_post_procedure(consultations, P, today) -> list[dict]:
    """R5 — retorno pós-procedimento pendente."""
    warn = P["post_procedure"]["warn_days_before"]
    out = []
    for c in consultations:
        due = to_date(c.get("return_due"))
        if not due or c.get("returned"):
            continue
        if due < today:
            out.append(_action(f"RETURN_OVERDUE_{c['id']}", "pos_procedimento",
                               f"Retorno atrasado — {c.get('procedure') or c.get('reason')}",
                               f"Previsto para {_fmt(due)}", 2, today))
        elif (due - today).days <= warn:
            out.append(_action(f"RETURN_DUE_{c['id']}", "pos_procedimento",
                               f"Agendar retorno — {c.get('procedure') or c.get('reason')}",
                               f"Previsto para {_fmt(due)}", 3, due))
    return out


# ─── Avaliação ────────────────────────────────────────────────────────────────
def evaluate(pet: dict, vaccines: list[dict], consultations: list[dict], medications: list[dict],
             latest_reading: dict | None, features: dict, today: date = None) -> list[dict]:
    today = today or date.today()
    P = load_protocols()
    actions = []
    actions += rule_telemetry_safety(pet, latest_reading, P, today)
    actions += rule_telemetry_drift(features, P, today)
    actions += rule_vaccines(pet, vaccines, P, today)
    actions += rule_deworming(medications, P, today)
    actions += rule_checkup(pet, consultations, P, today)
    actions += rule_medication_adherence(medications, P, today)
    actions += rule_post_procedure(consultations, P, today)
    actions.sort(key=lambda a: (a["priority"], a["due_date"] or "9999"))
    return actions
