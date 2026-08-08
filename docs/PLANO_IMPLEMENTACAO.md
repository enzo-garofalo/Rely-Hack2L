# Plano de Implementação — Opero

> **Contexto:** hackathon de AI Agents. Jornada única P0 (WhatsApp → agentes → validação → confirmação → aprovação humana → ERP), sem redigitação e sem inventar dados.
>
> **Time:** Pedro (frontend + pitch) · Enzo (backend + infra) · Gui (AI agents).
>
> **Stack:** React (Vite) → Django + DRF → PostgreSQL, tudo em Docker Compose. Voz via ElevenLabs (enhancement).
>
> **Regra de ouro:** ninguém constrói nada novo até a jornada feliz rodar 3 vezes seguidas.

---

## 0. Convenções

### 0.1 Estrutura do repositório (monorepo)

```text
opero/
├── docker-compose.yml
├── .env.example
├── backend/                  # Django + DRF (Enzo é dono da estrutura)
│   ├── Dockerfile
│   ├── manage.py
│   ├── requirements.txt
│   ├── config/               # settings, urls, wsgi
│   └── apps/
│       ├── core/             # organizações, clientes, pedidos, conversas, logs
│       ├── erp_simulator/    # "sistema externo": catálogo, preço, estoque, orders
│       └── agents/           # orquestrador + agentes (Gui é dono do conteúdo)
├── frontend/                 # React + Vite (Pedro)
│   ├── Dockerfile
│   ├── package.json
│   └── src/
├── docs/
│   ├── PLANO_IMPLEMENTACAO.md
│   └── REQUISITOS_FUNCIONAIS.md
└── scripts/
    └── seed.py               # dataset congelado
```

Decisão importante: `agents/` e `erp_simulator/` vivem no mesmo projeto Django, mas o `erp_simulator` é tratado como serviço externo — os agentes só falam com ele **via HTTP** (`requests`), com API key e `Idempotency-Key`. Isso mantém a história "a integração é real por API" verdadeira, sem microserviços.

### 0.2 Estratégia de branches

```text
main            → sempre demonstrável; só recebe merge de dev
 └── dev        → branch de integração; feature branches saem e voltam aqui
      ├── enzo/*
      ├── gui/*
      └── pedro/*
```

- Feature branches saem de `dev` e voltam para `dev` via PR curto (ou merge direto se o time preferir velocidade).
- Nome: `<dono>/<área>-<slug>`, ex.: `enzo/infra-bootstrap`, `gui/agent-intake`, `pedro/ui-console`.
- Regra de conflito: divergência de mais de 5 min → vence a alternativa mais simples que mantém a jornada ponta a ponta.
- Nos últimos 20 min, `dev` congela e vira `main`. Ninguém commita depois disso.

### 0.3 O contrato compartilhado (a fronteira entre Back e AI)

Este é o ponto onde Enzo e Gui precisam concordar **antes** de codar. É o que evita retrabalho.

O backend expõe para os agentes um **objeto `OrderContext`** e um conjunto de **tools determinísticas**. Cada agente é uma função Python com assinatura fixa:

```python
def run(order_context: OrderContext) -> AgentResult:
    ...
```

- `OrderContext`: dados do pedido em construção (mensagens, cliente, itens, estado, versão).
- Tools (funções Python que o Enzo entrega prontas, algumas chamando o ERP via HTTP): `search_catalog`, `get_price`, `check_inventory`, `calculate_total`, `get_customer_memory`, `create_memory_proposal`, `create_erp_order`.
- `AgentResult`: saída tipada (schema) que o orquestrador persiste e usa para decidir o próximo estado.

Enzo entrega o esqueleto do orquestrador + tools; Gui preenche a lógica de cada agente. Os **schemas** (seção de RF) são a linguagem comum.

---

## 1. Visão de dependências — quem destrava quem

```text
Enzo: infra + models + ERP simulator + tools + OrderContext
        │
        ├──────────────► Gui: agentes (precisam das tools e schemas)
        │
        └──────────────► Pedro: UI (precisa dos endpoints do Order API)

Gui: agentes prontos ──► Enzo pluga no orquestrador ──► Pedro consome timeline
```

