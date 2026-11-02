"""Sprint 4: integration without the Sprint 3 SQLite seed."""
import math
from datetime import date, datetime, timezone


def validate_payload(p):
    if not isinstance(p, dict) or not isinstance(p.get('pet'), dict):
        raise ValueError('pet is required')
    pet = p['pet']
    if pet.get('species') not in ('dog', 'cat'):
        raise ValueError('only dog and cat are supported')
    if not isinstance(pet.get('name'), str) or not 1 <= len(pet['name']) <= 80:
        raise ValueError('invalid pet name')
    for key in ('readings', 'vaccines', 'consultations', 'medications', 'events'):
        value = p.get(key, [])
        if not isinstance(value, list) or len(value) > 500 or any(not isinstance(x, dict) for x in value):
            raise ValueError(f'invalid {key}')
    previous = None
    limits = {'temperature_c': (20, 45), 'heart_rate_bpm': (10, 400),
              'spo2_pct': (0, 100), 'activity_score': (0, 1)}
    for row in p.get('readings', []):
        ts = datetime.fromisoformat(str(row.get('ts', '')).replace('Z', '+00:00'))
        if ts.tzinfo is None:
            raise ValueError('reading timestamps need timezone')
        if previous is not None and ts <= previous:
            raise ValueError('readings must be unique and chronological')
        if ts > datetime.now(timezone.utc):
            raise ValueError('future readings are invalid')
        previous = ts
        for key, (lo, hi) in limits.items():
            v = row.get(key)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v) or not lo <= v <= hi):
                raise ValueError(f'invalid {key}')
    for event in p.get('events', []):
        if event.get('event_type') not in ('message_sent', 'opened', 'replied', 'appointment_booked',
                                          'no_show', 'med_confirmed', 'med_missed'):
            raise ValueError('invalid event_type')


def analyze(p):
    from . import features as F, rules, recommender, iob, llm, guardrails
    from .pipeline import get_model, get_kb, build_context, _model_action
    today = date.today()
    pet = p['pet']
    readings = p.get('readings', [])
    warnings = []
    if any(m.get('doses_expected', 0) == 0 for m in p.get('medications', [])):
        warnings.append('Adesão medicamentosa não medida: confirmação de doses indisponível no cadastro atual.')
    if readings:
        latest_ts = datetime.fromisoformat(readings[-1]['ts'].replace('Z', '+00:00'))
        if (datetime.now(timezone.utc) - latest_ts).total_seconds() > 86400:
            warnings.append('Telemetria desatualizada: excluída da análise atual.')
            readings = []
    if len(readings) < 25:
        warnings.append('Histórico insuficiente para baseline individual completo.')
    tel = F.telemetry_features(readings, pet['species'])
    vaccines, consultations, medications = (p.get(k, []) for k in ('vaccines', 'consultations', 'medications'))
    clin = F.clinical_features(pet, vaccines, consultations, medications, today)
    feats = {k: v for k, v in tel.items() if k not in ('baseline', 'recent', 'baseline_source')} | clin
    model = get_model()
    if model is None:
        raise RuntimeError('trained model missing: run python -m ai_core.risk_model train')
    risk = model.predict(feats)
    actions = rules.evaluate(pet, vaccines, consultations, medications,
                             readings[-1] if readings else None, feats, today)
    if risk['risk_level'] in ('Alto', 'Crítico') and not any(a['priority'] <= 2 for a in actions):
        actions.append(_model_action(risk, today))
    actions.sort(key=lambda a: (a['priority'], a['due_date'] or '9999'))
    priority = min((a['priority'] for a in actions), default=4)
    profile = iob.tutor_profile(pet, p.get('events', []))
    services = recommender.recommend(pet, feats, risk, actions, profile)
    ctx = build_context(pet, feats, tel, risk, actions, services, profile, clin, today)
    gen = llm.generate(ctx, get_kb())
    checks = {'tutor': guardrails.validate_tutor_message(gen['tutor_message'], pet['name']),
              'vet': guardrails.validate_vet_briefing(gen['vet_briefing'])}
    blocked = not all(c['ok'] for c in checks.values())
    if blocked:
        # Compact fallback avoids repeating a rejected or overlong clinical reason.
        fallback = {'tutor_message': (
            f"Tutor, os dados de {pet['name']} foram analisados pelo CLYVO Copilot. "
            + ('Entre em contato com a clínica agora para orientação da equipe veterinária.' if priority == 1
               else 'Entre em contato com a clínica para revisar o acompanhamento e agendar a próxima avaliação.')),
            'vet_briefing': f"Pet: {pet['name']}. Score experimental: {risk['risk_score']}/100. "
                            f"Prioridade: {priority}. Revisar dados e ações estruturadas antes de orientar o tutor."}
        gen.update(tutor_message=fallback['tutor_message'], vet_briefing=fallback['vet_briefing'],
                   mode='template', error='Texto substituído após validação de conteúdo.')
        checks['final_tutor'] = guardrails.validate_tutor_message(gen['tutor_message'], pet['name'])
        checks['final_vet'] = guardrails.validate_vet_briefing(gen['vet_briefing'])
        if not checks['final_tutor']['ok'] or not checks['final_vet']['ok']:
            raise ValueError('Unable to produce valid draft')
    return dict(pet_id=pet.get('id'), pet_name=pet['name'], ts=datetime.now(timezone.utc).isoformat(),
                risk=risk, priority=priority, priority_label={1:'Urgente',2:'Alta',3:'Média',4:'Rotina'}[priority],
                actions=actions, services=services, tutor_profile=profile,
                tutor_message=guardrails.with_disclaimer(gen['tutor_message']), vet_briefing=gen['vet_briefing'],
                llm_mode=gen['mode'], llm_model=gen.get('model'), llm_error=gen.get('error'),
                rag_sources=gen.get('rag_sources', []), rag_used=gen['mode'] != 'template',
                warnings=warnings, simulated=bool(p.get('simulated', False)),
                guardrail={'blocked': blocked, **checks}, features=feats,
                baseline=tel['baseline'], baseline_source=tel['baseline_source'],
                model_version='sprint4-synthetic:' + str(model.trained_at), schema_version='1.0')
