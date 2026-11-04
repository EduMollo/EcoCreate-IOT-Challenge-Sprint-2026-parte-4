# CLYVO VET — CLYVO Copilot, Sprint 4

**Aplicação:** https://clyvovet.vercel.app
**Fontes:** [**Github**](https://github.com/EduMollo/EcoCreate-IOT-Challenge-Sprint-2026-parte-4)
[**Video**](https://youtu.be/4kTnQgR9ZAs)

## Componentes

| Camada | Responsabilidade |
|---|---|
| Java/Spring + banco da aplicação | Login, posse do pet, histórico, simulação, persistência de contexto/resultado, aprovação e portal do tutor |
| Python/Flask (`app.py`) | API interna stateless, sem usar o seed SQLite no fluxo integrado |
| Features + modelos | Baseline individual, desvios, tendências, RandomForest e IsolationForest |
| Regras | Prioridade operacional independente do score estatístico |
| RAG TF-IDF | Recuperação de trechos da base versionada `knowledge/` |
| Redação | Gemini ou Ollama; Claude preservado como opção configurável |
| Contingência | Template explicitamente identificado, sem alegar geração por LLM |

Os arquivos novos e alterados da integração Java estão em [`integracao-java/`](integracao-java/LEIA-ME.md), para aplicação no projeto Java existente. Essa pasta não é um projeto independente.

## Executar

Recomendado: Python 3.12 e Java 17 ou superior. Em PowerShell, execute `./iniciar.ps1`. O script cria o ambiente, instala dependências, retreina, roda os testes e inicia a API em `http://127.0.0.1:5001`.

Alternativa manual:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m ai_core.risk_model train
.venv/Scripts/python -m unittest discover -s tests -v
Copy-Item .env.example .env
# Configure COPILOT_API_TOKEN em .env com um valor privado forte.
.venv/Scripts/python app.py
```

Em **Pet → CLYVO Copilot**, a equipe simula uma janela, solicita análise, revisa o resultado e aprova a mensagem. O tutor acessa o próprio pet e confirma a leitura da mensagem aprovada. Nenhum WhatsApp externo é enviado. A aprovação registra disponibilização no portal como evento `message_sent`.

## API e publicação

- `GET /health`: saúde do serviço sem expor segredos.
- `POST /v1/analyze`: contexto JSON, header `Authorization: Bearer <COPILOT_API_TOKEN>`.
- Sem token configurado: 503. Token inválido: 401. Entrada inválida: 400. Falha no processamento: 503.
- Esquema e configuração: `docs/INTEGRACAO-SPRINT4.md`.
- Publicação proposta: segundo projeto Flask na Vercel, treino durante o build e token compartilhado apenas nos backends. Configuração fornecida em `vercel.json`; publicação ainda não validada.

## Equipe

| Integrante | RM |
|---|---|
| Carlos Alberto Guedes Neto | 566022 |
| Eduardo Novaes Mollo | 561515 |
| Vinicius Luis Exposito Morassi | 563340 |
| Luan Peixoto Marins Rocha | 562258 |
| Mathaus Victor Souza Marcelino | 564146 |

Desenvolvimento com assistência de IA; a equipe deve revisar, testar e compreender o código.
