# CLYVO VET — IoT, IoB & IA Generativa · CLYVO Copilot
### FIAP Challenge 2026 · Disruptive Architectures: IoT, IoB & Generative IA · Sprint 3

---

## 📌 Sobre o Projeto

O **CLYVO VET** é uma plataforma digital para a jornada contínua de saúde dos pets, conectando clínicas, tutores e o ecossistema veterinário.

- **Sprints 1–2** entregaram a camada de percepção: visão computacional (OpenCV + YOLOv4-tiny), sensores IoT simulados (ESP32 + DHT22 + batimentos + LCD) e um dashboard em tempo real (Flask + SSE).
- **Sprint 3** entrega a camada de **decisão e comunicação**: o **CLYVO Copilot**, componente de IA que aprende o baseline individual de cada pet, calcula risco, decide a próxima ação por protocolo clínico, recomenda serviços e redige a comunicação para tutor e veterinário — com aprovação humana antes do envio.

> **Sprint 2 detecta. Sprint 3 decide.**
> No Sprint 2 o único critério era uma faixa fixa da espécie (`37,5–39,2 °C`). Agora a pergunta é: *"isso é normal para **este** pet?"*

---

## 🧠 O componente de IA — por que híbrido

| Camada | Técnica | Papel |
|---|---|---|
| **C1** Baseline individual | EWMA + z-score + tendência (σ) | O "normal" de cada pet, não da espécie. Cold start explícito (prior → misto → individual) |
| **C2** Modelo preditivo | **IsolationForest** + **RandomForest** (scikit-learn) | Anomalia da telemetria + `P(atenção veterinária em 7 dias)` → `risk_score` 0–100 explicável |
| **C3** Motor de regras | YAML declarativo (`protocols.yaml`) | Vacinas, vermifugação, check-up, adesão, retorno, limites absolutos. **Regra vence modelo** |
| **C4** Recomendação | Content-based (cosseno sobre tags) | Serviço da clínica compatível com risco, perfil do pet e do tutor |
| **IoB** Perfil do tutor | Eventos: abriu, respondeu, agendou, faltou, confirmou dose | Engajamento, canal, horário, tom da mensagem |
| **C5** IA Generativa | **Claude API** (`claude-opus-5`, structured output) + **RAG** TF-IDF sobre `knowledge/*.md` | Redige mensagem ao tutor (WhatsApp) e briefing ao veterinário — **só redige, não decide** |
| Guardrails | regex + regras | Bloqueia diagnóstico/posologia; exige CTA; disclaimer CFMV; fallback template |

**Princípio: decisão é determinística e auditável; expressão é generativa.** Sem chave da API, o Copilot roda em modo template — a demo nunca depende de rede (mesmo padrão do YOLO sem pesos no Sprint 2).

---

## 🏗️ Arquitetura

Diagrama completo (Mermaid, renderiza no GitHub) e fluxo de sequência: [`docs/arquitetura.md`](docs/arquitetura.md).

```
[ESP32/Wokwi]  [iot_sensor_simulation.py]  [pet_detection.py → activity_score]
       └──────────────┴──────── HTTP POST ────────────────┘
                                 ▼
                  ┌────────────────────────────────┐
                  │  dashboard_server.py (Flask)   │──── SSE ────▶ dashboard.html
                  │  /api/sensor-data /api/activity│               (telemetria + Copilot
                  │  /api/triage /api/analyze      │                + triagem + IoB)
                  │  /api/insights/:id/approve     │
                  └────────────────────────────────┘
                        │                     ▲ insight
                        ▼                     │
                  ┌───────────┐        ┌──────────────────────────┐
                  │ clyvo.db  │◀──────▶│ ai_core/ (CLYVO Copilot) │
                  │ (SQLite)  │        │ features → risk_model →  │
                  └───────────┘        │ rules → recommender →    │
                                       │ iob → llm+rag → guardrails│──▶ Claude API (opcional)
                                       └──────────────────────────┘
```

---

## 🗂️ Estrutura do Repositório

