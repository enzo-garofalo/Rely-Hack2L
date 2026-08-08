"""Sanitização básica de auditoria (E8, RF38 "saída sanitizada" / RNF05).

A superfície real de vazamento aqui é pequena de propósito: `tools.py`
fala com o ERP simulado via ORM direto, não HTTP (ver nota em tools.py),
então nenhum header/credencial passa pelas tool calls. O único vetor
plausível é o texto de erro de uma chamada ao LLM (`llm_client.py`) — um
cliente OpenAI-compatible às vezes ecoa parte da API key numa mensagem de
autenticação falhada. Por isso a sanitização aqui é literal: substituir
qualquer ocorrência exata de um segredo conhecido (lido do ambiente, nunca
hardcoded) por um marcador, recursivamente em texto/dict/list — "básica"
de propósito, não um scanner de PII.
"""

from __future__ import annotations

import os

_REDACTED = "***REDACTED***"

# Nomes das env vars de segredo conhecidas neste projeto (CLAUDE.md,
# guardrail #8: "segredos só no backend"). Ler o valor aqui, nunca
# hardcoded, para que girar uma chave não exija tocar neste arquivo.
_SECRET_ENV_VARS = (
    "FEATHERLESS_API_KEY",
    "ERP_API_KEY",
    "ELEVENLABS_API_KEY",
    "DJANGO_SECRET_KEY",
)


def _secret_values() -> list[str]:
    values = (os.environ.get(name) for name in _SECRET_ENV_VARS)
    return [v for v in values if v]


def sanitize_text(text: str) -> str:
    for secret in _secret_values():
        if secret in text:
            text = text.replace(secret, _REDACTED)
    return text


def sanitize(value):
    """Aplica `sanitize_text` recursivamente em str/dict/list. É o que
    `tools.py` (ToolCall) e `audit.py` (AgentRun) chamam antes de gravar
    qualquer coisa na auditoria — o único ponto de escrita de cada um."""

    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {key: sanitize(val) for key, val in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value
