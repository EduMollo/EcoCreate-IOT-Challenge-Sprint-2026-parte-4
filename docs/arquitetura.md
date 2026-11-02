# Arquitetura — CLYVO VET + CLYVO Copilot

> Diagrama arquitetural mostrando a comunicação entre aplicação, banco de dados, APIs e componentes de IA (Sprint 3).
> O GitHub renderiza o Mermaid abaixo nativamente. Uma exportação em PNG está em `docs/arquitetura.png`.

## Visão geral

```mermaid
flowchart TB
    subgraph EDGE["Dispositivos (Sprint 2 → 3)"]
        ESP["ESP32 + DHT22 + MAX30102 + MPU6050<br/>(Wokwi / iot_sensor_simulation.py)"]
        CAM["Câmera + YOLOv4-tiny<br/>(pet_detection.py → ActivityTracker)"]
    end

    subgraph APP["Aplicação — Flask (dashboard_server.py)"]
        API_IN["POST /api/sensor-data<br/>POST /api/activity"]
        API_COP["API do Copilot<br/>/api/triage · /api/analyze · /api/insights/:id/approve<br/>/api/tutor-events · /api/model/metrics"]
        SSE["SSE /stream"]
        UI["Dashboard web<br/>(templates/dashboard.html)"]
    end

    subgraph DB["Banco de dados — SQLite (clyvo.db)"]
        T1["tutors · pets"]
        T2["readings (telemetria)"]
        T3["vaccines · consultations · medications"]
        T4["tutor_events (IoB)"]
        T5["insights (decisões auditáveis)"]
    end

    subgraph AI["CLYVO Copilot — ai_core/"]
        C1["C1 features.py<br/>baseline individual EWMA · z-score · slope"]
        C2["C2 risk_model.py<br/>IsolationForest + RandomForest"]
        C3["C3 rules.py + protocols.yaml<br/>motor de regras clínicas"]
        C4["C4 recommender.py + services.yaml<br/>content-based"]
        IOB["iob.py<br/>perfil comportamental do tutor"]
        RAG["rag.py<br/>TF-IDF sobre knowledge/*.md"]
        C5["C5 llm.py<br/>Claude API (structured output)"]
        GR["guardrails.py<br/>validação + disclaimer CFMV"]
        PIPE["pipeline.py<br/>orquestração"]
    end

    subgraph EXT["Serviços externos"]
        CLAUDE["Anthropic Claude API<br/>claude-opus-5"]
    end

    ESP -- "HTTP POST a cada 2s" --> API_IN
    CAM -- "HTTP POST activity_score" --> API_IN
    API_IN -- "insert" --> T2
    API_IN -- "a cada N leituras" --> PIPE

    PIPE --> C1 --> C2 --> C3 --> C4 --> C5 --> GR --> PIPE
    PIPE --> IOB
    RAG --> C5
    C5 <-- "HTTPS (opcional; fallback template)" --> CLAUDE
    T1 & T2 & T3 & T4 -- "leitura" --> PIPE
    PIPE -- "save_insight" --> T5

    PIPE -- "type: insight" --> SSE --> UI
    API_IN -- "type: reading" --> SSE
    UI <--> API_COP
    API_COP -- "approve → tutor_events.message_sent" --> T4
    API_COP -- "tutor abriu / respondeu / agendou" --> T4
```

## Fluxo de dados (sequência de uma análise)

```mermaid
sequenceDiagram
    participant S as Sensor (ESP32 / sim)
    participant F as Flask
    participant DB as SQLite
    participant P as pipeline.py
    participant M as risk_model
    participant R as rules
    participant L as llm + rag
    participant G as guardrails
    participant V as Veterinário (UI)
    participant T as Tutor (WhatsApp)

    S->>F: POST /api/sensor-data {temp, hr, spo2, activity}
    F->>DB: INSERT readings
    F-->>V: SSE reading (cards + gráfico)
    Note over F: 10ª leitura do pet → dispara Copilot
    F->>P: analyze_pet(pet_id)
    P->>DB: readings(200) · vaccines · consultations · medications · tutor_events
    P->>P: C1 baseline individual → z-scores, slopes, features clínicas
    P->>M: predict(features)
    M-->>P: risk_score, P(7d), anomalia, fatores
    P->>R: evaluate(protocolos)
    R-->>P: ações por prioridade (regra vence modelo)
    P->>P: IoB perfil do tutor · C4 serviços
    P->>L: generate(contexto + trechos RAG)
    L-->>P: tutor_message, vet_briefing (JSON) — ou template
    P->>G: validate()
    G-->>P: ok | bloqueado → template
    P->>DB: INSERT insights (auditável)
    P-->>V: SSE insight (risco, ações, mensagem, briefing)
    V->>F: POST /api/insights/:id/approve
    F->>DB: approved=1 · tutor_events.message_sent
    F-->>T: mensagem liberada (canal preferido)
    T->>F: POST /api/tutor-events (opened / replied / booked)
    F->>DB: tutor_events (realimenta o IoB)
```

## Componentes

