"""Voz (E9, enhancement): ElevenLabs STT (Scribe) + TTS, isolado do
pipeline de texto (CLAUDE.md, "Voz (enhancement)": "transcreva com a
ElevenLabs e alimente o mesmo pipeline de texto — não crie um fluxo
paralelo"). Só duas responsabilidades aqui: `transcribe` e `synthesize`.

Guardrails deste módulo:
- A API key só é lida daqui, via variável de ambiente (RF50/CLAUDE.md
  guardrail #8: "segredos só no backend" — nunca no frontend).
- Nenhuma das duas funções deixa uma exceção de rede/timeout escapar:
  ambas levantam `VoiceError` (nunca `requests.RequestException` crua),
  para que o chamador trate isso como um dado, não como uma falha do
  processo (RNF08: falha da ElevenLabs cai pra texto sem quebrar o
  fluxo — mas só dá pra "cair pra texto" se o erro for capturável).
- Timeout curto (`ELEVENLABS_TIMEOUT_SECONDS`), sem retry automático: numa
  demo ao vivo, é melhor falhar rápido e cair pro fallback de texto do
  que travar a UI esperando uma segunda tentativa.

Endpoints (confirmados na doc oficial em 2026-08; a API muda com
frequência — reconfira antes de reusar isto em outro contexto):
- POST {base}/v1/speech-to-text (multipart: file + model_id)
  https://elevenlabs.io/docs/api-reference/speech-to-text/convert
- POST {base}/v1/text-to-speech/{voice_id} (json: text + model_id)
  https://elevenlabs.io/docs/api-reference/text-to-speech/convert
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_BASE_URL = os.environ.get("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io")

# Modelo/voz configuráveis via env (mesmo padrão de agents/llm_client.py
# pros MODEL_* dos agentes): girar de modelo/voz é mudar o .env, não o
# código. Defaults são os valores atuais da doc oficial (scribe_v2 pro
# STT; eleven_flash_v2_5 é o modelo TTS multilíngue de menor latência,
# adequado pra uma demo ao vivo respondendo em pt-BR).
ELEVENLABS_STT_MODEL = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2")
ELEVENLABS_TTS_MODEL = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("ELEVENLABS_TIMEOUT_SECONDS", "20"))


class VoiceError(Exception):
    """Erro tratável de STT/TTS. Quem chama decide o fallback (RNF08) —
    por isso isto é uma exceção prevista e documentada, nunca deixada
    escapar como um erro genérico de rede."""


@dataclass
class TranscriptionResult:
    """Saída de `transcribe`. Um `str` puro não bastaria: RF46/RF47
    exigem tratar transcrição "claramente errada"/de baixa confiança sem
    quebrar o fluxo, e a única confiança que a Scribe devolve pro texto
    inteiro é `language_probability` — por isso ela viaja junto, não é
    inventada aqui."""

    text: str
    languageCode: str | None = None
    languageProbability: float | None = None


def transcribe(audio_bytes: bytes, mimetype: str) -> TranscriptionResult:
    """POST /v1/speech-to-text (ElevenLabs Scribe). Levanta `VoiceError`
    em qualquer falha (sem API key, rede, timeout, resposta não-2xx ou
    corpo inesperado) — nunca deixa a exceção original do `requests`
    escapar pro chamador."""

    if not ELEVENLABS_API_KEY:
        raise VoiceError("ELEVENLABS_API_KEY não configurada — defina no .env do backend.")
    if not audio_bytes:
        raise VoiceError("áudio vazio — nada para transcrever")

    try:
        response = requests.post(
            f"{ELEVENLABS_BASE_URL}/v1/speech-to-text",
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            data={"model_id": ELEVENLABS_STT_MODEL},
            files={"file": ("audio", audio_bytes, mimetype or "application/octet-stream")},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise VoiceError(f"falha ao transcrever áudio via ElevenLabs: {exc}") from exc

    try:
        payload = response.json()
        text = payload["text"]
    except (ValueError, KeyError) as exc:
        raise VoiceError(f"resposta inesperada da ElevenLabs (speech-to-text): {exc}") from exc

    return TranscriptionResult(
        text=text,
        languageCode=payload.get("language_code"),
        languageProbability=payload.get("language_probability"),
    )


def synthesize(text: str) -> bytes:
    """POST /v1/text-to-speech/{voice_id} (ElevenLabs TTS). Devolve o
    áudio (mp3) em bytes. Levanta `VoiceError` em qualquer falha — a
    resposta em áudio é sempre opcional (RF49); quem chama decide seguir
    só com o texto, que já existia antes desta chamada."""

    if not ELEVENLABS_API_KEY:
        raise VoiceError("ELEVENLABS_API_KEY não configurada — defina no .env do backend.")
    if not text.strip():
        raise VoiceError("texto vazio — nada para sintetizar")

    try:
        response = requests.post(
            f"{ELEVENLABS_BASE_URL}/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={"text": text, "model_id": ELEVENLABS_TTS_MODEL},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise VoiceError(f"falha ao sintetizar áudio via ElevenLabs: {exc}") from exc

    return response.content
