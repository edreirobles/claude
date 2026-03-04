#!/bin/bash
# Instala dependencias y arranca el SaaS en modo desarrollo

cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "⚠️  Se creó .env desde .env.example. Edítalo antes de continuar."
fi

pip install -r requirements.txt -q

uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
