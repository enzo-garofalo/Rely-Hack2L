#!/bin/sh
# Boot de produção (Railway). Diferente do docker-compose local, aqui não há
# `docker-compose exec` pra rodar migrate/seed na mão: cada deploy precisa
# chegar sozinho no mesmo estado que a demo espera.
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# seed_demo é idempotente (update_or_create) e roda a cada deploy de
# propósito: garante que o dataset congelado existe mesmo em banco novo,
# e devolve o cenário ao ponto inicial depois de um redeploy.
python manage.py seed_demo

exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${WEB_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile -
