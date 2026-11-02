# Validação da implementação — 01/11/2026

## Resultados efetivamente obtidos

| Verificação | Resultado | Alcance |
|---|---|---|
| Maven `verify`, Java Sprint 4 | Sucesso; 48 testes identificados, 44 executados, zero falhas/erros, quatro opcionais ignorados | Compilação, JAR, testes existentes e novo fluxo MVC com contrato de IA controlado |
| `CopilotIntegracaoTest` | Sucesso | Simulação, contexto, persistência, tela, aprovação, tutor, autorização por posse, CSRF e falha de transporte preservando histórico |
| Python `test_core.py` | Oito testes aprovados | Baseline separado da janela recente, cold start, valores inválidos/NaN, timestamps, duplicatas, espécie, guardrail e eventos IoB |
| Python `test_pipeline.py` | Cinco testes ignorados por dependências ausentes | Não comprova inferência, Flask ou RAG executados nesta sessão |
| Python `compileall` | Sucesso | Sintaxe dos arquivos Python |
| `git diff --check` Java | Sucesso | Sem erros de whitespace nas alterações rastreadas |

O teste de transporte controlado não faz chamada à API Python. O teste de geração controlada incluído na suíte Python verifica o contrato quando executado, sem comprovar geração por um modelo real.

## Bloqueios encontrados

- O Python instalado no sistema não continha Flask/scikit-learn e outras dependências.
- O ambiente negou resolução de rede para PyPI; não foi possível instalar essas bibliotecas. Uma tentativa inicial do wrapper Maven também tentou baixar arquivos, mas o Maven e as dependências Java foram encontrados em cache e o build foi concluído offline.
- Conexões locais foram negadas no ambiente; os testes MVC executam sem abrir porta. Não foi realizada uma nova validação visual em navegador.
- Não há chave de provedor generativo, servidor Ollama ou modelo local configurado.
- Uma tentativa de upload sem payload/destino identificado foi rejeitada pela revisão automática. Nenhum arquivo foi enviado nessa tentativa; não houve publicação desta implementação.

## Ainda obrigatório antes da entrega

1. Instalar `requirements.txt`, retreinar o modelo e executar toda a suíte Python sem os cinco skips.
2. Confirmar resultados do holdout e guardar as novas métricas com hash do dataset e versão do ambiente.
3. Configurar um provedor real e guardar evidência de resposta, modo e fontes, sem expor chave.
4. Publicar o serviço e as alterações Java; validar a migração PostgreSQL e o fluxo completo no site.
5. Validar tela em navegador, inclusive celular e tema claro/escuro.
6. Preencher o repositório e vídeo não listado em `ENTREGA.md` e conferir o ZIP final.

As métricas herdadas da Sprint 3 não foram recalculadas aqui e não devem ser anunciadas como resultado novo. Os testes externos Oracle/PostgreSQL ignorados não comprovam execução nesses bancos.
