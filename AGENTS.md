# AGENTS.md

Guia para agentes de IA (Codex) trabalhando neste repositório. Leia antes de escrever qualquer código.

## O que é o Opero

Uma equipe de agentes de IA transforma uma conversa B2B do WhatsApp em um pedido validado, confirmado, aprovado por humano e criado no ERP — sem redigitação e sem inventar dados. Projeto de hackathon; a regra de ouro é: **não construa nada novo até a jornada feliz rodar 3× seguidas.** Prefira sempre a alternativa mais simples que mantém a jornada ponta a ponta.

Documentação de referência: `docs/REQUISITOS_FUNCIONAIS.md` (RFs, máquina de estados, schemas) e `docs/PLANO_IMPLEMENTACAO.md` (tasks, branches, ordem). Em caso de dúvida sobre comportamento esperado, esses arquivos vencem.

## Stack

- Frontend: React + Vite + Tailwind (`frontend/`)
- Backend: Django + Django REST Framework (`backend/`)
- Banco: PostgreSQL
- Infra: Docker Compose
- Agentes: Python dentro do backend, em `backend/apps/agents/`
- Voz (enhancement): ElevenLabs STT + TTS, isolado em `backend/apps/core/voice.py`

## Estrutura

```text
backend/apps/core/            clientes, pedidos, conversas, logs, voice.py
backend/apps/erp_simulator/   "sistema externo": catálogo, preço, estoque, orders
backend/apps/agents/          orchestrator.py, tools.py, context.py, schemas.py, os 4 agentes
frontend/src/                 console de 3 colunas
scripts/seed.py               dataset congelado
```

## Arquitetura em uma frase

Um **supervisor determinístico (sem LLM)** coordena quatro agentes por uma máquina de estados. Cada agente é uma função `run(order_context: OrderContext) -> AgentResult`. Os agentes usam **tools determinísticas** e só acessam o ERP simulado **via HTTP** (API key + `Idempotency-Key`). Dados comerciais vêm do ERP; o modelo interpreta, não inventa.

Ordem: `Order Intake → Memory → Validation → (esclarecimento) → confirmação do cliente → aprovação do operador → ERP Execution`.

## Regras invioláveis (guardrails)

Estas não são preferências. Violá-las quebra a tese do produto:

1. **Nenhum dado comercial inventado.** SKU, preço, estoque e cliente vêm sempre do ERP/catálogo. O agente só pode escolher SKUs que a tool de catálogo retornou. Sem candidato confiável → esclarecimento ou revisão humana.
2. **Total é determinístico.** `calculate_total` é uma função pura em Python, nunca cálculo em texto livre do modelo.
3. **Aprovação humana antes de qualquer escrita no ERP.** Nada vai para `POST /api/erp/orders` sem confirmação do cliente **e** aprovação do operador, na mesma versão.
4. **Idempotência sempre.** Toda criação no ERP usa `Idempotency-Key`. Em timeout, consulte pela chave antes de repetir. Nunca duplique pedido.
5. **Memória não substitui o ERP.** Memória é contexto histórico; um alias observado entra como `MemoryProposal` (`pending_review`), nunca vira alias confiável automaticamente.
6. **Ambiguidade nunca é resolvida em silêncio.** Bloqueie o item e pergunte.
7. **Falha nunca vira sucesso por inferência.** Erros aparecem na interface e nos logs; não os esconda.
8. **Segredos só no backend.** Chaves de modelo e da ElevenLabs nunca no frontend.

## O contrato Back ↔ AI

A fronteira mais sensível do projeto. Antes de mexer nos agentes, respeite:

- `OrderContext` (`agents/context.py`): estado do pedido em construção.
- `AgentResult` e schemas (`agents/schemas.py`): saída tipada de cada agente. Congelados — mudanças exigem alinhar backend e AI juntos.
- Tools (`agents/tools.py`, entregues pelo backend): `search_catalog`, `get_price`, `check_inventory`, `calculate_total`, `get_customer_memory`, `create_memory_proposal`, `create_erp_order`. Cada chamada registra um `ToolCall`.
- O orquestrador (`agents/orchestrator.py`) é quem altera o estado principal e chama o agente autorizado. Agentes não conversam livremente entre si.

## Máquina de estados

```text
received → parsing → memory_loaded → validating
   ├── waiting_customer → validating          (esclarecimento)
   └── ready_for_confirmation → customer_confirmed → pending_approval
          → sending_to_erp → sent_to_erp | erp_execution_failed
```

## Comandos

```bash
docker-compose up --build                                  # sobe db + backend + frontend
docker-compose exec backend python manage.py migrate       # migrations
docker-compose exec backend python manage.py seed_demo      # dataset congelado (rodar após subir)
docker-compose exec backend python manage.py test           # testes
docker-compose exec backend python manage.py shell          # testar tools/agentes isolados
```

Serviços: frontend em `:5173`, API em `:8000/api`, ERP em `:8000/api/erp`.

Resetar o cenário: botão `Reset demo` na UI ou `POST /api/demo/reset`.

## Convenções de código

- Backend: siga o layout de apps do Django; lógica de negócio em serviços, não em views. DRF serializers para I/O.
- Agentes: temperatura baixa, saída sempre validada contra schema; falha controlada, nunca silenciosa.
- Frontend: componentes funcionais + hooks; client de API centralizado; estados vazio/loading/erro em toda tela.
- Não introduza microserviços, filas externas ou EDA distribuída — está fora de escopo por decisão explícita.

## Branches

`main ← dev ← feature branches`. Feature branches saem de `dev` no formato `<dono>/<área>-<slug>` (ex.: `enzo/erp-simulator`, `gui/agent-intake`, `pedro/ui-chat`). Merges pequenos e frequentes em `dev`. Nos últimos 20 min antes da demo, congele `dev` e promova para `main`.

## Voz (enhancement)

Áudio é apenas mais um canal de entrada: transcreva com a ElevenLabs e alimente **o mesmo pipeline** de texto — não crie um fluxo paralelo. Voz não pode bloquear o core: o texto correspondente sempre existe, e falha da ElevenLabs cai para entrada por texto. Só trabalhe nisso depois que a jornada por texto rodar 3× seguidas. A API da ElevenLabs muda com frequência — confirme endpoints e formatos na doc oficial antes de implementar.

## Ao fazer mudanças

- Rode migrations e `seed_demo` após alterar models.
- Se tocar em schema de agente, atualize `agents/schemas.py`, os agentes afetados e o consumo no frontend juntos.
- Confirme que a jornada feliz continua rodando ponta a ponta antes de commitar.
- Não quebre o `Reset demo` — ele é o que garante a apresentação.
