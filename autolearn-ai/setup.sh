#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# AutoLearn AI — Setup automatizado
# Corre este script una sola vez para configurar todo.
# Uso: bash setup.sh
# ─────────────────────────────────────────────────────────────
set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}✓ $1${RESET}"; }
warn() { echo -e "${YELLOW}⚠ $1${RESET}"; }
step() { echo -e "\n${BOLD}── $1${RESET}"; }

echo -e "${BOLD}"
echo "  ╔══════════════════════════════════╗"
echo "  ║      AutoLearn AI — Setup        ║"
echo "  ╚══════════════════════════════════╝"
echo -e "${RESET}"

# ── 1. Check Node ──────────────────────────────────────────
step "Verificando Node.js"
if ! command -v node &> /dev/null; then
  echo -e "${RED}✗ Node.js no encontrado. Instala Node 20+${RESET}"
  exit 1
fi
NODE_VER=$(node -v)
ok "Node.js $NODE_VER"

# ── 2. Install deps ────────────────────────────────────────
step "Instalando dependencias"
npm install
ok "Dependencias instaladas"

# ── 3. Create .env.local ───────────────────────────────────
step "Configurando variables de entorno"

if [ -f ".env.local" ]; then
  warn ".env.local ya existe — saltando"
else
  cp .env.example .env.local
  ok "Creado .env.local desde .env.example"
fi

# ── 4. Check keys ──────────────────────────────────────────
step "Verificando API keys"

source .env.local 2>/dev/null || true

MISSING=0

check_key() {
  local name=$1
  local value=$2
  local url=$3
  if [ -z "$value" ] || [ "$value" = "${name}=..." ] || [[ "$value" == *"..."* ]]; then
    warn "$name no configurada → $url"
    MISSING=$((MISSING + 1))
  else
    ok "$name configurada"
  fi
}

check_key "ANTHROPIC_API_KEY"            "$ANTHROPIC_API_KEY"            "https://console.anthropic.com"
check_key "NEXT_PUBLIC_SUPABASE_URL"     "$NEXT_PUBLIC_SUPABASE_URL"     "https://supabase.com"
check_key "NEXT_PUBLIC_SUPABASE_ANON_KEY" "$NEXT_PUBLIC_SUPABASE_ANON_KEY" "https://supabase.com"
check_key "SUPABASE_SERVICE_ROLE_KEY"    "$SUPABASE_SERVICE_ROLE_KEY"    "https://supabase.com"

if [ $MISSING -gt 0 ]; then
  echo ""
  warn "$MISSING key(s) pendiente(s). La app correrá en MODO DEMO hasta que las configures."
  warn "Edita .env.local y vuelve a correr: npm run dev"
else
  ok "Todas las keys configuradas"
fi

# ── 5. Supabase schema ─────────────────────────────────────
step "Schema de Supabase"
if [ -n "$NEXT_PUBLIC_SUPABASE_URL" ] && [[ "$NEXT_PUBLIC_SUPABASE_URL" != *"..."* ]]; then
  echo "Para aplicar el schema, corre este comando una vez:"
  echo ""
  echo "  npx supabase db push --db-url \$SUPABASE_DB_URL"
  echo ""
  echo "O pega el contenido de supabase/schema.sql en:"
  echo "  $NEXT_PUBLIC_SUPABASE_URL/project/default/sql/new"
else
  warn "Configura NEXT_PUBLIC_SUPABASE_URL primero"
fi

# ── 6. Deploy to Vercel ────────────────────────────────────
step "Deploy a Vercel"
if command -v vercel &> /dev/null || npx vercel --version &> /dev/null 2>&1; then
  echo "Para hacer deploy, corre:"
  echo ""
  echo "  npx vercel --prod"
  echo ""
  echo "Luego agrega las mismas variables de .env.local en:"
  echo "  vercel.com → tu proyecto → Settings → Environment Variables"
else
  warn "Vercel CLI no disponible. Instala con: npm i -g vercel"
fi

# ── Done ───────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════${RESET}"
if [ $MISSING -gt 0 ]; then
  echo -e "${YELLOW}${BOLD}  App lista en MODO DEMO${RESET}"
  echo -e "  Corre: ${BOLD}npm run dev${RESET}"
else
  echo -e "${GREEN}${BOLD}  Todo listo para producción${RESET}"
  echo -e "  Corre: ${BOLD}npm run dev${RESET}"
fi
echo -e "${GREEN}${BOLD}══════════════════════════════════════${RESET}"
echo ""
