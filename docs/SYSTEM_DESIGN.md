# System Design — Opero

## 1. Objetivo e fontes de verdade

O Opero transforma uma conversa B2B em um pedido validado, confirmado pelo cliente, aprovado por um operador e criado uma única vez no ERP simulado. O sistema prioriza uma jornada P0 demonstrável, auditável e reprodutível.

Este documento descreve o desenho implementável. Em caso de conflito, prevalecem, nesta ordem:

1. `docs/REQUISITOS_FUNCIONAIS.md` para comportamento e guardrails;
2. schemas e máquina de estados executáveis em `backend/apps/agents/`;
3. contratos HTTP em `backend/apps/core/` e `backend/apps/erp_simulator/`;
4. `docs/PLANO_IMPLEMENTACAO.md` para sequência de entrega.

## 2. Escopo

### Incluído no P0

- entrada textual em chat estilo WhatsApp;
- interpretação estruturada com evidência e confiança;
- memória operacional aprovada e propostas de novos aliases;
- validação determinística de catálogo, preço, estoque e total;
- esclarecimento de ambiguidades;
- confirmação explícita do cliente por versão;
- aprovação humana antes de escrever no ERP;
- criação idempotente no ERP simulado;
- recibo e timeline auditável;
- reset reprodutível da demo.

### Enhancement condicionado ao P0

- entrada de áudio via ElevenLabs STT;
- resposta de áudio via ElevenLabs TTS;
- fallback integral por texto.

### Fora de escopo

- WhatsApp real, autenticação, multi-tenant completo, crédito, CRUD administrativo, filas externas, microserviços e processamento distribuído.

## 3. Arquitetura de alto nível

```text
┌──────────────────── Browser ────────────────────┐
│ React + Vite                                    │
│ Chat │ Pedido estruturado │ Timeline/Recibo     │
└──────────────────────┬──────────────────────────┘
                       │ HTTP /api
┌──────────────────────▼──────────────────────────┐
│ Django + DRF                                     │
│                                                  │
│ Core API → Order Service → Supervisor            │
│                              │                   │
│         Intake → Memory → Validation → Execution │
│                              │                   │
│                         Tools determinísticas    │
│                              │ HTTP + API key    │
│                         ERP Simulator API        │
│                                                  │
│ Voice Adapter ───────────────► ElevenLabs        │
└──────────────────────┬──────────────────────────┘
                       │ ORM
                ┌──────▼──────┐
                │ PostgreSQL  │
                └─────────────┘
```

Todos os componentes de backend vivem no mesmo processo Django, mas os agentes acessam o ERP simulado exclusivamente por HTTP. Essa fronteira preserva a integração real por API sem introduzir microserviços.

## 4. Componentes e responsabilidades

| Componente | Responsabilidade | Não pode fazer |
|---|---|---|
| React/Vite | Operar a jornada, apresentar estados, evidências, timeline e recibo | Autorizar transições ou conter segredos |
| Core API | Validar payload HTTP e expor o estado persistido | Inferir sucesso de agente |
| Order Service | Reconstruir/persistir `OrderContext` e coordenar eventos | Inventar dados comerciais |
| Supervisor | Aplicar a máquina de estados e chamar somente o agente permitido | Usar LLM para decidir transições |
| Intake Agent | Converter mensagens em `OrderDraft` tipado | Definir preço, estoque ou SKU final |
| Memory Agent | Recuperar memória aprovada e criar proposta auditável | Aprovar alias automaticamente |
| Validation Agent | Resolver catálogo e validar preço/estoque/total via tools | Aceitar SKU fora do catálogo |
| ERP Execution Agent | Verificar pré-condições e criar pedido idempotente | Escrever antes de confirmação e aprovação |
| Tools | Executar operações determinísticas e registrar `ToolCall` | Ocultar falhas |
| ERP Simulator | Ser system of record comercial e garantir idempotência | Ser acessado diretamente pelo frontend |
| Voice Adapter | Transcrever/sintetizar sem criar pipeline paralelo | Expor chave ElevenLabs ao browser |

## 5. Fluxo textual

1. O frontend envia `POST /api/orders/ingest/` com `customerId` e `message`.
2. O backend persiste conversa, mensagem, pedido e versão.
3. O Supervisor executa Intake, Memory e Validation em sequência.
4. Se houver ambiguidade, o pedido para em `waiting_customer`.
5. O frontend envia a resposta para `customer-reply`; apenas os campos afetados são revalidados.
6. Sem pendências, o pedido vai a `ready_for_confirmation`.
7. A confirmação cria `CustomerConfirmation` vinculada à versão e leva a `pending_approval`.
8. A aprovação cria `OperatorApproval` para a mesma versão.
9. O ERP Execution Agent usa `Idempotency-Key` e grava o recibo externo.
10. O frontend carrega pedido e timeline em paralelo e exibe o recibo.

## 6. Máquina de estados

```text
received → parsing → memory_loaded → validating
   ├── waiting_customer → validating
   └── ready_for_confirmation
          → customer_confirmed
          → pending_approval
          → sending_to_erp
                ├── sent_to_erp
                └── erp_execution_failed
```

Somente o Supervisor altera o estado principal. Confirmação, aprovação e escrita no ERP devem referenciar a mesma versão. Qualquer alteração posterior invalida autorizações anteriores.

