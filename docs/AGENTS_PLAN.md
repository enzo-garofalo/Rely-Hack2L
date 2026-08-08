# Opero — Arquitetura de Agentes

> Documento de referência da equipe de agentes. Fonte da verdade para contratos,
> estados e guardrails. Se algo neste arquivo conflitar com o código, o código
> está errado — conserte o código, não o documento.

---

## Princípio central

**Orquestração é determinística. Interpretação é LLM.** Essa separação é a coluna
vertebral do sistema.

- O **Supervisor** decide *o que* acontece e *quando*. Não chama LLM, não interpreta
  mensagem, não inventa nada. É uma máquina de estados.
- Os **agentes de LLM** são *capacidades* que o Supervisor invoca. Eles interpretam,
  sugerem e validam — mas nunca controlam o fluxo nem escrevem no ERP por conta própria.

Regra de ouro do sistema inteiro: **o LLM propõe, o determinístico dispõe.**

Os agentes **não conversam entre si**. Toda coordenação passa pelo Supervisor. Não há
Intake chamando Memory, nem Memory chamando Validation. Isso mantém o sistema auditável
e limita ação indevida.

---

## Fluxo P0

```text
Áudio/Texto (WhatsApp)
        │  (voz → Scribe v2 → texto, quando for áudio)
        ▼
   Supervisor  ──invoca──►  Order Intake Agent
        │
        ├──invoca (opcional)──►  Operational Memory Agent  (recall)
        │
        ├──invoca──►  Validation Agent  ◄──► ERP Simulator (leitura)
        │                    │
        │                    └─ ambiguidade? → pergunta ao cliente
        │
        ▼
   waiting_customer → confirmação do cliente
        ▼
   pending_approval → aprovação do operador
        ▼
   Supervisor  ──invoca──►  ERP Execution Agent  ──► ERP Simulator (escrita idempotente)
        ▼
   Pedido criado (system of record)
        │
        └─ Memory Agent (propose): registra alias confirmado como MemoryProposal
```

---

## Supervisor de orquestração

Máquina de estados determinística. Sem LLM. Controla estados, permissões e transições.

### Estados

```text
received
parsing
memory_loaded
validating
waiting_customer
ready_for_confirmation
customer_confirmed
pending_approval
sending_to_erp
sent_to_erp
```

### Tabela de transições

| De | Para | Gatilho | Agente acionado | Guard |
|---|---|---|---|---|
| `received` | `parsing` | mensagem recebida | Order Intake | — |
| `parsing` | `memory_loaded` | itens extraídos | Operational Memory (recall) | opcional; pode pular |
| `memory_loaded` | `validating` | hints prontos | Validation | — |
| `validating` | `waiting_customer` | ambiguidade aberta | — | há ambiguidade não resolvida |
| `validating` | `ready_for_confirmation` | tudo resolvido | — | nenhuma pendência |
| `waiting_customer` | `validating` | cliente respondeu | Validation (reprocessa item) | resposta é do cliente |
| `ready_for_confirmation` | `customer_confirmed` | cliente confirmou resumo | — | resumo apresentado |
| `customer_confirmed` | `pending_approval` | — | — | — |
| `pending_approval` | `sending_to_erp` | operador aprovou | ERP Execution | confirmado **e** aprovado |
| `sending_to_erp` | `sent_to_erp` | pedido criado | — | resposta do ERP com id |

### Guards críticos (não negociáveis)

- Nenhuma escrita no ERP antes de `customer_confirmed` **e** `operator_approved`.
- Em `waiting_customer`, só aceita input do cliente. Nenhuma outra transição destrava.
- Uma resposta de esclarecimento reprocessa **apenas o item ambíguo** (patch), nunca
  reinterpreta o pedido inteiro do zero.

---

## Order Intake Agent

Estrutura a mensagem livre em itens. Preserva a evidência original.

- **Entrada:** mensagens da conversa + schema de saída.
- **Ação:** uma chamada de modelo com saída estruturada. Sem tools.
- **Saída:**

```json
{
  "items": [
    {
      "id": "item-1",
      "rawText": "10 cx de coca 2L",
      "productGuess": "coca 2L",
      "quantity": 10,
      "unit": "caixa",
      "confidence": 0.9,
      "sku": null,
      "ambiguities": []
    }
  ],
  "deliveryDate": "2026-08-09",
  "missingFields": [],
  "evidence": ["trecho literal da mensagem que originou cada item"]
}
```

**Guardrail:** não resolve SKU, não consulta preço, não inventa item que não está na
mensagem. Só estrutura o que foi dito e marca o que ficou faltando.

---

## Operational Memory Agent

Consultor com evidência. **Sugere, nunca afirma.** Duas operações separadas.