```
├── dashboard_server.py        # Flask: ingestão, persistência, gatilho do Copilot, API, SSE
├── iot_sensor_simulation.py   # Wearable simulado (DHT22, MAX30102, MPU6050) + cenários de deriva
├── pet_detection.py           # Visão computacional (YOLO) → ActivityTracker → /api/activity
├── templates/dashboard.html   # Dashboard: telemetria, painel do Copilot, fila de triagem, IoB
├── ai_core/                   # ★ CLYVO Copilot
│   ├── db.py                  #   C0 SQLite (8 tabelas)
│   ├── features.py            #   C1 baseline individual, z-scores, slopes, features clínicas
│   ├── risk_model.py          #   C2 IsolationForest + RandomForest (treino, métricas, explicação)
│   ├── rules.py + protocols.yaml      # C3 motor de regras clínicas
│   ├── recommender.py + services.yaml # C4 recomendação de serviços
│   ├── iob.py                 #   IoB — perfil comportamental do tutor
│   ├── rag.py                 #   RAG leve (TF-IDF) sobre knowledge/
│   ├── llm.py                 #   C5 Claude API + fallback template
│   ├── guardrails.py          #   validação da saída generativa
│   ├── pipeline.py            #   orquestração → insight auditável
│   └── trained/               #   modelo treinado + metrics.json
├── data/
│   ├── generate_dataset.py    # seed do banco + dataset sintético (seed fixa)
│   └── training_dataset.csv
├── knowledge/                 # base de conhecimento da clínica (RAG)
├── notebooks/avaliacao_modelo.ipynb   # matriz de confusão, ROC, importâncias
├── docs/                      # arquitetura, decisão de IA, modelo de dados, LGPD, roteiro do vídeo
├── wokwi/                     # circuito ESP32 (Sprint 2)
├── requirements.txt · .env.example
└── README.md
```

---

## 🛠️ Tecnologias

| Camada | Tecnologia | Finalidade |
|---|---|---|
| IoT | ESP32 + Wokwi · Python | Telemetria simulada (DHT22, MAX30102, MPU6050), LCD, alertas absolutos |
| Visão | OpenCV 4 + YOLOv4-tiny | Detecção cão/gato; **deslocamento do bbox → índice de atividade** |
| Backend | Flask 3 + SSE | Ingestão, API do Copilot, tempo real |
| Dados | SQLite (WAL) | Prontuário, telemetria, IoB, insights |
| ML | scikit-learn 1.9 (IsolationForest, RandomForest, LogisticRegression) · pandas · joblib | Risco preditivo, avaliação, explicabilidade |
| Regras | PyYAML | Protocolos clínicos declarativos |
| IA Generativa | Anthropic SDK (`claude-opus-5`) | Redação com structured output e cache de prompt |
| RAG | TF-IDF (scikit-learn) | Recuperação sobre `knowledge/*.md` |
| Front | HTML + Chart.js | Dashboard |

---

## 🚀 Como Executar

### 1. Instalar dependências
```bash
python -m pip install -r requirements.txt
```

### 2. (Opcional) Configurar o LLM
```bash
copy .env.example .env      # Windows  |  cp .env.example .env  # Linux/macOS
# edite .env e preencha ANTHROPIC_API_KEY. Sem chave, o Copilot usa o modo template.
```

### 3. Subir o dashboard (gera dados + treina o modelo na primeira vez)
```bash
python dashboard_server.py
# Acesse: http://localhost:5000
```
Na primeira execução: cria `clyvo.db` (12 tutores, 24 pets, 1.440 leituras, prontuário e eventos IoB), gera `data/training_dataset.csv` (2.000 episódios), treina o modelo e roda a primeira triagem.

### 4. Simular o wearable
```bash
python iot_sensor_simulation.py                                   # Thor, normal
python iot_sensor_simulation.py --scenario fever --drift-after 10 # febre gradual → Copilot detecta
python iot_sensor_simulation.py --pet Mel --scenario lethargy
```
Cenários: `normal · fever · tachycardia · hypoxia · lethargy`. O simulador **calibra no baseline individual** do pet consultando `/api/pets/:id/baseline`.

### 5. Visão computacional como sensor de atividade (opcional)
```bash
python pet_detection.py            # webcam (ou caminho de vídeo/imagem)
```
Publica `activity_score` em `/api/activity` a cada 2 s. Sem os pesos YOLO em `models/`, roda em modo simulado.

### 6. Regenerar dados / retreinar manualmente
```bash
python data/generate_dataset.py --reset
python -m ai_core.risk_model train
```

### 7. Notebook de avaliação
```bash
jupyter notebook notebooks/avaliacao_modelo.ipynb
```

---

## 🎬 Demo em 60 segundos

1. Abra o dashboard — Thor vem selecionado; os cards mostram o **baseline individual** (ex.: `38,3 ± 0,1`).
2. Rode `python iot_sensor_simulation.py --scenario fever --drift-after 10 --ramp 25 --interval 1`.
3. A cada 10 leituras o Copilot roda: o score sobe, os **fatores** explicam (`temperatura +3σ vs. baseline individual`), surge a ação *"Avaliação veterinária — desvio do baseline"* e o serviço *"Consulta clínica"*.
4. Leia a **mensagem ao tutor** (balão WhatsApp) e o **briefing ao veterinário**.
5. Clique **Aprovar e enviar** (human-in-the-loop) e depois **"tutor abriu / agendou"** (IoB realimenta o perfil).
6. Na **fila de triagem**, veja Mel (Crítico) e Luna (retorno atrasado) acima de Thor.

Roteiro completo do vídeo: [`docs/roteiro-video.md`](docs/roteiro-video.md).

---

## 🔌 API

