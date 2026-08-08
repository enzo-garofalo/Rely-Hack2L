FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Invocado via `sh` para não depender do bit de execução, que não sobrevive
# a um checkout no Windows. O docker-compose local sobrescreve este CMD com
# `runserver`; aqui o default é o boot de produção.
CMD ["sh", "./start.sh"]