### 1. `recall` — leitura, durante o intake

Opcional. Se nenhum item se beneficia de histórico, devolve vazio e o fluxo segue.

- **Entrada:** `customerId` + itens extraídos.
- **Tool:** `get_customer_memory(customerId)` → aliases, preferências, pedidos recentes.
- **Saída:** *hints*, não resoluções. Cada hint aponta para um item, diz o que sugere,
  com que confiança, e **com qual evidência**.

```json
{
  "hints": [
    {
      "itemRef": "item-2",
      "type": "alias_resolution",
      "suggests": { "field": "sku", "value": "OLEO-SOJA-900ML-CX20" },
      "confidence": 0.9,
      "evidence": "Cliente comprou OLEO-SOJA-900ML-CX20 nos 3 últimos pedidos.",
      "status": "suggestion"
    }
  ],
  "preferences": [
    { "type": "delivery_window", "value": "manhã",
      "evidence": "Últimas 5 entregas aceitas pela manhã." }
  ]
}
```

### 2. `propose` — escrita, depois da confirmação

Roda **só depois** do cliente confirmar o esclarecimento. Não vira fato: vira proposta
pendente de revisão.

- **Tool:** `create_memory_proposal(proposal)` → `{ proposalId, status: "pending_review" }`.

```json
{
  "customerId": "CUST-001",
  "type": "alias",
  "observed": "fardo da zero",
  "resolvedSku": "COCA-ZERO-LATA-CX12",
  "status": "pending_review",
  "evidence": {
    "source": "customer_confirmation",
    "conversationRef": "msg-7",
    "quote": "Sim, é o fardo com 12 latas de 350ml"
  }
}
```

### Guardrails

- Nunca escreve SKU, preço, estoque ou total como fato. Sugere um candidato; quem
  confirma que o SKU existe é o Validation.
- Todo hint carrega `evidence`. Sem evidência rastreável, não sai hint.
- Toda proposta nasce `pending_review`. Aprendizado nunca é automático.
- Confiança baixa não fecha item sozinha — vira insumo para pergunta de esclarecimento.

---

## Validation Agent

Peça central. É onde vive a maior parte da lógica determinística. **Resolve SKUs,
consulta ERP, calcula total, e formula a pergunta de esclarecimento** quando há
ambiguidade (é ele que tem o contexto do catálogo para saber quais são os candidatos).

- **Entrada:** item (do Intake) + hints (do Memory, quando houver).
- **Tools:**
  - `search_catalog(query)` — resolve nome informal → SKUs reais.
  - `get_price(sku)`
  - `check_inventory(sku)`
  - `calculate_total(items)` — determinístico.
- **Saída:** item resolvido **ou** ambiguidade estruturada.

Item resolvido:

```json
{
  "itemRef": "item-1",
  "status": "resolved",
  "sku": "COCA-2L-CX6",
  "unit": "caixa com 6",
  "unitPrice": 54.00,
  "inStock": true
}
```

Ambiguidade (o Validation gera a pergunta pronta):

```json
{
  "itemRef": "item-3",
  "status": "ambiguous",
  "ambiguities": [
    {
      "field": "sku",
      "question": "A Coca Zero é o fardo com 12 latas de 350 ml?",
      "candidates": ["COCA-ZERO-LATA-CX12"]
    }
  ]
}
```

### Guardrails

- Aceita **somente** SKUs retornados pelo catálogo. Nunca inventa produto, preço,
  estoque ou total.
- Se o SKU sugerido pelo Memory não existir mais no catálogo, descarta o hint e trata
  o item como não resolvido.
- Toda pergunta ao cliente é lastreada em dado do ERP — nunca uma dúvida inventada
  pelo modelo.

---

## ERP Execution Agent

Cria o pedido aprovado no ERP com idempotência.

- **Pré-condições (checadas pelo Supervisor):**
  - Cliente confirmou (`customer_confirmed`).
  - Operador aprovou (`operator_approved`).
  - Nenhuma pendência aberta.
- **Tool:** `create_erp_order(payload, idempotencyKey)`.
- **Saída:** recibo com número externo do pedido + `status: sent_to_erp`.

```json
{
  "externalOrderId": "ERP-2026-0042",
  "status": "sent_to_erp",
  "idempotencyKey": "order-CUST-001-msg-7",
  "payload": { "customerId": "CUST-001", "items": ["..."], "total": 2196.00 }
}
```

### Guardrails

- Usa `Idempotency-Key`. A mesma confirmação nunca cria dois pedidos.
- Não escreve nada antes das pré-condições. O Supervisor bloqueia.
- O ERP permanece como **system of record**. O agente não é a fonte da verdade.

---

