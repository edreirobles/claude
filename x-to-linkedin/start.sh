#!/usr/bin/env bash
# ═══════════════════════════════════════════
# X → LinkedIn AI Publisher — Inicio rápido
# ═══════════════════════════════════════════
set -e

# Activar entorno virtual si existe
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Verificar .env
if [ ! -f ".env" ]; then
    echo "Error: No existe el archivo .env. Ejecuta primero: bash setup.sh"
    exit 1
fi

echo ""
echo "═══════════════════════════════════════"
echo "  X → LinkedIn AI Publisher"
echo "  http://localhost:8000"
echo "═══════════════════════════════════════"
echo ""

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
