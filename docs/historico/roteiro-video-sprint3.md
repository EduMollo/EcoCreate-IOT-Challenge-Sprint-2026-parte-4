# Roteiro do vídeo pitch — 5 minutos

**Formato:** gravação de tela (dashboard + terminais) com narração. Câmera opcional no início e no fim.
**Publicar no YouTube em modo não listado.** Link vai no README e no PDF de entrega.

## Preparação (antes de gravar)

```bash
# Terminal 1 — servidor (gera dados + treina o modelo na primeira execução)
python dashboard_server.py

# Terminal 2 — deixe PRONTO, mas só rode no bloco 4
python iot_sensor_simulation.py --pet Thor --scenario fever --drift-after 10 --ramp 25 --interval 1

# Terminal 3 (opcional) — visão computacional como sensor de atividade
python pet_detection.py
```

- Abra `http://localhost:5000` e selecione **Thor** na fila de triagem (já vem selecionado).
- Se tiver `ANTHROPIC_API_KEY` no `.env`, o badge no topo mostra "Claude"; senão, "template (offline)". Ambos funcionam — diga qual está usando.
- Tenha `docs/arquitetura.md` aberto no GitHub (o Mermaid renderiza) ou o PNG.

## Cronograma

| Tempo | Bloco | Na tela | Fala-chave |
|---|---|---|---|
| **0:00–0:30** | O problema | Slide/título ou câmera | "Cuidado de pet é reativo: o tutor só age quando o animal já está doente. Vacina atrasa, remédio é esquecido, mudança de comportamento passa despercebida por semanas." |
| **0:30–1:00** | Recap Sprint 2 + limite | Código `_check_alerts` do Sprint 2 (faixa fixa) | "No Sprint 2 provamos que a telemetria existe. Mas o único critério de decisão era uma faixa fixa da espécie. **Sprint 2 detecta. Sprint 3 decide.**" |
| **1:00–2:00** | A IA: 5 camadas | `docs/decisao-de-ia.md` (tabela de abordagens) → diagrama | "Não é um chatbot. Baseline individual → modelo preditivo (IsolationForest + RandomForest) → regras clínicas → recomendação → e só então o LLM redige. **Decisão é determinística e auditável; expressão é generativa.** Por isso não usamos só LLM." |
| **2:00–3:15** | **Demo** | Dashboard com Thor | (1) Mostre baseline individual nos cards ("38,3 ± 0,1 — o normal *dele*"). (2) Rode o simulador com `--scenario fever`. (3) Após ~10 leituras o Copilot dispara: score sobe, fatores explicam "+3σ temperatura", ação "Avaliação veterinária — desvio do baseline", serviço "Consulta clínica". (4) Mostre a mensagem ao tutor no balão de WhatsApp e o briefing técnico. (5) Clique **Aprovar e enviar** — human-in-the-loop. (6) Clique "tutor abriu / agendou" — IoB realimenta o perfil. |
| **3:15–4:15** | Dados, fluxo e arquitetura | `docs/arquitetura.md` (flowchart + sequência) e `docs/modelo-de-dados.md` | "Oito tabelas em SQLite. Telemetria vem do ESP32 e da visão computacional — o deslocamento do bounding box virou índice de atividade. Eventos do tutor alimentam a camada IoB. Cada decisão é persistida em `insights` para auditoria." |
| **4:15–4:45** | Avaliação + guardrails | `notebooks/avaliacao_modelo.ipynb` (matriz de confusão, importâncias) + `docs/lgpd-e-guardrails.md` | "RandomForest AUC ~0,90 em dados sintéticos com seed fixa — declaramos isso abertamente. Guardrails bloqueiam diagnóstico e posologia; o veterinário aprova antes de enviar." |
| **4:45–5:00** | Benefícios + roadmap | Tabela de integrações em `docs/arquitetura.md` | "Tutor: sabe o que fazer. Clínica: fila priorizada e agenda cheia. Pet: detecção precoce. Próximos passos, em resposta ao feedback do Sprint 2: WhatsApp Business, agenda, prontuário/ERP, farmácia, planos e telemedicina." |

## Dicas

- Fale o nome de cada camada quando ela aparecer na tela (o avaliador marca "aplicação técnica de conceitos de IA" — 60 pontos).
- Mostre a fila de triagem com **Mel** (Crítico) e **Luna** (retorno atrasado) para provar que o sistema prioriza entre pets, não só analisa um.
- Se o LLM estiver em modo template, diga: "o texto abaixo vem do fallback determinístico; com a chave da API, o Claude redige a partir do mesmo contexto — a decisão é idêntica".
- Encerre com o link do repositório na tela.
