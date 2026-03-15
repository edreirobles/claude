#!/bin/bash
set -e

cd "$(dirname "$0")"

# Check for .env
if [ ! -f .env ]; then
  echo "⚠️  No .env file found."
  echo "   Copy .env.example to .env and add your ANTHROPIC_API_KEY:"
  echo "   cp .env.example .env"
  exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
  echo "❌ Python 3 is required but not found."
  exit 1
fi

# Create virtual environment if needed
if [ ! -d ".venv" ]; then
  echo "📦 Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "📦 Installing dependencies..."
pip install -q -r requirements.txt

# Create required directories
mkdir -p uploads outputs

echo ""
echo "✅ CV Matcher is starting..."
echo "   Open http://localhost:8000 in your browser"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
