# LGPD, responsabilidade clínica e guardrails

## 1. O sistema não diagnostica

O CLYVO Copilot **não é um dispositivo de diagnóstico** e não substitui o médico-veterinário (Lei 5.517/68 e resoluções do CFMV sobre responsabilidade técnica). Ele:

- detecta que **algo mudou** em relação ao padrão do próprio pet;
- organiza a **próxima ação** conforme protocolo da clínica;
- **redige** a comunicação — que só sai após aprovação humana.

Toda mensagem ao tutor carrega o aviso: *"Mensagem gerada pelo CLYVO Copilot e revisada pela equipe. Não substitui avaliação do médico-veterinário."*

## 2. Human-in-the-loop

| Etapa | Quem decide | Onde fica registrado |
|---|---|---|
| Cálculo de risco, ações e serviços | sistema (determinístico + preditivo) | `insights` (features, fatores, ações) |
| Redação da mensagem | LLM ou template | `insights.tutor_message`, `llm_mode`, `guardrail_json` |
| **Envio ao tutor** | **médico-veterinário** (`POST /api/insights/:id/approve`) | `insights.approved`, `sent_at`, `tutor_events.message_sent` |

Nenhum texto com conteúdo clínico chega ao tutor sem `approved = 1`.

## 3. Guardrails da camada generativa (`ai_core/guardrails.py`)

| Verificação | Regra | Consequência |
|---|---|---|
| Posologia | bloqueia `N mg / ml / mcg / comprimidos / gotas` | descarta saída do LLM → template |
| Prescrição | bloqueia `prescrev*`, `receit*` | idem |
| Diagnóstico afirmado | bloqueia `diagnóstico é / : / de / confirmado` | idem |
| Doença como fato | bloqueia `está com / tem / apresenta + <doença>` | idem |
| Medicamento nomeado | bloqueia dipirona, paracetamol, antibiótico, corticoide… | idem |
| Ancoragem | exige nome do pet **e** chamada para ação (agendar/consulta/clínica) | idem |
| Tamanho | tutor ≤ 700 caracteres; briefing ≤ 2.500 | idem |
| Disclaimer | sempre anexado à mensagem ao tutor | — |
| Recusa do modelo | `stop_reason == "refusal"` → template | registrado em `llm_error` |

Além disso, o **prompt de sistema** proíbe explicitamente diagnóstico, medicamento, dose e invenção de fatos, e o **structured output** (JSON Schema) garante que a resposta tenha exatamente dois campos.

## 4. LGPD (Lei 13.709/2018)

| Princípio | Como o CLYVO VET atende |
|---|---|
| **Finalidade** | Dados usados apenas para cuidado preventivo do pet e comunicação com o tutor sobre ele |
| **Minimização** | Do tutor: nome, telefone, canal e horário preferidos. Nenhum dado sensível do humano |
| **Consentimento** | Registrado no cadastro do app; comunicações só no canal consentido |
| **Transparência** | Toda mensagem informa que foi gerada com apoio de IA e revisada; o tutor pode pedir explicação |
| **Segurança** | Banco local com acesso restrito à clínica; chave da API em `.env` (nunca versionada); sem envio de dados pessoais em URL |
| **Retenção** | Telemetria bruta: 12 meses; agregados/baselines: enquanto o pet estiver ativo; eventos IoB: 24 meses |
| **Direitos do titular** | Exclusão ou portabilidade sob solicitação (`DELETE` em cascata por `tutor_id`) |

**O que sai para terceiros:** apenas o contexto estruturado necessário à redação (nome do pet, primeiro nome do tutor, sinais e ações) é enviado à API do Claude — sem telefone, sem histórico completo, sem dados de outros tutores. Em modo offline, nada sai da máquina.

## 5. Riscos residuais e mitigação

| Risco | Mitigação |
|---|---|
| Falso positivo gera ansiedade no tutor | Linguagem sem alarmismo (diretriz na base RAG); tom ajustado pelo IoB; aprovação humana |
| Falso negativo (desvio não detectado) | Limites absolutos do Sprint 2 continuam ativos como última linha de defesa (P1) |
| Sensor ruidoso (pelagem, movimento) | Features usam janela de 10 leituras e σ com piso; nunca uma leitura isolada |
| Modelo treinado em dados sintéticos | Declarado na documentação; retreino com desfechos reais previsto no roadmap |
| Dependência do LLM | Fallback template determinístico; a decisão nunca depende do LLM |
