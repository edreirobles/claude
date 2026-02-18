# X → LinkedIn AI Publisher

Automatización que convierte un tweet en una publicación lista para LinkedIn, generada con IA (Claude), con soporte para publicar inmediatamente o programar para una hora específica.

---

## Funcionalidades

- **Extracción automática** de texto, imágenes y links del tweet (incluyendo papers académicos)
- **Generación con Claude AI** de posts LinkedIn profesionales en español o inglés
- **Estilo personalizado**: inicia siempre con una *category phrase* que captura la atención
- **Adjunta imágenes** directamente del tweet a LinkedIn
- **Publicación inmediata** con un clic
- **Programación** de posts para fecha y hora exactas
- **Historial** de publicaciones con estado en tiempo real

---

## Setup en 5 minutos

### Requisitos previos

1. **Python 3.10+** instalado
2. **Clave de Anthropic (Claude)** → [console.anthropic.com](https://console.anthropic.com)
3. **LinkedIn Developer App** → [linkedin.com/developers](https://www.linkedin.com/developers/)

### Configurar LinkedIn App

1. Ve a [linkedin.com/developers](https://www.linkedin.com/developers/) y crea una app
2. En **Products**, agrega:
   - `Share on LinkedIn`
   - `Sign In with LinkedIn using OpenID Connect`
3. En **Auth > Authorized redirect URLs**, agrega:
   ```
   http://localhost:8000/auth/linkedin/callback
   ```
4. Copia el **Client ID** y **Client Secret**

### Instalación

```bash
# 1. Clonar / descargar el proyecto
cd x-to-linkedin

# 2. Ejecutar setup automático
bash setup.sh

# 3. Editar .env con tus claves
nano .env
```

Contenido del `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-tu-clave-aqui
LINKEDIN_CLIENT_ID=tu-client-id
LINKEDIN_CLIENT_SECRET=tu-client-secret
LINKEDIN_REDIRECT_URI=http://localhost:8000/auth/linkedin/callback
```

### Iniciar

```bash
bash start.sh
```

Abre [http://localhost:8000](http://localhost:8000) en tu navegador.

---

## Uso

1. **Conecta LinkedIn** (botón en la esquina superior derecha)
2. **Pega un URL de X/Twitter** en el campo de texto
3. Haz clic en **"Generar post"** — Claude extrae el contenido y genera el post
4. **Revisa y edita** el texto generado (puedes modificarlo libremente)
5. **Selecciona la imagen** a adjuntar (o ninguna)
6. Elige:
   - **Publicar ahora** → se publica inmediatamente
   - **Programar** → elige fecha y hora, el sistema publica automáticamente

---

## Con Docker (alternativa)

```bash
cp .env.example .env
# Editar .env con tus claves
docker-compose up --build
```

---

## Estructura del proyecto

```
x-to-linkedin/
├── app/
│   ├── main.py                    # FastAPI app principal
│   ├── config.py                  # Configuración (variables de entorno)
│   ├── database.py                # SQLAlchemy + SQLite async
│   ├── models.py                  # Modelos de datos
│   ├── schemas.py                 # Schemas Pydantic (API)
│   ├── routers/
│   │   ├── posts.py               # Endpoints: generar, publicar, programar
│   │   └── auth.py                # OAuth 2.0 LinkedIn
│   └── services/
│       ├── x_scraper.py           # Extracción de tweets (playwright + oEmbed)
│       ├── post_generator.py      # Generación con Claude AI
│       ├── linkedin_client.py     # LinkedIn API v2
│       └── scheduler_service.py   # APScheduler para posts programados
├── static/
│   ├── index.html                 # UI principal
│   ├── css/style.css              # Estilos
│   └── js/app.js                  # Lógica frontend
├── .env.example                   # Plantilla de configuración
├── requirements.txt               # Dependencias Python
├── setup.sh                       # Script de instalación automática
├── start.sh                       # Script de inicio rápido
├── Dockerfile                     # Imagen Docker
└── docker-compose.yml             # Docker Compose
```
