"""Camada de modelo (Featherless) — o único lugar que fala com o LLM.

Featherless é o provedor de inferência, API OpenAI-compatible (AGENTS_PLAN.md,
seção "Camada de modelo"). Este wrapper decide COMO chamar o modelo (tool
calling forçado, temperatura baixa, timeout, retry curto) e devolve um
objeto Pydantic já validado — nunca texto solto. O QUE perguntar (prompt,
schema de saída) é decisão de cada agente (intake.py, memory.py, etc.), não
deste módulo.

`load_dotenv()` já roda em config/settings.py antes de qualquer app carregar,
então aqui só lemos `os.environ` — sem chamar load_dotenv de novo.
"""

from __future__ import annotations

import logging
import os
from typing import TypeVar

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel, ValidationError

from .schemas import AgentName

logger = logging.getLogger(__name__)

# Base URL fixa do provedor primário do desafio. Trocar de provedor —
# guardrail de fallback do AGENTS_PLAN.md — é trocar esta linha (+ o
# modelo), nunca reescrever os agentes.
FEATHERLESS_BASE_URL = os.environ.get("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")
FEATHERLESS_API_KEY = os.environ.get("FEATHERLESS_API_KEY")

# Temperatura baixa e timeout curto por padrão: agentes aqui não são um
# chat criativo, são uma etapa determinística de pipeline que só usa LLM
# pra interpretar/estruturar (CLAUDE.md, "Convenções de código").
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TIMEOUT_SECONDS = 20.0

# Cada agente escolhe seu modelo Featherless via variável de ambiente, não
# hardcoded aqui. Isso é proposital: o AGENTS_PLAN.md pede pra testar 2
# modelos por agente e ficar com o que devolve tool call mais confiável
# (tabela "Qual modelo por agente") — o time decide o valor, o código só
# consome. Também é o que torna o fallback de última hora (um agente
# isolado pra outro modelo) uma mudança de env var, não de código.
_AGENT_MODEL_ENV_VAR: dict[AgentName, str] = {
    AgentName.ORDER_INTAKE: "MODEL_ORDER_INTAKE",
    AgentName.OPERATIONAL_MEMORY: "MODEL_OPERATIONAL_MEMORY",
    AgentName.VALIDATION: "MODEL_VALIDATION",
    AgentName.ERP_EXECUTION: "MODEL_ERP_EXECUTION",
}

T = TypeVar("T", bound=BaseModel)


class LLMOutputError(Exception):
    """O modelo não devolveu algo que valide contra o schema esperado, nem
    depois do retry. Quem chama `call_structured` deve tratar isto como
    falha do agente (AgentResult com status=ERROR) — nunca capturar e
    seguir em frente com um valor inventado (guardrail #7 do CLAUDE.md:
    falha nunca vira sucesso por inferência)."""


def get_model_for_agent(agent: AgentName) -> str:
    """Lê qual modelo Featherless usar para este agente. Falha alto e
    explícito se a env var não foi configurada — melhor quebrar no boot
    do que descobrir em produção (ou pior, na demo) que caiu num modelo
    default que ninguém escolheu."""

    env_var = _AGENT_MODEL_ENV_VAR[agent]
    model = os.environ.get(env_var)
    if not model:
        raise RuntimeError(
            f"Variável de ambiente {env_var} não configurada. Defina o modelo "
            f"Featherless escolhido para '{agent.value}' (ver AGENTS_PLAN.md, "
            "tabela 'Qual modelo por agente')."
        )
    return model


def get_client() -> OpenAI:
    """Cliente OpenAI apontado pro Featherless. Criado por chamada (não é
    singleton global) porque é barato e evita compartilhar estado entre
    testes/threads — não é um recurso caro tipo conexão de banco."""

    if not FEATHERLESS_API_KEY:
        raise RuntimeError("FEATHERLESS_API_KEY não configurada — defina no .env do backend.")
    return OpenAI(
        base_url=FEATHERLESS_BASE_URL,
        api_key=FEATHERLESS_API_KEY,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )


def _schema_as_tool(output_schema: type[T]) -> dict:
    """Descreve `output_schema` como uma tool OpenAI-compatible. Forçamos
    tool calling em vez de `response_format=json_object` porque modelos
    open às vezes escapam do response_format (AGENTS_PLAN.md, seção
    "Structured output em modelo open") — tool calling é mais confiável
    pra arrancar JSON no formato exato que a gente precisa."""

    return {
        "type": "function",
        "function": {
            "name": output_schema.__name__,
            "description": f"Devolve a saída estruturada no formato {output_schema.__name__}.",
            "parameters": output_schema.model_json_schema(),
        },
    }


def call_structured(
    *,
    agent: AgentName,
    messages: list[dict],
    output_schema: type[T],
    temperature: float = DEFAULT_TEMPERATURE,
    max_retries: int = 1,
) -> T:
    """Chama o modelo do `agent` forçando tool calling contra
    `output_schema` e devolve uma instância já validada.

    Guardrail (AGENTS_PLAN.md, "Structured output em modelo open"): não
    confiamos que vem JSON limpo de primeira. Por isso o retry é curto e
    embutido aqui — cada agente chama esta função uma vez e recebe ou um
    objeto válido, ou uma `LLMOutputError` explícita. Não há um terceiro
    caminho onde o agente recebe algo "mais ou menos" válido.
    """

    client = get_client()
    model = get_model_for_agent(agent)
    tool = _schema_as_tool(output_schema)
    tool_name = output_schema.__name__

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[tool],
                # "required" (forma genérica do padrão OpenAI) em vez do
                # tool_choice aninhado por nome de função: como só passamos
                # uma tool, o efeito é o mesmo (força essa tool a ser
                # chamada), mas "required" tem mais chance de ser suportado
                # por qualquer modelo/backend atrás do Featherless. Ainda
                # assim, teste contra o modelo real escolhido antes da demo
                # (AGENTS_PLAN.md: "teste 2 modelos por agente").
                tool_choice="required",
                temperature=temperature,
            )
            tool_calls = response.choices[0].message.tool_calls
            if not tool_calls:
                raise LLMOutputError(f"modelo {model} respondeu sem tool call (esperava {tool_name}).")
            raw_arguments = tool_calls[0].function.arguments
            return output_schema.model_validate_json(raw_arguments)
        except (APIError, APITimeoutError, ValidationError, LLMOutputError) as exc:
            last_error = exc
            logger.warning(
                "call_structured: tentativa %s/%s falhou para agent=%s model=%s: %s",
                attempt,
                max_retries + 1,
                agent.value,
                model,
                exc,
            )

    raise LLMOutputError(
        f"agent={agent.value} model={model} não devolveu {tool_name} válido "
        f"após {max_retries + 1} tentativa(s): {last_error}"
    )