| Camada | Componente | Tecnologia | Responsabilidade |
|---|---|---|---|
| Dispositivo | `wokwi/` + `iot_sensor_simulation.py` | ESP32, DHT22, MAX30102, MPU6050 (simulados) | Telemetria a cada 2 s; alertas por limite absoluto |
| Dispositivo | `pet_detection.py` | OpenCV + YOLOv4-tiny | Detecta o pet; **deslocamento do bbox → `activity_score`** |
| Aplicação | `dashboard_server.py` | Flask + SSE | Ingestão, persistência, gatilho do Copilot, API, human-in-the-loop |
| Aplicação | `templates/dashboard.html` | HTML + Chart.js | Telemetria ao vivo, painel do Copilot, fila de triagem, IoB |
| Dados | `ai_core/db.py` | SQLite (WAL) | 8 tabelas — ver `docs/modelo-de-dados.md` |
| IA C1 | `ai_core/features.py` | Python puro | Baseline individual (EWMA), z-score, slope, features clínicas |
| IA C2 | `ai_core/risk_model.py` | scikit-learn | IsolationForest (anomalia) + RandomForest (P atenção 7 d), explicabilidade |
| IA C3 | `ai_core/rules.py` | YAML declarativo | Protocolo vacinal, vermifugação, check-up, adesão, retorno, limites |
| IA C4 | `ai_core/recommender.py` | cosseno sobre tags | Serviços da clínica compatíveis com contexto do pet e do tutor |
| IoB | `ai_core/iob.py` | Python puro | Engajamento, canal, horário e tom a partir dos eventos do tutor |
| IA C5 | `ai_core/llm.py` + `rag.py` | Anthropic SDK + TF-IDF | Redige mensagem e briefing ancorados no contexto; fallback template |
| Segurança | `ai_core/guardrails.py` | regex + regras | Bloqueia diagnóstico/posologia; exige CTA; disclaimer CFMV |
| Orquestração | `ai_core/pipeline.py` | Python | Executa C1→C5, persiste o insight, publica via SSE |

## Endpoints

| Método | Rota | Uso |
|---|---|---|
| POST | `/api/sensor-data` | Telemetria do wearable (Sprint 2, agora persistida) |
| POST | `/api/activity` | Índice de atividade vindo da visão computacional |
| GET | `/api/history?pet_id=` | Últimas leituras do pet |
| GET | `/api/pets` · `/api/pets/:id` · `/api/pets/:id/baseline` · `/api/pets/lookup?name=` | Cadastro, prontuário e baseline individual |
| GET | `/api/triage` | Fila de triagem — último insight por pet, ordenado por risco |
| GET | `/api/insights/latest?pet_id=` · `/api/insights/:id` | Insight completo |
| POST | `/api/analyze/:pet_id` | Roda o Copilot sob demanda (`{"llm_mode": "offline"}` opcional) |
| POST | `/api/insights/:id/approve` | Veterinário aprova → mensagem liberada + evento IoB |
| POST | `/api/tutor-events` | Simula reação do tutor (IoB) |
| GET | `/api/model/metrics` · POST `/api/model/train` | Métricas / retreino do modelo |
| GET | `/api/health` | Estado do sistema (DB, modelo, LLM, RAG) |
| GET | `/stream` | SSE: `reading`, `activity`, `insight`, `status` |

## Decisões de arquitetura

- **SQLite, não Postgres.** O entregável precisa rodar a partir do .zip sem infraestrutura. WAL habilitado para leitura concorrente com o Flask *threaded*.
- **HTTP + SSE, não MQTT.** Mantém o protocolo já validado no Sprint 2; a arquitetura de ingestão não muda, só ganha persistência.
- **O Copilot roda no servidor, não no dispositivo.** O ESP32 continua "burro" (coleta e alerta absoluto); toda a inteligência é centralizada onde há histórico e prontuário.
- **LLM por último e opcional.** A decisão (risco, ações, serviços) existe e é persistida mesmo sem LLM. O LLM só muda a *forma* da comunicação.
- **Human-in-the-loop obrigatório.** Nenhuma mensagem com conteúdo clínico é enviada ao tutor sem aprovação do veterinário (`approved=1`).

## Integrações futuras (roadmap — resposta ao feedback do Sprint 2)

| Integração | O que muda | Onde encaixa |
|---|---|---|
| WhatsApp Business API | `approve` passa a disparar a mensagem real; webhooks alimentam `tutor_events` | `dashboard_server.py` → serviço de mensageria |
| Agenda da clínica (Google Calendar / sistema próprio) | CTA "agendar" vira link com slot real; `appointment_booked` automático | `recommender` + `approve` |
| Prontuário / ERP veterinário | `vaccines`, `consultations`, `medications` sincronizados em vez de seed | `ai_core/db.py` (camada de sync) |
| Farmácia / pet shop | Ação de adesão gera reposição automática do medicamento | `services.yaml` + novo endpoint |
| Planos de saúde pet | Score de risco preventivo como insumo de elegibilidade/precificação | `insights` (export) |
| Telemedicina | Teleconsulta recomendada abre sala de vídeo em 1 clique | `services.yaml` → link |
| Hardware real | ESP32 físico com MPU6050; MQTT quando houver múltiplos dispositivos | `wokwi/` → firmware |
