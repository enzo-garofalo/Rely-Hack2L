# Opero: pitch de demo day

> **Tempo:** 3 minutos.
>
> **Estrutura do slide:** equipe, problema e solução com tecnologia demonstrada.
>
> **Objetivo:** falar pouco e deixar o produto provar.

---

## 1. Equipe

Somos o Opero.

Eu sou o Pedro, focado em produto, comercial, vendas e front-end. O Enzo está no backend e no ERP Simulator. O Guilherme está nos agentes de IA, schemas, prompts e validação.

Somos três founders técnicos construindo uma solução para uma dor operacional real de distribuidores B2B.

---

## 2. Problema

Distribuidores B2B recebem pedidos todos os dias pelo WhatsApp.

Esses pedidos chegam em linguagem informal: apelidos de produto, embalagem incompleta, referência ao último pedido, prazo de entrega e mensagens quebradas em várias partes.

Hoje alguém precisa interpretar tudo, conferir catálogo, preço e estoque, tirar dúvida com o cliente e depois redigitar no ERP. Isso gera fila, erro, retrabalho e impede a operação de vender mais sem contratar mais pessoas.

O problema não é o WhatsApp. O problema é o trabalho invisível entre a conversa e o pedido executável.

---

## 3. Solução

O Opero é uma camada operacional de agentes de IA para distribuidores latino-americanos.

Ele começa pelos pedidos que já chegam no WhatsApp e transforma conversa desestruturada em pedido validado, confirmado e criado no ERP.

Na demo, quatro agentes trabalham juntos:

- Order Intake Agent interpreta a conversa.
- Operational Memory Agent usa histórico, aliases e correções.
- Validation Agent consulta catálogo, preço e estoque.
- ERP Execution Agent cria o pedido aprovado no ERP simulado.

---

## 4. Roteiro falado

### 0:00 a 0:25

Somos o Opero. Eu sou o Pedro, focado em produto, comercial e front-end. O Enzo está no backend e no ERP Simulator. O Guilherme está nos agentes de IA. Somos três founders técnicos construindo para uma dor operacional real de distribuidores B2B.

### 0:25 a 1:05

Distribuidores recebem pedidos todos os dias pelo WhatsApp. O cliente escreve do jeito dele: apelido de produto, embalagem incompleta, referência ao último pedido e prazo de entrega. Hoje um operador precisa interpretar, conferir catálogo, preço e estoque, corrigir dúvida e redigitar no ERP. Isso cria fila, erro e limita o volume de vendas que a operação consegue processar.

### 1:05 a 2:45

O Opero coloca agentes de IA com papéis definidos para operar esse fluxo. O Order Intake Agent entende a mensagem. O Operational Memory Agent usa histórico e aliases. O Validation Agent consulta catálogo, preço e estoque. E o ERP Execution Agent cria o pedido depois da confirmação do cliente e da aprovação do operador.

Agora vamos mostrar funcionando. Entra uma mensagem: "Manda 10 caixas de Coca 2L, 6 fardos da Zero e 15 daquele óleo da última vez." O sistema estrutura os itens, recupera o óleo pelo histórico, identifica a ambiguidade na Coca Zero, pergunta ao cliente, recebe a confirmação, valida no ERP simulado e libera para aprovação humana. Depois da aprovação, o pedido é criado no ERP com recibo e logs auditáveis.

### 2:45 a 3:00

O Opero não é um chatbot. É uma camada operacional de agentes para distribuidores latino-americanos, começando pelos pedidos que já acontecem no WhatsApp e expandindo para outras partes da operação.

---

## 5. Ordem da demo

1. Abrir Order Operations já no estado inicial e apontar o health check.
2. Enviar a mensagem preparada do Mercado Boa Compra.
3. Mostrar a conversa original e os itens estruturados com evidência e confiança.
4. Mostrar memória resolvendo "óleo da última vez".
5. Mostrar validação bloqueando "fardo da zero".
6. Responder ao esclarecimento no chat.
7. Destacar a proposta de memória `pending_review`.
8. Confirmar como cliente e aprovar como operador.
9. Mostrar número externo, `Idempotency-Key` e payload no recibo.
10. Fechar o recibo e mostrar agentes, transições e tool calls na timeline.

---

## 6. Frases fortes

"O problema não é receber pedido no WhatsApp. O problema é transformar conversa em operação."

"Chatbot responde. Opero executa."

"O ERP continua sendo o system of record. O Opero é a camada que entende a conversa e prepara a execução."

"A métrica que importa é simples: mais pedidos por operador, com menos correção manual."

---

## 7. O que não falar

- Não gastar tempo explicando mercado demais.
- Não falar de features futuras antes da demo.
- Não dizer que substitui ERP.
- Não vender como chatbot.
- Não abrir discussão de WhatsApp real.
- Não prometer fornecedor, procurement ou crédito como parte do core do hackathon.

---

## 8. Fechamento

Opero is the AI operations layer for Latin American distributors, starting with the order workflows that already happen on WhatsApp.
