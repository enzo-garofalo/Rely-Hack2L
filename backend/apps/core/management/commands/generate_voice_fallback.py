"""Gera o áudio de fallback pra demo (E9, RNF09): "existe um áudio
pré-gravado e sua transcrição esperada, caso a ElevenLabs falhe ao vivo".

Isto é um comando, não um arquivo binário fixo no repo, porque não dá pra
fabricar um áudio real sem chamar a ElevenLabs de verdade — rode uma vez,
com ELEVENLABS_API_KEY configurada, antes da apresentação:

    python manage.py generate_voice_fallback

O resultado (áudio + transcrição esperada) fica em
apps/core/fixtures/voice_fallback/. Isto NÃO é servido automaticamente
pela API — é um recurso manual para quem apresenta: se a ElevenLabs cair
ao vivo, jogue esse .mp3 na entrada de áudio da demo (ou faça upload dele
em POST /api/orders/ingest-audio) em vez de gravar na hora. Deixar isso
automático e silencioso no backend violaria o guardrail #7 do CLAUDE.md
("falha nunca vira sucesso por inferência") — o áudio de fallback é sobre
salvar a demo, não sobre esconder que a ElevenLabs falhou.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core import voice

FALLBACK_DIR = Path(settings.BASE_DIR) / "apps" / "core" / "fixtures" / "voice_fallback"


class Command(BaseCommand):
    help = "Gera o áudio de fallback (RNF09) a partir de VOICE_FALLBACK_TEXT, usando a ElevenLabs de verdade."

    def handle(self, *args, **options):
        text = os.environ.get("VOICE_FALLBACK_TEXT")
        if not text:
            raise CommandError("VOICE_FALLBACK_TEXT não configurada — defina no .env antes de rodar.")

        try:
            audio_bytes = voice.synthesize(text)
        except voice.VoiceError as exc:
            raise CommandError(f"falha ao gerar o áudio de fallback: {exc}")

        FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        audio_path = FALLBACK_DIR / "fallback.mp3"
        text_path = FALLBACK_DIR / "fallback.txt"
        audio_path.write_bytes(audio_bytes)
        text_path.write_text(text, encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(f"Fallback gerado: {audio_path} (transcrição esperada em {text_path})")
        )