| Método | Rota | Uso |
|---|---|---|
| POST | `/api/sensor-data` | Telemetria do wearable |
| POST | `/api/activity` | Índice de atividade (visão) |
| GET | `/api/triage` | Fila de triagem ordenada por risco |
| POST | `/api/analyze/:pet_id` | Roda o Copilot sob demanda (`{"llm_mode":"offline"}` opcional) |
| GET | `/api/insights/latest?pet_id=` | Último insight completo |
| POST | `/api/insights/:id/approve` | Veterinário aprova → mensagem liberada + evento IoB |
| POST | `/api/tutor-events` | Reação do tutor (IoB) |
| GET | `/api/pets` · `/api/pets/:id` · `/api/pets/:id/baseline` | Cadastro, prontuário, baseline |
| GET | `/api/model/metrics` · `/api/health` | Métricas do modelo · estado do sistema |
| GET | `/stream` | SSE (`reading`, `activity`, `insight`, `status`) |

---

## 📊 Resultados Parciais

**Modelo preditivo** (teste estratificado de 25 % · dados sintéticos com seed fixa · `ai_core/trained/metrics.json`):

| Modelo | Acurácia | Precisão | Recall | F1 | ROC AUC |
|---|---|---|---|---|---|
| **RandomForest** (principal) | 0,878 | 0,806 | 0,839 | 0,822 | **0,900** |
| Regressão Logística (baseline) | 0,826 | 0,719 | 0,792 | 0,753 | 0,881 |
| IsolationForest (detector, sem rótulos) | — | — | — | — | 0,847 |

Features mais importantes: `act_z` (0,30), `temp_z` (0,18), `hr_z` (0,10), `temp_slope` (0,08), `act_slope` (0,06) — queda de atividade e elevação de temperatura vs. baseline individual dominam, coerente com o modelo gerador.

![Avaliação](docs/img/avaliacao_modelo.png)
![Importância das features](docs/img/feature_importance.png)

**Triagem no seed** (24 pets): 19 Baixo · 1 Moderado · 3 Alto · 1 Crítico. Casos-vitrine: **Mel** (gata sênior, febre gradual → Crítico, contato imediato), **Luna** (retorno pós-procedimento atrasado + queda de SpO₂ → Alto), **Bob** (adesão 40 % + tutor de baixo engajamento → programa de adesão / teleconsulta), **Thor** (saudável, antirrábica atrasada 35 dias → Baixo, ação de vacinação).

Funcional:
- ✅ Baseline individual por pet (EWMA) com cold start explícito (prior → misto → individual)
- ✅ IsolationForest + RandomForest treinados, avaliados e explicáveis; heurística de fallback se não treinado
- ✅ Motor de regras com 7 regras (vacinas, vermífugo, check-up, adesão, retorno, limites absolutos, desvio do baseline)
- ✅ Recomendador content-based com justificativa e preço
- ✅ IoB: perfil do tutor a partir de eventos; botões de simulação no dashboard
- ✅ Claude API com structured output + RAG; fallback template; guardrails; disclaimer CFMV
- ✅ Human-in-the-loop (aprovação do veterinário) e insights auditáveis em SQLite
- ✅ Visão computacional → índice de atividade → feature do modelo
- ✅ Simulador com cenários de deriva calibrado no baseline individual

Limitações declaradas: dados de treino sintéticos; hardware simulado; RAG por TF-IDF. Detalhes em [`docs/decisao-de-ia.md`](docs/decisao-de-ia.md) e [`docs/lgpd-e-guardrails.md`](docs/lgpd-e-guardrails.md).

---

## 🔭 Integrações futuras (resposta ao feedback do Sprint 2)

WhatsApp Business API (envio real + webhooks → IoB) · agenda da clínica (slot real no CTA) · prontuário/ERP veterinário (sync em vez de seed) · farmácia e pet shop (reposição automática) · planos de saúde pet (score preventivo) · telemedicina (teleconsulta em 1 clique) · ESP32 físico com MPU6050 e MQTT. Tabela completa em [`docs/arquitetura.md`](docs/arquitetura.md#integrações-futuras-roadmap--resposta-ao-feedback-do-sprint-2).

---

## 🎥 Vídeo de Demonstração

> Link do YouTube (não listado): *a publicar*

## 🔗 Repositório

> Link do GitHub: https://github.com/EduMollo/Projeto-EcoCreate-IOT-Challenge-Sprint-2026-parte-3

Entrega anterior (Sprints 1–2): https://github.com/EduMollo/CS-parte-1-e-2-IOT-Grupo-FIEDMACALU

---

## 👥 Integrantes

| Nome | RM |
|---|---|
| *Carlos Alberto Guedes* | *566022* |
| *Eduardo Novaes Mollo* | *561515* |
| *Vinicius Luis Exposito* | *563340* |
| *Luan Peixoto Marins* | *562258* |
| *Mathaus Victor Souza Marcelino* | *564146* |