## 7. Contratos HTTP

### Order API

| Método e rota | Entrada | Saída principal |
|---|---|---|
| `GET /api/health/` | — | `{ status }` |
| `POST /api/orders/ingest/` | `{ customerId, message }` | `{ orderId, state }` |
| `GET /api/orders/{id}/` | — | pedido, versão, itens, pendências e recibo |
| `POST /api/orders/{id}/customer-reply/` | `{ message, itemRef? }` | `{ orderId, state }` |
| `POST /api/orders/{id}/confirm/` | — | `{ orderId, state }` |
| `POST /api/orders/{id}/approve/` | `{ approvedBy, notes? }` | estado e `erpReceipt` |
| `GET /api/orders/{id}/timeline/` | — | mensagens, agentes, tools e transições |
| `POST /api/demo/reset/` | — | `{ status: "reset" }` |

### Voz

| Método e rota | Entrada | Comportamento |
|---|---|---|
| `POST /api/orders/ingest-audio/` | multipart `customerId` + `audio` | transcreve e chama o mesmo ingest textual |
| `GET /api/orders/{id}/voice-reply/` | — | MP3 ou JSON com texto de fallback |

### ERP Simulator

| Método e rota | Regra |
|---|---|
| `GET /api/erp/context/{customerId}/` | exige API key; retorna catálogo, preço e estoque |
| `POST /api/erp/orders/` | exige API key e `Idempotency-Key` |
| `GET /api/erp/orders/{id}/` | consulta recibo persistido |

## 8. Dados e ownership

- `Organization`, `Customer`, `Conversation`, `Message`: identidade e conversa.
- `Order`, `OrderVersion`, `OrderItem`: agregado versionado do pedido.
- `CustomerConfirmation`, `OperatorApproval`: autorizações ligadas à versão.
- `MemoryEntry`, `MemoryProposal`: memória aprovada e aprendizado pendente.
- `AgentRun`, `ToolCall`: auditoria de agentes e ferramentas.
- `ErpProduct`, `ErpPrice`, `ErpInventory`, `ErpAlias`: dados comerciais do ERP.
- `ErpOrder`, `ErpIdempotencyKey`: efeito externo e proteção contra duplicidade.

PostgreSQL é a persistência única. O frontend nunca mantém estado comercial como fonte de verdade; após uma mutação, recarrega pedido e timeline do backend.

## 9. Consistência, idempotência e concorrência

- totais são calculados por função pura;
- preço e estoque são consultados no ERP no momento da validação;
- cada escrita usa uma chave estável por pedido/versão;
- repetição com a mesma chave devolve o pedido existente;
- timeout deve consultar a chave antes de repetir;
- ações inválidas para o estado atual retornam conflito, nunca sucesso aparente;
- a UI bloqueia cliques repetidos, mas o backend continua responsável pela garantia.

## 10. Falhas e recuperação

| Falha | Resposta esperada |
|---|---|
| LLM indisponível ou saída inválida | `AgentResult.ERROR`, HTTP 502 e estado auditável |
| Ambiguidade | bloquear item e pedir somente o esclarecimento necessário |
| ERP timeout | consultar idempotência antes de retry |
| ERP rejeita | `erp_execution_failed`, erro visível e sem recibo inventado |
| ElevenLabs falha | manter texto, permitir reenvio/digitação e não bloquear P0 |
| Browser recarrega | reconstruir a tela consultando pedido/timeline persistidos |
| Reset | apagar somente dados voláteis e restaurar dataset congelado idêntico |

## 11. Segurança e privacidade

- chaves Featherless, ERP e ElevenLabs ficam somente no backend;
- `ToolCall` e timeline devem sanitizar segredos e payloads sensíveis;
- CORS limita a origem do frontend;
- aprovação na UI não substitui autorização e validação no backend;
- áudio é evidência persistida e deve seguir a mesma política de dados das mensagens.

## 12. Observabilidade

Cada agente gera `AgentRun` com início, fim, sucesso, motivo, estado anterior e próximo. Cada tool gera `ToolCall` com entrada, saída, erro e horário. A timeline consolida mensagens, runs, chamadas, confirmações, aprovações e transições em ordem cronológica.

## 13. Deploy local

O Docker Compose inicia:

- `db`: PostgreSQL 16 com volume persistente;
- `backend`: Django 5 + DRF na porta 8000;
- `frontend`: Vite dev server na porta 5173.

O `.env` fornece URLs e segredos locais. O frontend usa `VITE_API_BASE_URL`; o backend usa `ERP_BASE_URL` para respeitar a fronteira HTTP interna.

## 14. Estratégia de testes e gates

1. unitários de schemas, Supervisor, tools e serialização;
2. unitários de componentes e estados React;
3. integração da Order API com agentes substituídos por doubles determinísticos;
4. idempotência e transições inválidas;
5. build de produção e checks estáticos;
6. jornada textual completa três vezes após reset;
7. QA adversarial de payload, rede, concorrência, acessibilidade e segredos;
8. voz somente depois do gate textual.

## 15. Restrições conhecidas

- o pipeline HTTP atual é síncrono; a timeline representa a sequência persistida após cada ação, não streaming ao vivo;
- o P0 opera um cliente e cenário congelados;
- integrações externas dependem de credenciais fornecidas fora do repositório;
- a voz é descartável sem comprometer a tese do produto.
