"""WhatsApp real (E10, enhancement): transporte entre o Django e o
gateway Node (`whatsapp-gateway/`, whatsapp-web.js).

Este módulo é a BORDA do sistema, no mesmo espírito de `voice.py` (E9):
só sabe falar HTTP com o gateway e traduzir falha de rede em dado. Ele
não conhece pedido, agente, estado nem regra de negócio — quem decide o
que dizer e quando é `order_service.py`.

Guardrails deste módulo:
- O token compartilhado com o gateway só existe aqui e no gateway, via
  variável de ambiente — nunca no frontend (guardrail #8 do CLAUDE.md).
- Nenhuma exceção de rede escapa: tudo vira `WhatsAppGatewayError`, para
  que o chamador trate como dado. O gateway cair NUNCA pode derrubar a
  jornada — o chat simulado é o fallback obrigatório da demo.
- A falha de entrega é gravada na própria `Message` (`delivery_status`/
  `delivery_error`), não engolida: "falha nunca vira sucesso por
  inferência" (guardrail #7) vale também pro transporte.
- Timeout curto e sem retry: numa demo ao vivo é melhor registrar
  "failed" rápido do que segurar a request do operador esperando o
  Chromium do gateway voltar.
"""

from __future__ import annotations

import logging
import os
import re

import requests
from django.db import transaction

from .models import Conversation, Message

logger = logging.getLogger(__name__)

# URL do gateway vista de dentro da rede do compose (Django -> gateway).
WHATSAPP_GATEWAY_URL = os.environ.get("WHATSAPP_GATEWAY_URL", "http://whatsapp-gateway:3001")
WHATSAPP_GATEWAY_TOKEN = os.environ.get("WHATSAPP_GATEWAY_TOKEN", "")
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("WHATSAPP_GATEWAY_TIMEOUT_SECONDS", "10"))


class WhatsAppGatewayError(Exception):
    """Falha tratável de transporte (gateway fora do ar, sem sessão do
    WhatsApp, número inexistente, timeout). Quem chama decide o que fazer
    — na prática, registrar em `Message.delivery_status=failed` e seguir:
    o pedido em si não depende do canal real."""


def is_configured() -> bool:
    """Só há canal real se existir token compartilhado. Sem isso o Django
    nem tenta chamar o gateway (e o `/api/whatsapp/inbound` recusa tudo):
    um gateway sem autenticação seria um endpoint aberto criando pedidos
    em nome de qualquer telefone."""

    return bool(WHATSAPP_GATEWAY_TOKEN)


def normalize_phone(raw: str) -> str:
    """Só os dígitos. O WhatsApp entrega o remetente como
    `5511999990001@c.us`, o seed grava `551199999000X` e uma pessoa
    digita `+55 (11) 99999-0001` — normalizar aqui evita espalhar essa
    bagunça pelo resto do código."""

    return re.sub(r"\D", "", raw or "")


def send_text(phone: str, text: str) -> dict:
    """POST {gateway}/send — pede ao gateway que mande `text` para
    `phone` pelo WhatsApp real. Levanta `WhatsAppGatewayError` em
    qualquer falha; nunca deixa vazar exceção crua do `requests`."""

    if not is_configured():
        raise WhatsAppGatewayError(
            "WHATSAPP_GATEWAY_TOKEN não configurado — canal WhatsApp real desligado."
        )
    if not normalize_phone(phone):
        raise WhatsAppGatewayError("telefone vazio — não há para quem enviar")
    if not text.strip():
        raise WhatsAppGatewayError("texto vazio — nada para enviar")

    try:
        response = requests.post(
            f"{WHATSAPP_GATEWAY_URL}/send",
            headers={"X-Gateway-Token": WHATSAPP_GATEWAY_TOKEN},
            json={"phone": normalize_phone(phone), "text": text},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WhatsAppGatewayError(f"falha ao enviar mensagem pelo gateway: {exc}") from exc

    try:
        return response.json()
    except ValueError:
        # O envio deu 2xx; corpo estranho não invalida a entrega.
        return {}


def deliver(message: Message) -> None:
    """Entrega uma mensagem de saída pelo canal da conversa e registra o
    resultado na própria linha. Conversa simulada não tem transporte
    externo — a "entrega" é a API devolver o estado pro console — então
    fica em `not_applicable` e nada é chamado."""

    conversation = message.conversation
    if conversation.source != Conversation.Source.WHATSAPP_WEB:
        return

    phone = conversation.customer.phone
    try:
        send_text(phone, message.content)
    except WhatsAppGatewayError as exc:
        # Só log + estado; propagar aqui derrubaria a request do operador
        # por causa de um canal que é enhancement (o pedido já está no ERP).
        logger.warning("Message #%s não entregue pelo WhatsApp: %s", message.pk, exc)
        message.delivery_status = Message.DeliveryStatus.FAILED
        message.delivery_error = str(exc)
    else:
        message.delivery_status = Message.DeliveryStatus.SENT
        message.delivery_error = ""

    message.save(update_fields=["delivery_status", "delivery_error"])


def deliver_on_commit(message: Message) -> None:
    """Agenda a entrega para depois do commit da transação atual.

    Chamada HTTP dentro de `transaction.atomic` é armadilha: o gateway
    demorando segura a transação aberta, e um rollback depois do envio
    deixaria o cliente com uma mensagem sobre um pedido que não existe.
    `on_commit` resolve os dois — e, fora de transação, o Django executa
    o callback na hora."""

    transaction.on_commit(lambda: deliver(message))
