"""
IoB — Internet of Behaviors: perfil comportamental do tutor

O sensor aqui não está no pet — está no humano. Cada interação do tutor
com a plataforma (abriu, respondeu, agendou, faltou, confirmou o remédio)
vira sinal para personalizar canal, horário, tom e tipo de ação sugerida.
"""

from collections import Counter
from datetime import datetime

ENGAGEMENT_HIGH = 0.65
ENGAGEMENT_MID = 0.35

TONE_HINTS = {
    "alto":  "direto e objetivo; o tutor responde bem — pode incluir detalhe técnico leve",
    "médio": "amigável, uma chamada para ação clara e única",
    "baixo": "curto, acolhedor, sem culpa; uma única ação, o mais fácil possível (link/1 clique)",
}


def _hour(ts: str) -> int | None:
    try:
        return datetime.fromisoformat(str(ts)[:19]).hour
    except ValueError:
        return None


def tutor_profile(tutor: dict, events: list[dict]) -> dict:
    counts = Counter(e["event_type"] for e in events)
    sent = counts.get("message_sent", 0)
    opened = counts.get("opened", 0)
    replied = counts.get("replied", 0)
    booked = counts.get("appointment_booked", 0)
    no_show = counts.get("no_show", 0)
    med_ok = counts.get("med_confirmed", 0)
    med_missed = counts.get("med_missed", 0)

    open_rate = min(1.0, opened / sent) if sent else None
    reply_rate = min(1.0, replied / sent) if sent else None
    no_show_rate = no_show / (booked + no_show) if (booked + no_show) else None
    med_rate = med_ok / (med_ok + med_missed) if (med_ok + med_missed) else None

    # Engajamento composto (valores ausentes assumem neutro 0.5)
    o = open_rate if open_rate is not None else 0.5
    r = reply_rate if reply_rate is not None else 0.5
    ns = no_show_rate if no_show_rate is not None else 0.0
    score = round(0.4 * o + 0.4 * r + 0.2 * (1 - ns), 3)
    engagement = "alto" if score >= ENGAGEMENT_HIGH else "médio" if score >= ENGAGEMENT_MID else "baixo"

    # Canal e horário aprendidos das interações efetivas (abriu/respondeu/agendou)
    effective = [e for e in events if e["event_type"] in ("opened", "replied", "appointment_booked")]
    channels = Counter(e["channel"] for e in effective if e.get("channel"))
    hours = Counter(h for h in (_hour(e["ts"]) for e in effective) if h is not None)
    preferred_channel = channels.most_common(1)[0][0] if channels else (tutor.get("preferred_channel") or "whatsapp")
    preferred_hour = hours.most_common(1)[0][0] if hours else (tutor.get("preferred_hour") or 19)

    nudges = []
    if engagement == "baixo":
        nudges.append("Oferecer agendamento em 1 clique ou teleconsulta — reduzir atrito")
    if no_show_rate and no_show_rate >= 0.3:
        nudges.append("Histórico de faltas: confirmar presença 24h antes")
    if med_rate is not None and med_rate < 0.8:
        nudges.append("Baixa confirmação de doses: ativar lembrete diário no canal preferido")
    nudges.append(f"Melhor janela de contato: {preferred_channel} por volta das {preferred_hour:02d}h")

    return {
        "events_total": len(events),
        "open_rate": None if open_rate is None else round(open_rate, 2),
        "reply_rate": None if reply_rate is None else round(reply_rate, 2),
        "no_show_rate": None if no_show_rate is None else round(no_show_rate, 2),
        "med_confirmation_rate": None if med_rate is None else round(med_rate, 2),
        "engagement_score": score,
        "engagement": engagement,
        "preferred_channel": preferred_channel,
        "preferred_hour": preferred_hour,
        "tone_hint": TONE_HINTS[engagement],
        "nudges": nudges,
    }