Regra prática: **Enzo tem que sair na frente** com contratos, fixtures e ERP. Enquanto isso, Pedro trabalha com dados mockados e Gui trabalha os prompts/schemas isolados. O ponto de sincronização crítico é quando as tools ficam prontas (Gate 2).

---

## 2. Fase 0 — Fundação conjunta (primeiros ~20 min, todos juntos)

**Branch:** `dev` (commit inicial coletivo)

1. Ler os dois documentos de `docs/`.
2. Confirmar o cenário exato da demo (a mensagem "10 cx de coca 2L, 6 fardos da zero, 15 do óleo…").
3. Congelar os schemas de `AgentResult` (ver Requisitos Funcionais).
4. Criar repositório, `dev`, `.env.example`, e o esqueleto de pastas.
5. Cada um confirma que consegue contar a história da demo em 30 segundos.

**Gate 0:** repo criado, pastas no lugar, todos sabem o cenário e os schemas estão escritos.

---

## 3. Tasks — Enzo (Backend + Infra)

### E1 · Bootstrap de infra e Docker
- **Branch:** `enzo/infra-bootstrap`
- **Objetivo:** subir `docker-compose up` e ter Postgres + Django respondendo.
- **Fazer:** `docker-compose.yml` com serviços `db` (postgres:16), `backend` (Django), `frontend` (node/vite). `Dockerfile` do backend. `requirements.txt` (django, djangorestframework, psycopg2-binary, requests, django-cors-headers, python-dotenv). Projeto Django `config` + apps vazios (`core`, `erp_simulator`, `agents`). CORS liberado para o front.
- **DoD:** `GET /api/health/` retorna 200 dentro do container; front consegue chamar o back.
- **Depende de:** Gate 0.

### E2 · Modelagem e migrations
- **Branch:** `enzo/db-models`
- **Objetivo:** modelo de dados mínimo e real.
- **Fazer:** models em `core` (Organization, Customer, Conversation, Message, Order, OrderVersion, OrderItem, CustomerConfirmation, OperatorApproval, MemoryEntry, MemoryProposal, AgentRun, ToolCall) e em `erp_simulator` (ErpProduct, ErpPrice, ErpInventory, ErpAlias, ErpOrder, ErpIdempotencyKey). Migrations aplicadas.
- **DoD:** `python manage.py migrate` limpo; admin do Django mostra as tabelas.
- **Depende de:** E1.

### E3 · Dataset congelado (seed)
- **Branch:** `enzo/fixtures-seed`
- **Objetivo:** dados idênticos a cada reset.
- **Fazer:** `scripts/seed.py` com 1 distribuidor, 1 cliente (Mercado Boa Compra), 6 produtos (incluindo `COCA-2L-CX6`, `COCA-ZERO-LATA-CX12`, `OLEO-SOJA-900ML-CX20`), preços por cliente, estoque, 3 aliases de memória aprovados. Comando `manage.py seed_demo`.
- **DoD:** rodar o comando popula o banco; rodar de novo limpa e repopula igual.
- **Depende de:** E2.

### E4 · ERP Simulator (API "externa")
- **Branch:** `enzo/erp-simulator`
- **Objetivo:** provar leitura e escrita por API com idempotência.
- **Fazer:** 3 endpoints — `GET /api/erp/context/{customerId}` (cliente + catálogo + preços + estoque), `POST /api/erp/orders` (cria pedido, exige header `Idempotency-Key`, persiste, devolve número externo), `GET /api/erp/orders/{id}`. Autenticação por API key simples. Idempotência: se a chave já existe, devolve o pedido existente sem criar de novo.
- **DoD:** criar o mesmo pedido 2× com a mesma chave gera 1 registro; segunda chamada devolve o mesmo número.
- **Depende de:** E3.

### E5 · Tools determinísticas + OrderContext
- **Branch:** `enzo/agent-tools`
- **Objetivo:** entregar a "caixa de ferramentas" que Gui vai usar.
- **Fazer:** módulo `agents/tools.py` com `search_catalog`, `get_price`, `check_inventory`, `calculate_total` (função pura, sem LLM), `get_customer_memory`, `create_memory_proposal`, `create_erp_order` (chama o ERP via HTTP com a chave). `agents/context.py` com a dataclass `OrderContext`. Cada tool registra um `ToolCall` no banco.
- **DoD:** dá para chamar cada tool via shell do Django e ver o `ToolCall` gravado; `calculate_total` nunca depende de texto do modelo.
- **Depende de:** E4. **Destrava:** Gui (Gate 2).

