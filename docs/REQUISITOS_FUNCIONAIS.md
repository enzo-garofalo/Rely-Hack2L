# Requisitos Funcionais — Opero

> **Escopo:** jornada única P0 do hackathon — uma conversa B2B do WhatsApp vira um pedido validado, confirmado, aprovado por humano e criado no ERP simulado, com auditoria completa.
>
> **Stack:** React (Vite) · Django + DRF · PostgreSQL · Docker Compose · ElevenLabs (voz).
>
> **Escopo estendido:** entrada e resposta por voz — o cliente pode mandar o pedido em áudio; o sistema transcreve com ElevenLabs e pode responder por voz.
>
> **Fora de escopo (P0):** Supplier Agent, login, dashboard, CRUD de clientes/catálogo, crédito, múltiplos clientes, WhatsApp real, follow-up automático.

---

## 1. Atores

| Ator | Descrição | Interface |
|---|---|---|
| Cliente empresarial | Cliente B2B do distribuidor (ex.: Mercado Boa Compra). Envia o pedido. | Chat estilo WhatsApp (simulado). |
| Operador | Funcionário do distribuidor. Revisa e aprova. | Console web (tela única). |
| Agentes | Order Intake, Memory, Validation, ERP Execution. | Backend. |
| Orquestrador | Coordena estados e permissões (determinístico, sem LLM). | Backend. |
| ERP simulado | System of record de catálogo, preço, estoque e pedido. | API HTTP. |
| ElevenLabs | Serviço externo de voz: transcrição (STT) do áudio e síntese (TTS) das respostas. | API HTTP. |

---

## 2. Requisitos funcionais

### 2.1 Entrada do pedido

- **RF01** O sistema deve permitir que uma mensagem livre do cliente seja recebida e persistida, associada a uma conversa e a um pedido.
- **RF02** Ao receber a primeira mensagem, o sistema deve criar um pedido em estado `received` e disparar o pipeline de agentes.
- **RF03** Mensagens consecutivas da mesma conversa devem ser associadas ao mesmo pedido, sem criar pedido duplicado.

### 2.2 Interpretação (Order Intake Agent)

- **RF04** O sistema deve estruturar a mensagem em itens (produto informal, quantidade, unidade), data de entrega e observações, com saída em schema tipado.
- **RF05** Cada item estruturado deve preservar o trecho original da mensagem como evidência.
- **RF06** O sistema deve marcar campos ausentes ou de baixa confiança para tratamento posterior.
- **RF07** O Order Intake Agent não deve definir preço, estoque nem criar pedido no ERP.

### 2.3 Memória operacional (Operational Memory Agent)

- **RF08** O sistema deve recuperar memória `cliente ↔ distribuidor` (aliases e preferências aprovadas) quando ela ajudar a interpretar o pedido — por exemplo, resolver "óleo da última vez" para o SKU correto.
- **RF09** A memória deve ser consultada como capacidade (quando houver contexto útil), não como etapa obrigatória de todo pedido.
- **RF10** Após uma correção ou confirmação, o sistema deve poder criar uma `MemoryProposal` com evidência, em status `pending_review`.
- **RF11** Uma proposta de memória não deve virar alias confiável automaticamente; requer regra/revisão.
- **RF12** A memória nunca deve substituir catálogo, preço ou estoque atuais do ERP.

### 2.4 Validação comercial (Validation Agent)

- **RF13** O sistema deve buscar candidatos no catálogo do ERP e só aceitar SKUs efetivamente retornados por ele.
- **RF14** O sistema deve consultar preço por cliente e estoque por produto no ERP.
- **RF15** O sistema deve calcular subtotal e total com função determinística, nunca por texto livre do modelo.
- **RF16** Quando houver ambiguidade (ex.: "fardo da zero"), o sistema deve bloquear o item e emitir uma pergunta objetiva de esclarecimento.
- **RF17** O sistema deve revalidar o pedido após cada resposta do cliente.
- **RF18** O Validation Agent não deve inventar SKU, preço, estoque ou total, nem substituir produto sem consentimento.

### 2.5 Esclarecimento

- **RF19** O sistema deve enviar ao cliente apenas a pergunta necessária, pela mesma conversa.
- **RF20** A resposta do cliente deve ser associada ao pedido existente e atualizar somente os campos afetados.

### 2.6 Confirmação do cliente

- **RF21** O sistema deve apresentar ao cliente um resumo com itens, unidades, preços, total e entrega.
- **RF22** A confirmação do cliente deve ser explícita e vinculada à versão exata do pedido.
- **RF23** Qualquer alteração posterior deve invalidar a confirmação anterior.

### 2.7 Aprovação humana

