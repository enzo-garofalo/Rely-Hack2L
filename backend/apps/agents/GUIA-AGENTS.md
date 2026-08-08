# Guia de uso — `apps.agents`

> Documento prático: como consumir a pipeline de agentes de outro código
> (view, comando, teste). Para entender a arquitetura e os guardrails em
> profundidade, veja `docs/AGENTS_PLAN.md` (fonte da verdade). Este guia
> não repete aquele conteúdo — mostra como usar o que já está pronto.

## Regra de ouro pra quem for consumir isto

**Nunca importe `orchestrator.py`, os agentes (`intake.py`, `memory.py`,
`validation.py`, `erp_execution.py`) ou `context.py` direto do seu
código.** A ponte oficial é `apps.core.order_service` — é ela que sabe
reconstruir o `OrderContext` a partir do banco, persistir o resultado, e
lidar com `OrderVersion`/`CustomerConfirmation`/`OperatorApproval`. Chamar
o Supervisor direto significa reimplementar essa ponte, e as views HTTP já
fazem isso por você (`apps/core/views.py`).

Esta pasta (`apps/agents/`) é contrato entre o time de agentes e o time de
backend — schemas, `OrderContext` e as assinaturas dos agentes não mudam
sem os dois lados combinarem.

## Pré-requisitos de ambiente

No `.env` da raiz do repo:

```bash
FEATHERLESS_API_KEY=<sua key>
MODEL_ORDER_INTAKE=<modelo escolhido, ex.: zai-org/GLM-5.2>
MODEL_OPERATIONAL_MEMORY=<modelo escolhido>
MODEL_VALIDATION=<modelo escolhido>
MODEL_ERP_EXECUTION=<modelo escolhido>
```

As 4 variáveis `MODEL_*` são **obrigatórias** — sem elas, `llm_client.get_model_for_agent`
levanta `RuntimeError` explícito (nenhum modelo default escondido). O
modelo é só o nome do repositório no catálogo da Featherless (ex.:
`Qwen/Qwen3.6-27B`), só funciona com modelos com suporte a **tool
calling** (badge "TOOLS" no catálogo) — o wrapper força `tool_choice`.

Sem `FEATHERLESS_API_KEY` configurada, `get_client()` também levanta
`RuntimeError` — os 3 agentes que usam LLM (Intake, Memory, e o passo de
esclarecimento do Validation) tratam isso e devolvem `AgentResult` com
`status=ERROR` em vez de deixar a exceção escapar.

## Como consumir — `apps.core.order_service`

Cada função abaixo já é `@transaction.atomic`: ou o pedido avança e tudo
é persistido, ou nada muda no banco.

### Criar um pedido a partir de uma mensagem (texto)

```python
from apps.core.order_service import ingest_message

outcome = ingest_message(customer_id=42, message="quero 3 caixas de coca 2L pra amanha")
outcome.order.id          # PK do Order criado
outcome.order.state       # "ready_for_confirmation" | "waiting_customer" | "parsing" (se falhou)
outcome.result.status     # AgentStatus.OK | AgentStatus.ERROR
outcome.result.error      # motivo, se status == ERROR
```

Roda a pipeline inteira (Intake → Memory → Validation) numa chamada só e
para sozinho em `waiting_customer` (se sobrou ambiguidade) ou
`ready_for_confirmation` (se tudo resolveu).

### Criar um pedido a partir de áudio (voz, ElevenLabs)

```python
from apps.core.order_service import ingest_audio_message

outcome = ingest_audio_message(customer_id=42, audio_file=arquivo_upload)
```

Transcreve via ElevenLabs (`apps.core.voice`) e cai no mesmo pipeline de
texto — nunca um fluxo paralelo. Se a transcrição falhar, cai pro
fallback de voz (RNF09) antes de desistir.

### Responder um esclarecimento pendente

```python
from apps.core.order_service import submit_customer_reply

outcome = submit_customer_reply(order_id=order.id, message="a de 600ml mesmo")
# item_ref é opcional: sem ele, assume o primeiro item ainda ambíguo
```

Só funciona se `order.state == "waiting_customer"` — caso contrário
levanta `OrderServiceError` (guard do Supervisor violado).

### Confirmar (cliente) e aprovar (operador)

```python
from apps.core.order_service import confirm_customer, approve_operator

order = confirm_customer(order_id=order.id)               # -> pending_approval
outcome = approve_operator(order_id=order.id, approved_by="operador@empresa.com")
outcome.order.state         # "sent_to_erp" | "erp_execution_failed"
```

`approve_operator` só escreve no ERP se `customerConfirmed` **e**
`operatorApproved` — nunca antes. Chamar fora de ordem levanta
`OrderServiceError`.

### Erros possíveis