### E6 · Orquestrador + máquina de estados
- **Branch:** `enzo/orchestrator-statemachine`
- **Objetivo:** sequência determinística que chama os agentes.
- **Fazer:** `agents/orchestrator.py` com a máquina de estados (`received → parsing → memory_loaded → validating → waiting_customer → ready_for_confirmation → customer_confirmed → pending_approval → sending_to_erp → sent_to_erp`). O orquestrador recebe um evento, chama o agente autorizado (função `run` de Gui), persiste `AgentRun` e a transição. Sem LLM aqui.
- **DoD:** com agentes "stub" (mock), um pedido percorre todos os estados; cada transição registra agente + motivo + versão.
- **Depende de:** E5. **Integra com:** Gui (agentes reais).

### E7 · Order API (para o frontend)
- **Branch:** `enzo/order-api`
- **Objetivo:** endpoints que o console consome.
- **Fazer:** `POST /api/orders/ingest` (recebe a mensagem, cria conversa+pedido, dispara o pipeline), `GET /api/orders/{id}` (estado completo: itens, evidência, confiança, validações, esclarecimento pendente, resumo), `POST /api/orders/{id}/customer-reply`, `POST /api/orders/{id}/confirm`, `POST /api/orders/{id}/approve` (dispara execução no ERP), `GET /api/orders/{id}/timeline`, `POST /api/demo/reset`.
- **DoD:** com Postman/curl dá para percorrer a jornada inteira sem UI.
- **Depende de:** E6. **Destrava:** Pedro (integração real).

### E8 · Auditoria e reset reprodutível
- **Branch:** `enzo/audit-reset`
- **Objetivo:** logs limpos e reset confiável para a demo.
- **Fazer:** endpoint de timeline consolidando `AgentRun` + `ToolCall` + transições ordenados; `POST /api/demo/reset` que trunca dados voláteis e roda `seed_demo`. Sanitização básica do que aparece nos logs.
- **DoD:** reset devolve o sistema ao estado inicial idêntico; timeline mostra a colaboração dos agentes ponta a ponta.
- **Depende de:** E7.

### E9 · Voz — integração ElevenLabs (STT + TTS) · **enhancement**
- **Branch:** `enzo/voice-elevenlabs`
- **Objetivo:** permitir pedido por áudio e resposta por voz, reaproveitando o pipeline existente.
- **Fazer:** serviço `core/voice.py` com `transcribe(audio) -> texto` (ElevenLabs Scribe / STT) e `synthesize(texto) -> audio` (ElevenLabs TTS). Endpoint `POST /api/orders/ingest-audio` (multipart) que transcreve e chama internamente o mesmo fluxo do `ingest`. Armazenar o áudio original + transcrição como evidência ligada ao pedido. Campo/rota para devolver o áudio da resposta (esclarecimento/resumo). API key só no backend. Tratamento de erro/timeout que não trava o fluxo. Áudio de fallback pré-gravado.
- **DoD:** enviar um áudio cria o pedido igual ao texto; transcrição fica visível e auditável; resposta pode voltar em áudio; falha da ElevenLabs cai para texto sem quebrar.
- **Depende de:** E7 (o pipeline de texto tem que existir antes). **Começar após o Gate 4.**

---

## 4. Tasks — Gui (AI Agents)

### G1 · Núcleo de agentes (LLM client + structured output)
- **Branch:** `gui/agent-core`
- **Objetivo:** base para todos os agentes.
- **Fazer:** wrapper de chamada ao modelo com saída estruturada (JSON validado), temperatura baixa, timeout e retry curto. Helper para tool calling. `agents/schemas.py` com os schemas de saída (OrderDraft, MemoryContext/MemoryProposal, ValidatedOrder/ClarificationRequest, ErpReceipt). Pode começar em paralelo à infra, com tools mockadas.
- **DoD:** uma chamada de teste devolve JSON válido conforme schema, ou falha de forma controlada.
- **Depende de:** Gate 0 (schemas congelados).

