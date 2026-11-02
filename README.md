# CLYVO VET — CLYVO Copilot, Sprint 4

Continuação da Sprint 3 (nota 90). Disciplina Disruptive Architectures: IoT, IoB & Generative IA, turma 2TDSPF. Prazo: 04/11/2026.

O Copilot analisa o histórico de um pet cadastrado no ClyvoVet, calcula indicadores com RandomForest e IsolationForest, aplica regras e prepara uma comunicação para revisão veterinária. A Sprint 4 acrescenta a API de integração, dados da aplicação Java, janela de sensores simulados, rastreabilidade, publicação da mensagem no portal e confirmação de leitura pelo tutor.

## Estado desta versão

Implementação local em validação. Não declarar entrega concluída antes de validar inferência real e o fluxo publicado. Os arquivos e números da Sprint 3 preservados em `docs/historico` e `ai_core/trained` são históricos até novo treinamento. Testes ignorados não comprovam funcionamento. Ver `docs/VALIDACAO-SPRINT4.md`.

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

No projeto Java Sprint 4, configure `COPILOT_URL=http://127.0.0.1:5001` e `COPILOT_TOKEN` com o mesmo valor privado de `COPILOT_API_TOKEN`. Inicie com `./mvnw.cmd spring-boot:run`. O Flyway aplica V7 no H2/PostgreSQL. A instalação Oracle manual exige o SQL adicional V7; não é executada automaticamente quando Flyway está desabilitado.

Em **Pet → CLYVO Copilot**, a equipe simula uma janela, solicita análise, revisa o resultado e aprova a mensagem. O tutor acessa o próprio pet e confirma a leitura da mensagem aprovada. Nenhum WhatsApp externo é enviado. A aprovação registra disponibilização no portal como evento `message_sent`.

## Geração de texto

1. `CLYVO_LLM_PROVIDER=template`: sem chamadas externas; modo de contingência.
2. `gemini`: configurar `GEMINI_API_KEY` e um `GEMINI_MODEL` disponível. Há faixa gratuita em modelos elegíveis, sujeita às condições da conta e limites. Não há credencial configurada nesta versão.
3. `ollama`: instalar Ollama, baixar o modelo configurado (ex.: `ollama pull qwen2.5:3b`) e usar `CLYVO_LLM_PROVIDER=ollama`. `OLLAMA_URL` é configuração do servidor. Um Ollama no seu PC não fica acessível à Vercel por `localhost`; produção exige endpoint hospedado e protegido ou provedor remoto.
4. `claude`: instalar o SDK `anthropic`, fornecer credencial e `CLYVO_LLM_MODEL` compatível. Não há modelo Anthropic presumido ou conta ativa.

O modelo redige, mas não altera o score ou as regras. Falhas e respostas reprovadas geram template identificado. Fontes recuperadas não significam que foram utilizadas na geração: `rag_used=false` nos templates. As validações de texto são controles parciais; revisão humana continua necessária.

## API e publicação

- `GET /health`: saúde do serviço sem expor segredos.
- `POST /v1/analyze`: contexto JSON, header `Authorization: Bearer <COPILOT_API_TOKEN>`.
- Sem token configurado: 503. Token inválido: 401. Entrada inválida: 400. Falha no processamento: 503.
- Esquema e configuração: `docs/INTEGRACAO-SPRINT4.md`.
- Publicação proposta: segundo projeto Flask na Vercel, treino durante o build e token compartilhado apenas nos backends. Configuração fornecida em `vercel.json`; publicação ainda não validada.

## Dados e avaliação

O dataset de 2.000 episódios é sintético. Treino e teste usam separação estratificada de 75/25 e seed fixa, com regressão logística de comparação. O novo treinamento registra hash do CSV, versão scikit-learn e origem sintética. Isso mede aderência ao gerador, não precisão clínica real. A probabilidade em sete dias é experimental, sem calibração clínica demonstrada.

Os fatores exibidos combinam importância global das features com magnitude da alteração. Não são atribuições causais nem SHAP por instância. Adesão medicamentosa sem confirmação de doses é sinalizada como não medida; o valor padrão do modelo é uma imputação e não uma observação.

Leituras são simuladas, com unidade e timestamp UTC. Cada cenário cria uma janela independente de até 40 leituras; as últimas 10 compõem a janela recente. Não se misturam cenários na formação do baseline. Datas e valores inválidos, duplicatas e ordem incorreta são rejeitados. Telemetria com mais de 24h é desconsiderada na análise atual. O modelo atende somente cães e gatos.

## Evidências e entrega

- `docs/VALIDACAO-SPRINT4.md`: testes executados e pendências.
- `docs/roteiro-video.md`: demonstração em aproximadamente cinco minutos.
- `docs/ENTREGA.md`: links para repositório e vídeo, a preencher sem inventar URLs.
- `.github/workflows/validate.yml`: instala dependências, retreina e exige testes completos no CI.

O dashboard Flask, simulador de terminal, visão computacional e circuito Wokwi da Sprint 3 foram preservados como ferramentas legadas. O fluxo principal integrado desta sprint usa `app.py` e o Java; não confundir os dois caminhos. OpenCV é opcional em `requirements-vision.txt`.

## Equipe

| Integrante | RM |
|---|---|
| Carlos Alberto Guedes Neto | 566022 |
| Eduardo Novaes Mollo | 561515 |
| Vinicius Luis Exposito Morassi | 563340 |
| Luan Peixoto Marins Rocha | 562258 |
| Mathaus Victor Souza Marcelino | 564146 |

Desenvolvimento com assistência de IA; a equipe deve revisar, testar e compreender o código.