- **RF24** O operador deve conseguir revisar dados, evidências, validações e mensagens em uma única tela.
- **RF25** O sistema deve exigir aprovação humana antes de qualquer escrita no ERP.
- **RF26** Uma correção após a aprovação deve criar nova versão e invalidar a aprovação anterior.

### 2.8 Execução no ERP (ERP Execution Agent)

- **RF27** A execução só pode ocorrer se o pedido estiver confirmado pelo cliente e aprovado pelo operador na mesma versão, sem pendências abertas.
- **RF28** O sistema deve enviar o pedido ao ERP com uma `Idempotency-Key`.
- **RF29** Em caso de timeout, o sistema deve consultar o pedido pela chave de idempotência antes de tentar novamente, evitando duplicação.
- **RF30** O sistema deve salvar o número externo do pedido e exibir o recibo.
- **RF31** Após sucesso, o cliente deve receber uma confirmação final.

### 2.9 ERP Simulado

- **RF32** O ERP simulado deve expor `GET /api/erp/context/{customerId}` retornando cliente, catálogo, preços e estoque.
- **RF33** O ERP simulado deve expor `POST /api/erp/orders` com autenticação por API key e suporte a `Idempotency-Key`.
- **RF34** O ERP simulado deve expor `GET /api/erp/orders/{id}` para consulta do pedido criado.
- **RF35** Chamar `POST /api/erp/orders` com a mesma chave de idempotência deve devolver o pedido existente, sem criar um novo.
- **RF36** O ERP simulado deve permanecer como system of record; o Opero opera sobre ele, não o substitui.

### 2.10 Auditoria e logs

- **RF37** Toda execução de agente deve gerar um registro (`AgentRun`) com estado anterior, próximo, motivo e versão.
- **RF38** Toda chamada de ferramenta deve gerar um `ToolCall` com nome, entrada e saída sanitizadas.
- **RF39** O sistema deve expor uma timeline consolidada que permita seguir o pedido de ponta a ponta.

### 2.11 Reset e demonstração

- **RF40** O sistema deve oferecer um `POST /api/demo/reset` que restaura o dataset congelado a um estado idêntico.
- **RF41** A interface deve oferecer um botão `Reset demo` que limpa a tela e reinicia o cenário.

### 2.12 Entrada e resposta por voz (ElevenLabs)

- **RF42** O cliente deve poder enviar o pedido em áudio, gravando na própria interface ou anexando um arquivo de áudio.
- **RF43** O sistema deve transcrever o áudio para texto usando a API de speech-to-text da ElevenLabs (Scribe).
- **RF44** A transcrição deve alimentar exatamente o mesmo pipeline de agentes de uma mensagem de texto — o áudio é apenas mais um canal de entrada, não um fluxo paralelo.
- **RF45** O sistema deve preservar o áudio original e a transcrição como evidência, associados ao pedido (complementando RF05).
- **RF46** O sistema deve exibir a transcrição ao operador antes de processar, de forma que uma transcrição claramente errada seja visível e auditável.
- **RF47** O sistema deve tratar falha ou baixa confiança de transcrição sem quebrar o fluxo: exibir o erro e permitir reenvio ou entrada por texto.
- **RF48** O sistema deve poder responder ao cliente por voz, sintetizando a pergunta de esclarecimento e/ou o resumo com a API de text-to-speech da ElevenLabs.
- **RF49** A resposta por voz é complementar: o texto correspondente deve sempre existir, e a ausência de áudio nunca deve bloquear o fluxo.
- **RF50** A chave da ElevenLabs deve ficar apenas no backend; o áudio trafega back ↔ ElevenLabs, nunca direto do frontend.

---

## 3. Máquina de estados (referência)

```text
received → parsing → memory_loaded → validating
   ├── waiting_customer → validating          (esclarecimento)
   └── ready_for_confirmation
          → customer_confirmed
          → pending_approval
          → sending_to_erp
                ├── sent_to_erp                (sucesso)
                └── erp_execution_failed       (falha → revisão humana)
```

- Somente o orquestrador altera o estado principal.
- `customer_confirmed` exige mensagem explícita do cliente.
- `pending_approval → sending_to_erp` exige confirmação + aprovação da mesma versão.
- Falha nunca é convertida em sucesso por inferência do modelo.

---

## 4. Schemas de saída dos agentes (contrato)

Estes são a linguagem comum entre backend e AI. Devem ser congelados antes de codar.