### G2 · Order Intake Agent
- **Branch:** `gui/agent-intake`
- **Objetivo:** transformar a conversa em itens estruturados.
- **Fazer:** função `run` que recebe as mensagens e devolve `OrderDraft` (items, deliveryDate, missingFields, evidence). Preserva o trecho original de cada item. Marca confiança.
- **DoD:** a mensagem da demo vira 3 itens com evidência; "óleo da última vez" fica marcado como precisando de memória.
- **Depende de:** G1. **Usa:** tools de E5 (quando prontas).

### G3 · Operational Memory Agent
- **Branch:** `gui/agent-memory`
- **Objetivo:** recuperar aliases/histórico e propor aprendizado.
- **Fazer:** `run` que consulta `get_customer_memory`, resolve "óleo da última vez" → `OLEO-SOJA-900ML-CX20`, e depois da correção cria `MemoryProposal` para "fardo da zero" → `COCA-ZERO-LATA-CX12` (status `pending_review`, com evidência). **Guardrail:** memória não substitui catálogo/preço/estoque.
- **DoD:** memória resolve o óleo; proposta é gerada e auditável; nada vira alias confiável automaticamente.
- **Depende de:** G1, E5.

### G4 · Validation Agent
- **Branch:** `gui/agent-validation`
- **Objetivo:** validar contra o ERP e decidir avanço.
- **Fazer:** `run` que usa `search_catalog`, `get_price`, `check_inventory`, `calculate_total`. Só aceita SKU retornado pelo catálogo. Bloqueia "fardos da zero" e emite `ClarificationRequest`. Recalcula após cada resposta. **Guardrail:** nunca inventa produto/preço/estoque/total.
- **DoD:** ambiguidade gera pergunta; total sempre vem da função determinística.
- **Depende de:** G1, E5.

### G5 · ERP Execution Agent
- **Branch:** `gui/agent-execution`
- **Objetivo:** criar o pedido aprovado no ERP.
- **Fazer:** `run` que checa pré-condições (confirmado + aprovado + sem pendência), monta o payload, chama `create_erp_order` com `Idempotency-Key`, trata timeout consultando pela chave antes de repetir, salva o número externo.
- **DoD:** pedido criado uma única vez; em timeout simulado, não duplica.
- **Depende de:** G1, E5.

### G6 · Orquestração fim-a-fim + ajuste
- **Branch:** `gui/agent-orchestration`
- **Objetivo:** plugar os 4 agentes no orquestrador do Enzo e afinar.
- **Fazer:** conectar cada `run` ao estado correto, garantir logging de raciocínio resumido, ajustar prompts com o dataset congelado, preparar **fallback** (resposta pré-gravada) caso o modelo falhe na hora.
- **DoD:** a jornada da demo roda 3× seguidas sem intervenção; existe fallback pronto.
- **Depende de:** G2–G5, E6.

### G7 · Robustez do intake para voz · **enhancement**
- **Branch:** `gui/voice-intake-robustness`
- **Objetivo:** garantir que texto transcrito (mais bagunçado que texto digitado) ainda produza um `OrderDraft` bom.
- **Fazer:** ajustar o prompt do Order Intake para lidar com marcas de fala (hesitação, repetição, números por extenso), tratar baixa confiança da transcrição e sugerir esclarecimento quando o texto vier ambíguo. Não é um agente novo — é afinação do G2 para a entrada de voz.
- **DoD:** o áudio de demo transcrito gera os mesmos 3 itens que a versão em texto.
- **Depende de:** G2, E9. **Começar após o Gate 4.**

---

## 5. Tasks — Pedro (Frontend + Pitch)

### P1 · Bootstrap do front
- **Branch:** `pedro/ui-bootstrap`
- **Objetivo:** app React rodando no Docker, falando com o back.
- **Fazer:** Vite + React + Tailwind, client de API (axios/fetch com base URL do back), proxy/CORS ok, tela em branco com "health check" visível.
- **DoD:** front no container consome `GET /api/health/`.
- **Depende de:** E1.

