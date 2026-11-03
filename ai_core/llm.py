"""
C5 - IA Generativa (Claude API) + RAG

O LLM entra por ULTIMO e s� redige. Recebe a decisao j� tomada pelas
camadas C1-C4 (score, a�oes por prioridade, servi�os, perfil do tutor) e
trechos da base de conhecimento da cl�nica (RAG), e devolve dois textos:
    tutor_message  - WhatsApp para o tutor, linguagem simples
    vet_briefing   - briefing t�cnico para o veterin�rio

Padrao herdado do Sprint 2 (YOLO sem pesos -> modo simula�ao): sem
credenciais da Anthropic, ou com CLYVO_LLM_MODE=offline, o sistema cai em
modo template determin�stico. A demo nunca quebra.
"""

import json
import os

MODEL = os.getenv("CLYVO_LLM_MODEL", "")
EFFORT = os.getenv("CLYVO_LLM_EFFORT", "low")          # reda�ao curta: esfor�o baixo basta
DEFAULT_MODE = os.getenv("CLYVO_LLM_MODE", "auto")     # auto | offline

# Prompt de sistema ESTAVEL (cache�vel). Conte�do vari�vel vai no turno do usu�rio.
SYSTEM_PROMPT = """Voc� � o CLYVO Copilot, assistente de comunica�ao de uma cl�nica veterin�ria brasileira.

Voc� NAO toma decisao cl�nica. Voc� recebe uma decisao j� tomada por um sistema determin�stico
(score de risco, a�oes priorizadas por protocolo, servi�os recomendados, perfil do tutor) e sua �nica
tarefa � redigir dois textos em portugu�s do Brasil:

1. tutor_message - mensagem de WhatsApp para o tutor do pet.
2. vet_briefing - briefing cl�nico objetivo para o m�dico-veterin�rio.

Regras inviol�veis:
- Nunca afirme diagn�stico, nunca nomeie doen�a como fato, nunca cite medicamento nem dose.
- Use somente os fatos do contexto. Nao invente valores, datas, servi�os ou pre�os.
- tutor_message: chame o pet pelo nome; explique em linguagem simples o que mudou (sem jargao, sem
  desvio-padrao/z-score); indique UMA a�ao principal (a de maior prioridade); convide para agendar
  usando o canal/facilidade indicados; siga o tom sugerido pelo perfil de engajamento. M�ximo 550
  caracteres. No m�ximo 2 emojis. Se houver a�ao "Urgente", pe�a contato imediato com a cl�nica.
- vet_briefing: t�picos curtos - Risco (score, n�vel, probabilidade), Sinais (m�trica, valor recente,
  baseline, z), A�oes pendentes (por prioridade), Servi�os sugeridos, Perfil do tutor. Linguagem
  t�cnica, sem recomenda�ao terap�utica. M�ximo 1600 caracteres.
- Os trechos da base de conhecimento servem para embasar o tom e a orienta�ao; nao copie literalmente.

Responda apenas com o JSON pedido."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tutor_message": {"type": "string"},
        "vet_briefing": {"type": "string"},
    },
    "required": ["tutor_message", "vet_briefing"],
    "additionalProperties": False,
}


# ��� Prompt �������������������������������������������������������������������
def build_rag_query(ctx: dict) -> str:
    parts = [ctx["pet"]["species_label"]]
    parts += [f["label"] for f in ctx["risk"]["top_factors"]]
    parts += [a["title"] for a in ctx["actions"][:3]]
    parts += [s["name"] for s in ctx["services"][:2]]
    parts.append(f"engajamento {ctx['tutor']['engagement']}")
    return " ".join(parts)


def build_user_prompt(ctx: dict, snippets: list[dict]) -> str:
    kb = "\n\n".join(f"[{s['source']} > {s['heading']}]\n{s['text']}" for s in snippets) or "(nenhum trecho)"
    return (
        "CONTEXTO ESTRUTURADO (fonte �nica de verdade):\n"
        f"{json.dumps(ctx, ensure_ascii=False, indent=2)}\n\n"
        "TRECHOS DA BASE DE CONHECIMENTO DA CLINICA:\n"
        f"{kb}\n\n"
        "Gere o JSON com tutor_message e vet_briefing."
    )


# ��� Template determin�stico (fallback) ���������������������������������������
def _plain_changes(ctx: dict) -> str:
    pet = ctx["pet"]["name"]
    pron = "ela" if (ctx["pet"].get("sex") or "").upper().startswith("F") else "ele"
    f = ctx["telemetry"]["z"]
    sentences = []
    if (f.get("temp_z") or 0) >= 1.5:
        sentences.append(f"a temperatura de {pet} est� um pouco acima do normal d{pron}")
    if (f.get("hr_z") or 0) >= 1.5:
        sentences.append(f"o cora�ao d{pron} est� batendo mais r�pido que o costume")
    elif (f.get("hr_z") or 0) <= -1.5:
        sentences.append(f"o cora�ao d{pron} est� batendo mais devagar que o costume")
    if (f.get("spo2_z") or 0) <= -1.5:
        sentences.append(f"a oxigena�ao d{pron} est� um pouco abaixo do padrao")
    if (f.get("act_z") or 0) <= -1.5:
        sentences.append(f"{pron} est� se movimentando menos que o habitual")
    if not sentences:
        return ""
    if len(sentences) == 1:
        return f"Notamos pelos sensores que {sentences[0]}."
    return f"Notamos pelos sensores que {', '.join(sentences[:-1])} e {sentences[-1]}."


def template_generate(ctx: dict) -> dict:
    pet = ctx["pet"]["name"]
    tutor_first = (ctx["tutor"]["name"] or "tutor").split()[0]
    actions = ctx["actions"]
    services = ctx["services"]
    urgent = any(a["priority_label"] == "Urgente" for a in actions)
    top = actions[0] if actions else {"title": "check-up de rotina", "priority_label": "Rotina", "reason": ""}
    svc = services[0]["name"] if services else "uma consulta"
    channel = ctx["tutor"]["preferred_channel"]
    low_eng = ctx["tutor"]["engagement"] == "baixo"

    changes = _plain_changes(ctx)
    if urgent:
        msg = (f"{tutor_first}, aqui � a equipe CLYVO VET. {changes or f'Os sensores de {pet} indicaram uma altera�ao importante.'} "
               f"Pedimos que entre em contato com a cl�nica agora mesmo pelo {channel} ou telefone para orientarmos "
               f"os pr�ximos passos. Estamos � disposi�ao. ??")
    else:
        why = f" ({top['reason']})" if top.get("reason") and top["priority_label"] in ("Alta", "M�dia") else ""
        ask = (f"Para facilitar, podemos fazer uma teleconsulta r�pida ou agendar em um toque pelo link."
               if low_eng else f"Podemos agendar {svc.lower()} para esta semana?")
        msg = (f"Ol�, {tutor_first}! Aqui � a equipe CLYVO VET. {changes} "
               f"Nossa recomenda�ao para {pet} agora �: {top['title'].lower()}{why}. {ask} "
               f"� s� responder por aqui. ??").replace("  ", " ")

    r = ctx["risk"]
    tel = ctx["telemetry"]
    lines = [
        f"RISCO - score {r['risk_score']}/100 ({r['risk_level']}); P(aten�ao 7d) = {r['prob_attention_7d']:.0%}; "
        f"anomalia = {r['anomaly_score']:.2f}; origem = {r['mode']}.",
        "SINAIS - " + "; ".join(
            f"{k}: {tel['recent'].get(k)} (baseline {tel['baseline'][k]['mean']} � {tel['baseline'][k]['std']}, "
            f"z {tel['z'].get(k + '_z'):+.1f}, fonte {tel['baseline_source'].get(k)})"
            for k in ("temp", "hr", "spo2", "act") if tel["recent"].get(k) is not None) or "SINAIS - sem telemetria.",
        "FATORES - " + ("; ".join(f"{f['label']}: {f['value_text']}" for f in r["top_factors"]) or "nenhum relevante."),
        "A�OES - " + ("; ".join(f"[{a['priority_label']}] {a['title']} - {a['reason']}" for a in actions) or "nenhuma pendente."),
        "SERVI�OS - " + ("; ".join(f"{s['name']} (R$ {s['price_brl']}; {', '.join(s['why'][:2])})" for s in services) or "-"),
        f"TUTOR - engajamento {ctx['tutor']['engagement']} (score {ctx['tutor']['engagement_score']}); "
        f"canal {ctx['tutor']['preferred_channel']} ~{ctx['tutor']['preferred_hour']:02d}h; "
        f"{'; '.join(ctx['tutor']['nudges'][:2])}.",
        f"CLINICO - �ltima consulta h� {ctx['clinical']['days_since_last_consult']} d; atraso vacinal "
        f"{ctx['clinical']['vaccine_overdue_days']} d; adesao {ctx['clinical']['med_adherence_pct']}%.",
    ]
    return {"tutor_message": msg, "vet_briefing": "\n".join(lines), "mode": "template",
            "model": None, "rag_sources": [], "error": None}


# ��� Claude �������������������������������������������������������������������
def _has_credentials() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def claude_generate(ctx: dict, snippets: list[dict]) -> dict:
    if not MODEL:
        raise ValueError("Configure CLYVO_LLM_MODEL")
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": build_user_prompt(ctx, snippets)}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        cat = response.stop_details.category if response.stop_details else None
        raise RuntimeError(f"refusal ({cat})")
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return {
        "tutor_message": data["tutor_message"].strip(),
        "vet_briefing": data["vet_briefing"].strip(),
        "mode": "claude",
        "model": response.model,
        "rag_sources": [f"{s['source']} > {s['heading']}" for s in snippets],
        "error": None,
        "usage": {"input": response.usage.input_tokens, "output": response.usage.output_tokens,
                  "cache_read": getattr(response.usage, "cache_read_input_tokens", 0)},
    }


def _alternative_generate(provider, ctx, snippets):
    import requests
    prompt = build_user_prompt(ctx, snippets)
    if provider == 'gateway':
        from flask import has_request_context, request

        token = os.getenv('AI_GATEWAY_API_KEY')
        if not token and has_request_context():
            token = request.headers.get('x-vercel-oidc-token')
        token = token or os.getenv('VERCEL_OIDC_TOKEN')
        if not token:
            raise RuntimeError('Gateway authentication unavailable')
        model = os.getenv('CLYVO_GATEWAY_MODEL', 'google/gemini-2.5-flash-lite')
        response = requests.post(
            'https://ai-gateway.vercel.sh/v1/chat/completions',
            headers={'Authorization': f'Bearer {token}'},
            json={'model': model,
                  'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                               {'role': 'user', 'content': prompt}],
                  'response_format': {'type': 'json_schema',
                                      'json_schema': {'name': 'copilot_message',
                                                      'strict': True, 'schema': OUTPUT_SCHEMA}},
                  'max_completion_tokens': 900},
            timeout=(5, 30))
        response.raise_for_status()
        data = json.loads(response.json()['choices'][0]['message']['content'])
    elif provider == 'gemini':
        model = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite')
        response = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key': os.environ['GEMINI_API_KEY']},
            json={'systemInstruction': {'parts': [{'text': SYSTEM_PROMPT}]},
                  'contents': [{'parts': [{'text': prompt}]}],
                  'generationConfig': {'responseMimeType': 'application/json',
                                       'responseJsonSchema': OUTPUT_SCHEMA}}, timeout=(5, 35))
        response.raise_for_status()
        data = json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'])
    else:
        model = os.getenv('OLLAMA_MODEL', 'qwen2.5:3b')
        response = requests.post(os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434') + '/api/generate',
                                 json={'model': model, 'system': SYSTEM_PROMPT, 'prompt': prompt,
                                       'format': OUTPUT_SCHEMA, 'stream': False,
                                       'options': {'temperature': 0}}, timeout=(5, 35))
        response.raise_for_status()
        data = json.loads(response.json()['response'])
    if any(not isinstance(data.get(k), str) or not data[k].strip() for k in OUTPUT_SCHEMA['required']):
        raise ValueError('invalid generated fields')
    return {**data, 'mode': provider, 'model': model, 'error': None,
            'rag_sources': [f"{s['source']} > {s['heading']}" for s in snippets]}


def generate(ctx: dict, kb=None, mode: str = None, *, allow_gateway=False) -> dict:
    """Ponto de entrada. mode: auto | offline."""
    mode = mode or DEFAULT_MODE
    snippets = kb.search(build_rag_query(ctx), k=3) if kb is not None else []

    provider = os.getenv('CLYVO_LLM_PROVIDER', 'auto')
    if provider == 'gateway' and not allow_gateway:
        mode = 'offline'
    if provider == 'auto':
        provider = 'gemini' if os.getenv('GEMINI_API_KEY') else 'claude' if _has_credentials() else 'template'
    if provider in ('gemini', 'ollama', 'gateway') and mode != 'offline':
        try:
            if not snippets:
                raise ValueError('no relevant knowledge retrieved')
            return _alternative_generate(provider, ctx, snippets)
        except Exception:
            out = template_generate(ctx)
            out['error'] = f'{provider} indispon�vel ou resposta inv�lida; usando template'
            out['rag_sources'] = [f"{s['source']} > {s['heading']}" for s in snippets]
            return out

    if mode == "offline" or provider == 'template' or not _has_credentials():
        out = template_generate(ctx)
        out["rag_sources"] = [f"{s['source']} > {s['heading']}" for s in snippets]
        out["error"] = None if mode == "offline" or os.getenv('CLYVO_LLM_PROVIDER') == 'template' else "Gera�ao nao configurada; usando template."
        return out

    try:
        return claude_generate(ctx, snippets)
    except Exception as exc:  # noqa: BLE001 - qualquer falha do LLM cai no template, nunca derruba o pipeline
        err = type(exc).__name__
        out = template_generate(ctx)
        out["rag_sources"] = [f"{s['source']} > {s['heading']}" for s in snippets]
        out["error"] = f"Claude indispon�vel ({err}); usando template"
        return out
