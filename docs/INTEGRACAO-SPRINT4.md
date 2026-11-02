# Integração Sprint 4

## Fluxo

Navegador autenticado → Java verifica perfil e posse → lê pet e prontuário → API Python autenticada → features/modelos/regras → RAG/redação/validação → Java persiste contexto e resultado → veterinário aprova → tutor lê → evento IoB.

Não se mantém cadastro duplicado no SQLite. O Python não recebe usuário, senha, email, telefone ou endereço do tutor. O nome do tutor é substituído por “Tutor”. O nome do pet e o contexto clínico necessário continuam presentes; a demonstração deve usar dados fictícios.

## Contrato de entrada

```json
{
  "pet": {"id": 1, "name": "Thor", "species": "dog", "birth_date": "2020-01-01", "weight_kg": 20, "tutor_name": "Tutor"},
  "readings": [{"ts":"2026-11-01T20:00:00Z","temperature_c":38.5,"heart_rate_bpm":90,"spo2_pct":97.5,"activity_score":0.5}],
  "vaccines": [], "consultations": [], "medications": [], "events": [], "simulated": true
}
```

Atualize os timestamps ao testar. `species`: dog/cat. `vaccines`: vaccine, applied_at, next_due. `consultations`: id, date, reason, return_due, returned. `medications`: id, name, start_date, end_date, doses_expected, doses_confirmed. `events`: event_type, ts, channel. Não inventar confirmação de doses a partir da prescrição.

## Contrato de saída

`schema_version`, `pet_id`, `ts`, `risk` (score, nível, probabilidade experimental, anomalia, fatores), `priority`, `priority_label`, `actions`, `services`, `tutor_profile`, `tutor_message`, `vet_briefing`, `llm_mode`, `llm_model`, `llm_error`, `rag_sources`, `rag_used`, `warnings`, `guardrail`, `features`, `baseline`, `baseline_source`, `model_version`, `simulated`.

O Java verifica associação ao pet e campos essenciais. O score não é reescrito pela regra: uma prioridade urgente aparece separadamente para evitar ocultar o limite absoluto ultrapassado.

## Persistência

- `cv4_copilot_window`: janelas simuladas versionadas.
- `cv4_copilot_insight`: contexto enviado, resultado, criação e aprovação com usuário/data.
- `cv4_copilot_event`: disponibilização no portal e leitura confirmada; unicidade por análise/tipo.

V7 existe para H2, PostgreSQL e Oracle. PostgreSQL usa TEXT; Oracle usa CLOB. Não há execução Oracle ou PostgreSQL comprovada desta alteração até testes externos. A entrega Database anterior permanece separada.

## Configuração publicada

1. Criar o repositório IoT Sprint 4 e importar como projeto Flask separado na Vercel.
2. Usar Python 3.12, `requirements.txt`, `app.py` e build `python -m ai_core.risk_model train`.
3. Configurar `COPILOT_API_TOKEN` privado no Python.
4. Configurar `COPILOT_URL` e `COPILOT_TOKEN` equivalentes no Java e publicar a versão testada.
5. Configurar provedor de geração real se disponível. Sem isso, mostrar template e registrar a limitação.
6. Validar `/health` e executar a jornada completa no portal publicado com dados fictícios.

Não desligar a proteção de deployment indiscriminadamente. Se o endpoint exigir Vercel Authentication, configurar acesso servidor a servidor compatível antes de liberar a integração. O bearer da aplicação não substitui a autenticação da plataforma.

Transporte Java tem timeout de conexão 5s, leitura 55s e resposta limitada a 256 KiB. Python limita corpo a 512 KiB e listas a 500 elementos. Chamadas de geração têm timeout e contingência; não há processamento em segundo plano dependente da memória da função.

## Fontes de implementação consultadas

- https://vercel.com/docs/frameworks/backend/flask
- https://vercel.com/docs/functions/limitations
- https://ai.google.dev/gemini-api/docs/billing
- https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- https://docs.ollama.com/api/generate