### P2 · Layout do console (3 colunas)
- **Branch:** `pedro/ui-console-layout`
- **Objetivo:** o shell da tela única.
- **Fazer:** layout de 3 colunas — esquerda (chat WhatsApp), centro (pedido estruturado), direita (timeline dos agentes). Estados vazio/loading/erro. Pode usar dados mockados.
- **DoD:** as 3 áreas existem e são responsivas ao conteúdo mockado.
- **Depende de:** P1.

### P3 · Coluna de chat (WhatsApp)
- **Branch:** `pedro/ui-chat`
- **Objetivo:** conversa simulada.
- **Fazer:** bolhas estilo WhatsApp, botão "enviar mensagem inicial" (dispara `POST /api/orders/ingest`), campo de resposta do cliente (`customer-reply`), render da pergunta de esclarecimento.
- **DoD:** enviar a mensagem cria o pedido; a resposta do cliente atualiza a conversa.
- **Depende de:** P2, E7 (ou mock até lá).

### P4 · Coluna do pedido (itens + validações)
- **Branch:** `pedro/ui-order-panel`
- **Objetivo:** mostrar o pedido em construção.
- **Fazer:** lista de itens (SKU, unidade, qtd, preço, estoque), badge de confiança, evidência textual, estado da validação, bloco de resumo com total, botão "confirmar" (cliente) e "aprovar" (operador).
- **DoD:** o painel reflete o `GET /api/orders/{id}` real.
- **Depende de:** P2, E7.

### P5 · Coluna da timeline dos agentes
- **Branch:** `pedro/ui-agent-timeline`
- **Objetivo:** deixar visível "por que são agentes".
- **Fazer:** cards dos 4 agentes com estado atual, tool calls chamadas (nome + entrada/saída resumida) e transições de estado, em ordem cronológica (consome `/timeline`).
- **DoD:** durante a jornada, dá para assistir os agentes trabalhando.
- **Depende de:** P2, E8.

### P6 · Ações finais + recibo do ERP + reset
- **Branch:** `pedro/ui-actions-receipt`
- **Objetivo:** fechar o ciclo visualmente.
- **Fazer:** ao aprovar, abrir drawer/modal com payload enviado, número externo, status `sent_to_erp` e a chave de idempotência. Botão `Reset demo` (chama `/api/demo/reset` e limpa a tela).
- **DoD:** aprovar cria o pedido e mostra o recibo; reset volta tudo ao início.
- **Depende de:** P4, E7, E8.

### P8 · Voz na interface (gravar, transcrever, ouvir) · **enhancement**
- **Branch:** `pedro/ui-voice`
- **Objetivo:** deixar o cliente mandar áudio e ouvir a resposta.
- **Fazer:** botão de gravar (MediaRecorder) e/ou anexar áudio na coluna do chat; envio para `POST /api/orders/ingest-audio`; exibir a transcrição retornada como uma bolha de mensagem (deixando claro que veio de voz); player para a resposta em áudio (esclarecimento/resumo). Estados de gravando/enviando/erro. Se a ElevenLabs falhar, cair para o input de texto normal.
- **DoD:** gravar um pedido em áudio percorre a mesma jornada; a transcrição aparece no chat; a resposta toca em áudio.
- **Depende de:** P3, E9. **Começar após o Gate 4.**

### P7 · Polimento + pitch + vídeo de backup
- **Branch:** `pedro/ui-polish` (código) + tarefa não-branch (pitch)
- **Objetivo:** demo convincente e apresentação pronta.
- **Fazer:** microcopy, hierarquia visual, remover botões sem função, destacar a proposta de memória gerada. Ensaiar a demo de 3–4 min, gravar vídeo de backup, preparar no máximo 3 slides.
- **DoD:** a banca entende sem explicação longa; vídeo existe; roteiro cronometrado.
- **Depende de:** todo o resto integrado.

---

## 6. Ordem de desenvolvimento consolidada (com gates)