## Objeto compartilhado: `OrderContext`

Os quatro agentes operam sobre um único objeto de contexto. Sem microserviços, sem
filas, sem conversa livre entre agentes.

```json
{
  "conversationId": "conv-001",
  "state": "validating",
  "customer": { "id": "CUST-001", "phone": "..." },
  "deliveryDate": "2026-08-09",
  "items": [ "..." ],
  "hints": [ "..." ],
  "ambiguities": [ "..." ],
  "total": null,
  "approvals": { "customerConfirmed": false, "operatorApproved": false },
  "erpReceipt": null,
  "events": [ "log de tool calls e transições de estado" ]
}
```

`events` é o que alimenta a timeline dos agentes na interface e serve de trilha de
auditoria para a banca.

---

## Camada de modelo (Featherless)

Featherless é o **provedor de inferência** do projeto — API OpenAI-compatible que serve
modelos open (Qwen, DeepSeek, GLM, Kimi, etc). Ele entra na camada de modelo, **não** na
orquestração: os agentes são nossos, o Supervisor é nosso, o Featherless só serve o
modelo por trás de cada chamada de agente.

> **Sobre o Hermes Agent (marketplace do Featherless):** é um assistente pessoal
> gerenciado (memória persistente + canais tipo Telegram/WhatsApp). **Não** usar como
> orquestrador — ele é um loop de agente genérico governado por LLM, o oposto do
> Supervisor determinístico que a nossa arquitetura exige. O Supervisor continua sendo
> código nosso.

### Como plugar

Interface OpenAI-compatible — aponta o SDK da OpenAI pro `base_url` do Featherless:

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.featherless.ai/v1",
    api_key=FEATHERLESS_API_KEY,
)

resp = client.chat.completions.create(
    model="Qwen/Qwen3.6-...",     # ver catálogo em featherless.ai/models
    messages=[...],
    tools=[...],                   # tool calling suportado
)
```

Trocar de provedor = trocar `base_url` + `model`. É isso que torna o fallback barato.

### Qual modelo por agente

| Agente | Precisa de | Modelo sugerido (Featherless) |
|---|---|---|
| Order Intake | structured output preciso | Qwen 3.6 ou DeepSeek 4 |
| Operational Memory | hints simples com evidência | Qwen 3.6 (médio) |
| Validation | tool calling confiável | DeepSeek 4 ou GLM 5.2 |
| ERP Execution | um único tool call | modelo médio basta |

Teste 2 modelos por agente e fique com o que devolve JSON / tool call mais confiável.
Confira também os limites de concorrência do plano (Concurrent Unit Limits) — quatro
agentes chamando em paralelo consomem unidades simultâneas.

### Structured output em modelo open (guardrail)

Modelos open às vezes escapam do `response_format`. Para Intake e Validation, prefira
**tool calling** para forçar a saída no schema, e tenha parsing com `try/except` + um
retry. Não confie que vem JSON limpo de primeira.

### Estratégia de fallback (protege a demo)

Como tudo é OpenAI-compatible, cada agente troca de modelo mudando uma linha. Regra:

1. Featherless é o provedor **primário** — é o desafio do patrocinador, use no core.
2. Se **um** agente específico estiver falhando structured output perto do deadline
   (quase sempre o Intake), troque **só ele** por um modelo mais forte do próprio
   Featherless — sem tocar no resto.
3. Só em último caso, se nada no Featherless segurar, caia esse agente isolado para um
   modelo proprietário. Nunca aposte a jornada inteira num modelo instável às 05:00.

---

## Entrada por voz (ElevenLabs)

Camada opcional, entra **depois** do fluxo de texto rodar três vezes. O pedido pode
chegar como áudio (como chega no WhatsApp na vida real).

- Áudio → **Scribe v2** (STT) → texto → entra no Order Intake sem mudar mais nada.
- Use **keyterm prompting** com os nomes de produtos/SKUs para a transcrição não errar
  "coca zero", "óleo", etc.
- Na demo, use **áudio gravado**, não voz ao vivo (reprodutibilidade + sem risco de
  microfone/ruído na frente da banca).
- TTS (o sistema responder em voz) é bônus, só se sobrar tempo.

---

## Guardrails globais (resumo)

1. Nenhum SKU, preço, estoque ou total inventado — tudo vem de tool call contra o ERP.
2. Nenhuma escrita no ERP antes de confirmação do cliente **e** aprovação do operador.
3. Nenhum pedido duplicado — idempotência na criação.
4. Memória sempre propõe, nunca afirma — aprendizado nasce `pending_review`.
5. Todo hint e toda proposta carregam evidência rastreável.
6. Agentes não conversam entre si — o Supervisor coordena tudo.