```jsonc
// OrderDraft (Order Intake Agent)
{
  "items": [
    { "rawText": "10 cx de coca 2L", "quantity": 10, "unit": "CX", "productHint": "coca 2L", "confidence": 0.9 }
  ],
  "deliveryDate": "2026-08-09",
  "missingFields": [],
  "evidence": ["10 cx de coca 2L", "6 fardos da zero", "15 do óleo da última vez"]
}

// MemoryContext / MemoryProposal (Memory Agent)
{
  "resolved": [ { "productHint": "óleo da última vez", "sku": "OLEO-SOJA-900ML-CX20", "source": "memory" } ],
  "proposals": [ { "alias": "fardo da zero", "sku": "COCA-ZERO-LATA-CX12", "status": "pending_review", "evidence": "resposta do cliente" } ]
}

// ValidatedOrder / ClarificationRequest (Validation Agent)
{
  "status": "needs_clarification",          // ou "validated"
  "question": "A Coca Zero é o fardo com 12 latas de 350 ml?",
  "items": [
    { "sku": "COCA-2L-CX6", "quantity": 10, "unit": "CX", "unitPrice": 54.0, "inStock": true }
  ],
  "total": 540.0
}

// ErpReceipt (ERP Execution Agent)
{
  "erpOrderId": "ERP-2026-0001",
  "status": "sent_to_erp",
  "idempotencyKey": "opero-ord_001-v3"
}
```

---

## 5. Dataset congelado

### Cliente
- Mercado Boa Compra · telefone demonstrativo · entrega: amanhã.

### Produtos

| Pedido informal | SKU | Unidade | Preço | Estoque |
|---|---|---|---:|---:|
| coca 2L | `COCA-2L-CX6` | caixa com 6 | R$ 54,00 | 80 |
| zero (após esclarecer) | `COCA-ZERO-LATA-CX12` | fardo com 12 | R$ 42,00 | 45 |
| óleo da última vez | `OLEO-SOJA-900ML-CX20` | caixa com 20 | R$ 118,00 | 30 |

### Memória aprovada (cliente ↔ distribuidor)
- "coca 2L" → costuma ser caixa com 6.
- Último óleo comprado → `OLEO-SOJA-900ML-CX20`.
- Cliente aceita entrega pela manhã.

### Proposta gerada na demo
- Alias: "fardo da zero" → `COCA-ZERO-LATA-CX12` · status `pending_review` · evidência: resposta do cliente.

---

## 6. Requisitos não funcionais

- **RNF01** Determinismo: preço, estoque, catálogo e total vêm sempre do ERP/funções puras, nunca do modelo.
- **RNF02** Idempotência: toda criação no ERP usa `Idempotency-Key`; timeout consulta antes de repetir.
- **RNF03** Reprodutibilidade: `reset` devolve o sistema a um estado idêntico; a demo roda 3× seguidas.
- **RNF04** Isolamento do ERP: os agentes só acessam o ERP simulado via HTTP com API key.
- **RNF05** Observabilidade: cada `AgentRun` e `ToolCall` é persistido e visível na timeline.
- **RNF06** Contêinerização: `docker-compose up` sobe db + backend + frontend.
- **RNF07** Fallback: existe uma resposta pré-gravada caso o modelo falhe durante a apresentação.
- **RNF08** Voz não bloqueante: transcrição e síntese pela ElevenLabs são chamadas isoladas; se a API falhar ou demorar, o fluxo continua por texto sem travar.
- **RNF09** Fallback de voz na demo: existe um áudio pré-gravado e sua transcrição esperada, caso a ElevenLabs falhe ao vivo.
- **RNF10** Segredo protegido: a API key da ElevenLabs vive só no backend, nunca no frontend.

---

## 7. Critérios de aceite (Definition of Done)

- [ ] Mensagem aparece no chat e cria o pedido.
- [ ] Os 4 agentes aparecem na timeline com tool calls visíveis.
- [ ] Memória resolve "óleo da última vez" para o SKU correto.
- [ ] Ambiguidade "fardo da zero" gera pergunta ao cliente.
- [ ] Catálogo, preço e estoque vêm do ERP simulado.
- [ ] Cliente confirma uma versão específica; correção invalida a confirmação.
- [ ] Operador aprova antes de qualquer escrita.
- [ ] Pedido é criado no ERP uma única vez (idempotência comprovada).
- [ ] Recibo do ERP é exibido com número externo e chave.
- [ ] Proposta de memória é gerada e auditável.
- [ ] Nenhum SKU, preço ou total inventado.
- [ ] `Reset demo` funciona e a jornada roda 3× seguidas.
- [ ] Cliente consegue enviar o pedido em áudio; a ElevenLabs transcreve e o texto entra no mesmo pipeline.
- [ ] A transcrição fica visível e auditável, com o áudio original preservado como evidência.
- [ ] O sistema responde por voz (esclarecimento ou resumo) via ElevenLabs, com o texto sempre presente.
- [ ] Falha da ElevenLabs não trava o fluxo (fallback por texto e áudio pré-gravado disponíveis).