| Bloco | Enzo | Gui | Pedro | Gate de saída |
|---|---|---|---|---|
| **Fase 0** | fundação conjunta | fundação conjunta | fundação conjunta | Gate 0: repo + schemas congelados |
| **Bloco 1** | E1 → E2 → E3 | G1 (schemas + core, mock) | P1 → P2 | **Gate 1:** back sobe no Docker; front consome health; schemas escritos |
| **Bloco 2** | E4 → E5 | G2, G3, G4, G5 (com tools reais) | P3 (com mock) | **Gate 2:** tools reais prontas; agentes rodam isolados; mensagem vira pedido no shell |
| **Bloco 3** | E6 → E7 | G6 (plugar no orquestrador) | P4, P5 | **Gate 3:** jornada ponta a ponta sem UI; UI consome dados reais |
| **Bloco 4** | E8 | ajuste de prompts + fallback | P6 | **Gate 4:** fluxo completo na tela; reset funciona |
| **Bloco 5 — voz** | E9 (ElevenLabs) | G7 (intake robusto) | P8 (voz na UI) | **Gate 5:** áudio percorre a jornada; falha da ElevenLabs cai para texto |
| **Bloco 6** | apoio à integração | eval no dataset | P7 (polish + pitch) | **Gate 6:** 3 execuções seguidas + vídeo de backup |

Ponto crítico: **Gate 2**. Se as tools do Enzo (E5) atrasarem, Gui fica bloqueado. Prioridade máxima é E1→E5 no caminho crítico. Pedro consegue avançar até P3 só com mock; Gui consegue avançar G1 e a estrutura dos agentes com tools falsas, mas precisa das reais para validar.

Sobre a voz (Bloco 5): é **enhancement**, não faz parte do caminho crítico. Só começa depois do Gate 4 — com a jornada por texto já rodando 3× seguidas. Se o tempo apertar, a voz é a primeira coisa a ser cortada, e a demo continua íntegra por texto. A regra "não construir nada até a jornada funcionar 3 vezes" continua valendo: voz vem depois disso.

---

## 7. Contratos de API (resumo rápido)

### Order API (backend → frontend)
```text
POST /api/orders/ingest            { customerId, message } → pedido completo
GET  /api/orders/{id}              → estado completo do pedido
POST /api/orders/{id}/customer-reply { message, itemRef? }
POST /api/orders/{id}/confirm      → confirmação do cliente (versão atual)
POST /api/orders/{id}/approve      → aprovação do operador → dispara ERP
GET  /api/orders/{id}/timeline     → agent runs + tool calls + estados
POST /api/demo/reset               → reseed
```

### Voz (backend → frontend / ElevenLabs) · enhancement
```text
POST /api/orders/ingest-audio      (multipart) áudio → transcreve e cria o pedido
GET  /api/orders/{id}/voice-reply  → áudio sintetizado da resposta atual
# ambos usam core/voice.py (ElevenLabs STT + TTS); key só no backend
```

### ERP Simulator API (tools → simulador, via HTTP com API key)
```text
GET  /api/erp/context/{customerId} → cliente + catálogo + preços + estoque
POST /api/erp/orders               → cria pedido (header Idempotency-Key)
GET  /api/erp/orders/{id}          → recibo do pedido
```

### Tools internas (Enzo entrega, Gui consome)
```text
search_catalog(query)              get_customer_memory(customer_id)
get_price(customer_id, sku)        create_memory_proposal(...)
check_inventory(sku, qty)          create_erp_order(payload, idempotency_key)
calculate_total(items)  # determinístico, sem LLM
```

---

## 8. Riscos de integração e mitigação

| Risco | Mitigação |
|---|---|
| Tools (E5) atrasam e travam Gui | Enzo prioriza o caminho E1→E5; Gui usa tools mock até lá com a mesma assinatura. |
| Fronteira Back↔AI mal definida | Schemas e assinatura `run(OrderContext) -> AgentResult` congelados no Gate 0. |
| Modelo varia na hora da demo | Temperatura baixa, dataset ensaiado, fallback pré-gravado (G6). |
| Front esperando back que não veio | Pedro trabalha com mock até E7; contrato de API fixo desde o Gate 1. |
| ERP duplica pedido | Idempotência no E4 + consulta antes de retry no G5. |
| Merge hell no fim | `dev` como integração contínua; merges pequenos e frequentes; congelar 20 min antes. |
| ElevenLabs falha ou demora na demo | Voz é enhancement e não bloqueia o fluxo; áudio pré-gravado + transcrição esperada como fallback; entrada por texto sempre disponível. |
| Voz consumir tempo do core | Só começa após o Gate 4; primeira da lista de corte se atrasar. |
