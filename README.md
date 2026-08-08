# Opero

> A camada de operações de IA para distribuidores da América Latina — começando pelos pedidos que já acontecem no WhatsApp.

Uma equipe de agentes de IA transforma uma conversa B2B desestruturada em um pedido validado, confirmado, aprovado por humano e criado no ERP — sem redigitação e sem inventar dados.

---

## O problema

O fabricante vende grandes volumes para poucos distribuidores. O distribuidor transforma isso em milhares de pedidos menores para clientes B2B (mercados, restaurantes, revendedores). Cada pedido que chega em uma conversa cria trabalho invisível: interpretar, conferir, consultar preço e estoque, tirar dúvidas e redigitar tudo no ERP.

O problema não é o WhatsApp. É transformar uma conversa desestruturada em um pedido executável — sem aumentar o headcount na mesma proporção que o volume.

Exemplo de pedido real que chega:

> "Manda 10 cx de coca 2L, 6 fardos da zero e 15 daquele óleo da última vez. Entrega amanhã cedo."

---

## Como funciona

Quatro agentes coordenados por um supervisor **determinístico** (sem LLM). Dados comerciais vêm sempre do ERP, nunca do modelo. Toda escrita externa passa por confirmação do cliente e aprovação humana.

```text
Mensagem (WhatsApp)
        │
        ▼
Supervisor de orquestração  ·  estados + permissões (determinístico)
        │
        ├── Order Intake Agent      → estrutura os itens da conversa
        ├── Memory Agent            → recupera aliases e histórico
        ├── Validation Agent        → catálogo, preço e estoque (via ERP)
        └── ERP Execution Agent     → cria o pedido no ERP (idempotente)
        │
        ▼
Esclarecimento → Confirmação do cliente → Aprovação do operador → ERP
```

| Papel | Cor na UI | Natureza |
|---|---|---|
| Supervisor | neutro | Determinístico, sem LLM |
| Order Intake / Memory / Validation / Execution | roxo | Agentes LLM com tools |
| ERP Simulator | verde | System of record |
| Confirmação + aprovação | âmbar | Humano no controle |

Guardrails principais: nenhum SKU fora do catálogo, total calculado por função determinística, nenhuma escrita no ERP antes de confirmação e aprovação, e criação sempre idempotente.

---

## Stack

- **Frontend:** React + Vite + Tailwind
- **Backend:** Django + Django REST Framework
- **Banco:** PostgreSQL
- **Infra:** Docker Compose
- **Agentes:** camada Python dentro do backend, com tools determinísticas e saída em schema tipado

O ERP simulado vive no mesmo projeto Django, mas é tratado como serviço externo: os agentes só falam com ele via HTTP, com API key e `Idempotency-Key`. A integração é real por API; apenas o dataset é simulado.

---

## Como rodar

Pré-requisitos: Docker e Docker Compose.

```bash
git clone <repo> opero
cd opero
cp .env.example .env        # preencher a chave do modelo e as configs
docker-compose up --build
```

Depois de subir, popular o dataset da demo:

```bash
docker-compose exec backend python manage.py seed_demo
```

Serviços:

| Serviço | URL |
|---|---|
| Frontend (console) | http://localhost:5173 |
| Backend / API | http://localhost:8000/api |
| ERP Simulator | http://localhost:8000/api/erp |

Resetar o cenário a qualquer momento pelo botão `Reset demo` na interface ou via `POST /api/demo/reset`.

---

## Estrutura do repositório

```text
opero/
├── docker-compose.yml
├── .env.example
├── backend/                  # Django + DRF
│   └── apps/
│       ├── core/             # clientes, pedidos, conversas, logs
│       ├── erp_simulator/    # "sistema externo": catálogo, preço, estoque, orders
│       └── agents/           # orquestrador + 4 agentes + tools
├── frontend/                 # React + Vite (console de 3 colunas)
├── docs/
│   ├── PLANO_IMPLEMENTACAO.md
│   └── REQUISITOS_FUNCIONAIS.md
└── scripts/
    └── seed.py               # dataset congelado
```

---

## A interface

Uma tela única — o **Order Operations Console** — em três colunas:

- **Esquerda:** conversa estilo WhatsApp com o cliente.
- **Centro:** pedido estruturado, validações, resumo, confirmação e aprovação.
- **Direita:** timeline dos agentes, tool calls e transições de estado.

É essa transparência que responde à pergunta "por que são agentes e não um chatbot?".

---

## Endpoints principais

**Order API (frontend):**

```text
POST /api/orders/ingest                 envia a mensagem inicial
GET  /api/orders/{id}                    estado completo do pedido
POST /api/orders/{id}/customer-reply     resposta ao esclarecimento
POST /api/orders/{id}/confirm            confirmação do cliente
POST /api/orders/{id}/approve            aprovação do operador → dispara o ERP
GET  /api/orders/{id}/timeline           agent runs + tool calls + estados
POST /api/demo/reset                     reseed
```

**ERP Simulator (via API key):**

```text
GET  /api/erp/context/{customerId}       cliente + catálogo + preços + estoque
POST /api/erp/orders                     cria pedido (header Idempotency-Key)
GET  /api/erp/orders/{id}                recibo do pedido
```

---

## Time

| Pessoa | Frente |
|---|---|
| Pedro | Frontend + pitch |
| Enzo | Backend + infra |
| Gui | AI agents |

Fluxo de branches: `main ← dev ← feature branches` (`<dono>/<área>-<slug>`). Detalhes de tasks, ordem e gates em [`docs/PLANO_IMPLEMENTACAO.md`](docs/PLANO_IMPLEMENTACAO.md).

---

## Documentação

- [Plano de implementação](docs/PLANO_IMPLEMENTACAO.md) — tasks, branches, ordem de desenvolvimento e gates.
- [Requisitos funcionais](docs/REQUISITOS_FUNCIONAIS.md) — RFs, máquina de estados, schemas e critérios de aceite.

---

## Visão

`Order Operations → Supplier Ops → Procurement → Credit/Finance`, sempre dentro da operação do distribuidor. WhatsApp é o wedge inicial, não a fronteira do produto.