Todas as funções acima podem levantar `OrderServiceError` (uso da API
inválido pro estado atual — trate como HTTP 409) além das exceções óbvias
(`Order.DoesNotExist`, `Customer.DoesNotExist`). Um `AgentResult` com
`status=ERROR` **não** é uma exceção — é um resultado válido que significa
"o agente rodou e falhou de forma controlada" (ex.: LLM fora do ar). Sempre
cheque `outcome.result.status` além do `try/except`.

### Outras funções úteis

- `reset_demo()` — apaga e recria o dataset congelado (usado pelo botão
  "Reset demo" da UI / `POST /api/demo/reset`).
- `response_text_for_order(order)` — monta o texto de resposta ao cliente
  pro estado atual do pedido (usado pra gerar o áudio de resposta via TTS).

## A máquina de estados (resumo)

```text
received → parsing → memory_loaded → validating
   ├── waiting_customer ──(customer_reply)──► validating   (reprocessa 1 item, patch)
   └── ready_for_confirmation ──(confirm)──► customer_confirmed → pending_approval
          ──(approve)──► sending_to_erp → sent_to_erp | erp_execution_failed
```

Documentação completa da tabela de transições e guards: `docs/AGENTS_PLAN.md`.
Implementação: `orchestrator.py` (`Supervisor`).

## Os 4 agentes, em uma linha cada

| Agente | Arquivo | Usa LLM? | O que faz |
|---|---|---|---|
| Order Intake | `intake.py` | sempre | Estrutura a mensagem livre em itens (`OrderDraft`). Sem tools. |
| Operational Memory | `memory.py` | só se há histórico | `run()`: recall — sugere hints com evidência a partir de `get_customer_memory`. `propose()`: grava alias confirmado como `MemoryProposal` (`pending_review`), mecânico. |
| Validation | `validation.py` | só com 2+ candidatos ambíguos | Resolve SKU via hint de memória ou `search_catalog`, calcula total via `calculate_total`. A maior parte é determinística. |
| ERP Execution | `erp_execution.py` | nunca | Checa pré-condições, chama `create_erp_order` com Idempotency-Key. |

Cada agente abre e fecha seu próprio `AgentRun` (auditoria, `audit.py`) —
inclusive nos caminhos de erro, nunca deixa um registro pendurado aberto.

## Guardrails que não podem ser quebrados

1. Nenhum SKU/preço/estoque/total inventado — tudo vem de `tools.py`, que
   fala com `erp_simulator` via ORM direto (decisão do time: sem API
   HTTP própria pro ERP simulado).
2. `calculate_total` é a única fonte de total — nunca somado à mão.
3. Nenhuma escrita no ERP sem `customerConfirmed` **e** `operatorApproved`.
4. `create_erp_order` é idempotente por chave — replay nunca duplica.
5. Memória só sugere (`MemoryHint`) ou propõe (`MemoryProposal`,
   `pending_review`) — nunca vira fato confirmado sozinha.
6. Ambiguidade nunca é resolvida em silêncio — vira pergunta, sempre
   lastreada em candidato real do catálogo.
7. Falha de agente vira `AgentResult(status=ERROR)`, nunca uma exceção
   solta nem um sucesso inventado.
8. `output_data`/`input_data`/mensagens de erro gravados em `ToolCall`
   passam por `sanitize()` (`sanitize.py`) antes de ir pro banco.

## Testando isoladamente (sem passar pela API HTTP)

```bash
docker compose exec backend python manage.py shell
```

```python
from apps.core.models import Customer, Order, Conversation
from apps.agents.context import OrderContext, CustomerRef
from apps.agents import intake, memory, validation, erp_execution
from apps.agents.orchestrator import Agents, Supervisor

customer = Customer.objects.first()
order = Order.objects.filter(customer=customer).first()
ctx = OrderContext(orderId=order.id, conversationId=str(order.conversation_id),
                    customer=CustomerRef(id=customer.id, phone=customer.phone))

sup = Supervisor(Agents(intake.run, memory.run, validation.run, erp_execution.run))
sup.receive_message(ctx, "3 caixas de coca 2L")
print(ctx.state, ctx.resolvedItems, ctx.ambiguities)
```

Isso roda a pipeline **sem** tocar em `OrderVersion`/`OrderItem` (fica só
em memória) — útil pra depurar um agente sem se preocupar com persistência.
Pra testar uma tool isolada, toda função de `tools.py` exige um `AgentRun`
já criado (`from apps.agents import audit; run = audit.start_agent_run(ctx, AgentName.VALIDATION)`).

## Ferramenta de debug local (dashboard)

Existe um dashboard HTML com estado em tempo real, logs ao vivo e ações
interativas (`python manage.py visualize`), em
`apps/agents/visualization/` + `apps/agents/management/commands/visualize.py`.
**Não é parte do produto e não está versionado** (`.git/info/exclude`) —
é uma ferramenta pessoal de quem estiver mexendo em `agents/` no momento.
Se você não vê esses arquivos no seu clone, é esperado.
