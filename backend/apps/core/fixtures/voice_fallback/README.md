# Áudio de fallback (E9, RNF09)

Backup manual para a demo ao vivo, caso a ElevenLabs falhe ou fique lenta
durante a apresentação. Não é servido automaticamente por nenhum endpoint —
é para quem está apresentando usar na hora, substituindo a gravação ao
vivo por este arquivo.

## Gerar

Precisa de `ELEVENLABS_API_KEY` configurada de verdade no `.env`:

```bash
docker-compose exec backend python manage.py generate_voice_fallback
```

Isso cria, a partir do texto em `VOICE_FALLBACK_TEXT` (`.env.example`):

- `fallback.mp3` — o áudio gerado pela ElevenLabs.
- `fallback.txt` — a transcrição esperada (o texto exato que virou áudio).

## Usar na demo

Se a ElevenLabs cair ao vivo:

1. Em vez de gravar, faça upload de `fallback.mp3` em
   `POST /api/orders/ingest-audio` (campo `audio`).
2. Se a própria transcrição falhar também, cole o conteúdo de
   `fallback.txt` direto em `POST /api/orders/ingest` (campo `message`) —
   a jornada continua idêntica, por texto (RF47).

Os dois arquivos não são versionados no git (binário gerado, não
código-fonte) — gere localmente antes de cada apresentação.
