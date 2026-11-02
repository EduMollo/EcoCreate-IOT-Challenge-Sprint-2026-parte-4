# Integração CLYVO Copilot — IoT Sprint 4

O botão **CLYVO Copilot** na ficha do pet abre o acompanhamento integrado. A equipe clínica pode criar janelas de sensores simulados, analisar o contexto pelo serviço Python, revisar e aprovar a mensagem. O tutor vê apenas mensagens aprovadas dos próprios pets e confirma a leitura.

## Configuração

- `COPILOT_URL`: endereço do backend Python, sem barra final (local: `http://127.0.0.1:5001`).
- `COPILOT_TOKEN`: segredo compartilhado com `COPILOT_API_TOKEN` no Python; não deve aparecer no navegador.
- Sem essas variáveis, a tela continua disponível e informa que a análise está aguardando configuração.
- Flyway V7 cria as tabelas adicionais no H2/PostgreSQL. No Oracle com instalação manual, executar o V7 adicional antes de usar a tela. A entrega Database anterior não foi reempacotada nesta alteração.

O serviço Python está na pasta irmã `CS4 IOT/Projeto-EcoCreate-IOT-Challenge-Sprint-2026-parte-4`; seguir seu README. Não é necessário duplicar o cadastro de pets no SQLite legado.

## O que foi verificado

Maven `verify`: 48 testes identificados, 44 executados com sucesso, zero falhas/erros, quatro testes externos opcionais ignorados. O novo teste MVC usa transporte de IA controlado: comprova persistência, telas Thymeleaf, aprovação, proteção CSRF, posse do pet, ocultação do briefing ao tutor, evento de leitura sem duplicidade e preservação dos resultados em indisponibilidade.

Esse teste não comprova inferência Python, chamada real ao LLM ou implantação na Vercel. As evidências Playwright e de deploy anteriores à integração continuam sendo históricas para as telas que já existiam. O novo Copilot não foi validado no navegador nesta execução, pois o ambiente bloqueou conexões locais.

## Decisões

- Prioridade das regras aparece separadamente do score do modelo.
- Dados da aplicação são convertidos para contrato explícito; email, telefone, endereço e nome completo do tutor não são enviados.
- Nenhuma confirmação de dose é inferida a partir de uma prescrição. O Python sinaliza a informação não medida.
- Apenas cães/gatos são aceitos pelo modelo atual.
- Janelas de simulação são versionadas e não misturam cenários no baseline.
- Aprovação disponibiliza a mensagem no portal. Não existe envio real de WhatsApp.
- Resultado e contexto são preservados como JSON no banco com usuário/data de aprovação.
- A transação de leitura é encerrada antes de aguardar o processamento HTTP externo.

## Pendências de publicação

Instalar dependências Python, retreinar e executar seus testes completos; selecionar/configurar geração real; criar repositório IoT; publicar a API; definir variáveis Java; validar banco publicado e fluxo completo. Até isso ocorrer, a integração é uma implementação local em validação.
