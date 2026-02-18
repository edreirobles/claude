#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
# X → LinkedIn AI Publisher — Setup Automático
# ═══════════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log()     { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
info()    { echo -e "${BLUE}[i]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }
header()  { echo -e "\n${BLUE}═══ $1 ═══${NC}\n"; }

header "X → LinkedIn AI Publisher — Setup"

# ─── Verificar Python ──────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    error "Python 3 no está instalado. Instálalo desde https://python3.org"
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python encontrado: $PYTHON_VERSION"

if python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
    log "Python >= 3.10 OK"
else
    error "Se requiere Python 3.10 o superior. Versión actual: $PYTHON_VERSION"
fi

# ─── Entorno virtual ───────────────────────────────────────
header "Entorno Virtual"

if [ ! -d "venv" ]; then
    info "Creando entorno virtual..."
    python3 -m venv venv
    log "Entorno virtual creado"
else
    info "Entorno virtual ya existe"
fi

# Activar
source venv/bin/activate
log "Entorno virtual activado"

# ─── Instalar dependencias ─────────────────────────────────
header "Instalando Dependencias"

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
log "Dependencias Python instaladas"

# ─── Playwright (Chromium) ─────────────────────────────────
header "Instalando Chromium para scraping"
playwright install chromium
log "Chromium instalado"

# ─── Configuración .env ────────────────────────────────────
header "Configuración"

if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env creado desde .env.example"
    echo ""
    echo -e "${YELLOW}IMPORTANTE: Debes editar el archivo .env con tus claves:${NC}"
    echo ""
    echo "  1. ANTHROPIC_API_KEY"
    echo "     → Obtén tu clave en: https://console.anthropic.com"
    echo ""
    echo "  2. LINKEDIN_CLIENT_ID y LINKEDIN_CLIENT_SECRET"
    echo "     → Crea una app en: https://www.linkedin.com/developers/"
    echo "     → Agrega los productos: 'Share on LinkedIn' y 'Sign In with LinkedIn using OpenID Connect'"
    echo "     → Redirect URI: http://localhost:8000/auth/linkedin/callback"
    echo ""
    echo -e "${YELLOW}Edita el archivo .env antes de continuar:${NC}"
    echo "  nano .env  (o usa tu editor favorito)"
    echo ""
    read -p "Presiona ENTER cuando hayas configurado el .env..."
else
    log ".env ya existe"
fi

# ─── Verificar .env básico ─────────────────────────────────
if grep -q "sk-ant-xxx" .env || grep -q "ANTHROPIC_API_KEY=sk-ant-xxx" .env 2>/dev/null; then
    warn "⚠ ANTHROPIC_API_KEY no ha sido configurada en .env"
fi

# ─── Listo ─────────────────────────────────────────────────
header "¡Setup Completado!"

echo -e "${GREEN}Para iniciar la aplicación:${NC}"
echo ""
echo "  source venv/bin/activate"
echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo ""
echo -e "  Luego abre: ${BLUE}http://localhost:8000${NC}"
echo ""
echo -e "${GREEN}O usa el script de inicio:${NC}"
echo "  ./start.sh"
echo ""
