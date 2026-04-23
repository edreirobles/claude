# X -> LinkedIn AI Publisher

Aplicacion FastAPI para convertir contenido de X en publicaciones de LinkedIn, publicarlas o programarlas, medir su desempeno y automatizar parte del flujo desde likes en X y Telegram.

## Lo Que Hace Hoy

- Extrae texto, imagenes, links, videos, PDFs y articulos largos de X.
- Genera copy para LinkedIn con Claude en espanol o ingles.
- Permite publicar de inmediato o programar al siguiente slot disponible.
- Adjunta imagen, video, documento PDF o una imagen generada con IA.
- Guarda historial, exporta CSV y muestra metricas de LinkedIn.
- Monitorea likes en X usando cookies de sesion del navegador y crea posts `x_auto`.
- Expone un bot de Telegram para generar, editar, programar y revisar posts.

## Stack

- Backend: FastAPI + SQLAlchemy async + SQLite
- Scheduler: APScheduler
- IA: Anthropic Claude + Google Imagen/Gemini + fallbacks
- Scraping: Playwright + HTTP scraping
- Frontend: HTML/CSS/JS estatico
- Bot: python-telegram-bot

## Requisitos

- Python 3.10+
- Chromium para Playwright
- Credenciales de Anthropic
- App de LinkedIn con OAuth habilitado

## Variables De Entorno

Existe un archivo de ejemplo en `.env.example`.

Variables clave:

- `ANTHROPIC_API_KEY`: obligatoria para generar el copy.
- `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_REDIRECT_URI`: obligatorias para conectar LinkedIn.
- `DATABASE_URL`: base principal de la app.
- `SCHEDULER_DATABASE_URL`: base de APScheduler.
- `GOOGLE_API_KEY`: opcional para generacion de imagenes.
- `LINKEDIN_LI_AT`, `LINKEDIN_JSESSIONID`: opcionales para scraping de metricas via Voyager.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID`: opcionales para el bot.
- `X_USERNAME`, `X_AUTH_TOKEN`, `X_CT0`: opcionales para el monitor de likes en X.
- `X_MONITOR_START_DATE`: opcional, formato `YYYY-MM-DDTHH:MM:SS` en hora de Monterrey.

## Setup Rapido

1. Crea el archivo de entorno:

```bash
cp .env.example .env
```

2. Instala dependencias:

```bash
pip install -r requirements.txt
playwright install chromium
```

3. Configura tu app de LinkedIn:

- En [LinkedIn Developers](https://www.linkedin.com/developers/), crea una app.
- Agrega `Share on LinkedIn`.
- Agrega `Sign In with LinkedIn using OpenID Connect`.
- Configura este redirect URL:

```text
http://localhost:8000/auth/linkedin/callback
```

4. Inicia la aplicacion:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Tambien puedes usar `start.sh` en entornos con Bash.

## Uso Desde La Web

1. Conecta LinkedIn.
2. Pega un URL de tweet de X.
3. Genera el post con IA.
4. Edita el copy si hace falta.
5. Elige publicar ahora o programar.

La programacion actual funciona por slots: el backend asigna automaticamente el proximo horario disponible a las `5:00 AM` o `4:00 PM` hora de CDMX/Monterrey.

## Automatizacion De Likes En X

El monitor no usa la API paga de X. Usa cookies de sesion del navegador:

1. Inicia sesion en `x.com`.
2. Abre DevTools.
3. Ve a `Application -> Cookies -> x.com`.
4. Copia `auth_token` y `ct0`.
5. Configura en `.env`:

```env
X_USERNAME=tu_handle_sin_arroba
X_AUTH_TOKEN=tu_cookie_auth_token
X_CT0=tu_cookie_ct0
X_MONITOR_START_DATE=2026-03-02T00:00:00
```

Cuando esta activo:

- revisa likes cada `X_CHECK_INTERVAL_MINUTES`
- hace una semilla inicial para no procesar likes antiguos
- genera posts `x_auto`
- los acomoda en slots consecutivos

## Bot De Telegram

Si configuras `TELEGRAM_BOT_TOKEN` y `TELEGRAM_USER_ID`, el bot arranca junto con la app y te permite:

- enviar tweets o articulos web para generar posts
- editar previews antes de publicar
- programar o publicar al instante
- ver `/hoy`, `/pendientes`, `/status` y `/articulos`
- recibir notificaciones antes de publicar y al completar/fallar publicaciones

## Metricas De LinkedIn

La app soporta dos estrategias:

- API publica de LinkedIn cuando el token tiene `r_member_social`
- scraping via Voyager con `LINKEDIN_LI_AT` y `LINKEDIN_JSESSIONID`

Con eso el dashboard muestra likes, comentarios, impresiones, clicks, shares y top posts.

## Docker

El compose monta la base principal y la base del scheduler dentro de `./data`:

```bash
cp .env.example .env
docker-compose up --build
```

## Estructura

```text
x-to-linkedin/
|-- app/
|   |-- main.py
|   |-- config.py
|   |-- database.py
|   |-- models.py
|   |-- schemas.py
|   |-- routers/
|   |   |-- auth.py
|   |   |-- posts.py
|   |   |-- x_monitor.py
|   |   `-- admin.py
|   `-- services/
|       |-- linkedin_client.py
|       |-- linkedin_scraper.py
|       |-- post_generator.py
|       |-- scheduler_service.py
|       |-- telegram_bot.py
|       |-- url_scraper.py
|       |-- x_likes_monitor.py
|       `-- x_scraper.py
|-- static/
|   |-- index.html
|   |-- css/style.css
|   `-- js/app.js
|-- .env.example
|-- docker-compose.yml
|-- Dockerfile
|-- import_csv.py
|-- requirements.txt
|-- setup.sh
`-- start.sh
```
