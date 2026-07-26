# X -> LinkedIn AI Publisher

Aplicacion FastAPI para convertir fuentes de IA en publicaciones de LinkedIn, medir su desempeno y operar un flujo diario tipo radar con aprobacion por Telegram.

## Lo Que Hace Hoy

- Extrae texto, imagenes, links, videos, PDFs y articulos largos de X.
- Genera copy para LinkedIn con Anthropic o OpenAI en espanol o ingles.
- Permite publicar de inmediato o programar al siguiente slot disponible.
- Adjunta imagen, video o documento PDF cuando la fuente lo trae. Si no hay media real, publica sin adjunto.
- Crea slots diarios de radar, aprende de las publicaciones historicas con mejor desempeno, busca fuentes frescas 48 horas antes y pide aprobacion por Telegram 60 minutos antes. La aprobacion queda abierta sin vencimiento y, cuando apruebas, se publica 30 minutos despues.
- Guarda historial, exporta CSV y muestra metricas de LinkedIn.
- Puede monitorear likes en X usando cookies de sesion del navegador, pero la autocalendarizacion queda desactivada por defecto.
- Expone un bot de Telegram para generar, editar, programar y revisar posts.

## Stack

- Backend: FastAPI + SQLAlchemy async + SQLite
- Scheduler: APScheduler
- IA: Anthropic u OpenAI para texto
- Scraping: Playwright + HTTP scraping
- Frontend: HTML/CSS/JS estatico
- Bot: python-telegram-bot

## Requisitos

- Python 3.10+
- Node.js 22+ para la implementacion cloud
- Chromium para Playwright
- Credenciales de Anthropic u OpenAI para texto
- App de LinkedIn con OAuth habilitado

## Variables De Entorno

Existe un archivo de ejemplo en `.env.example`.

Variables clave:

- `TEXT_GENERATION_PROVIDER`: `anthropic` u `openai`.
- `ANTHROPIC_API_KEY`: obligatoria si `TEXT_GENERATION_PROVIDER=anthropic`.
- `ANTHROPIC_TEXT_MODEL`: opcional, default `claude-opus-4-6`.
- `OPENAI_API_KEY`: obligatoria si `TEXT_GENERATION_PROVIDER=openai`.
- `OPENAI_TEXT_MODEL`: opcional, default `gpt-5-mini`.
- `OPENAI_REASONING_EFFORT`: opcional, default `minimal`.
- `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_REDIRECT_URI`: obligatorias para conectar LinkedIn.
- `DATABASE_URL`: base principal de la app.
- `SCHEDULER_DATABASE_URL`: base de APScheduler.
- `EDITORIAL_RADAR_ENABLED`: activa el radar diario, default `true`.
- `EDITORIAL_RADAR_LEAD_HOURS`: horas antes del slot para buscar fuente y preparar copy, default `48`.
- `EDITORIAL_RADAR_APPROVAL_LEAD_MINUTES`: minutos antes del slot para pedir aprobacion por Telegram, default `60`.
- `EDITORIAL_RADAR_PUBLISH_DELAY_MINUTES`: minutos entre aprobacion por Telegram y publicacion, default `30`.
- `EDITORIAL_RADAR_DAYS_AHEAD`: cuantos slots futuros mantiene creados, default `14`.
- `EDITORIAL_RADAR_SOURCE_MAX_AGE_HOURS`: antiguedad maxima preferida para fuentes del radar, default `168`.
- `LINKEDIN_LI_AT`, `LINKEDIN_JSESSIONID`: opcionales para scraping de metricas via Voyager.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID`: opcionales para el bot.
- `X_USERNAME`, `X_AUTH_TOKEN`, `X_CT0`: opcionales para el monitor de likes en X.
- `X_AUTO_SCHEDULE_ENABLED`: activa autocalendarizacion desde likes de X, default `false`.
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

Si quieres generar el texto con OpenAI usando un modelo mas barato, por ejemplo GPT-5 mini, configura:

```env
TEXT_GENERATION_PROVIDER=openai
OPENAI_API_KEY=tu_api_key
OPENAI_TEXT_MODEL=gpt-5-mini
OPENAI_REASONING_EFFORT=minimal
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

## Autoarranque En Windows

Si quieres que la app vuelva sola despues de reiniciar Windows, usa:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install-autostart.ps1
```

Eso registra una tarea de Windows que lanza un supervisor local al iniciar sesion. El supervisor:

- arranca la app si no esta corriendo
- evita instancias duplicadas
- vuelve a levantarla si se cae

Si alguna vez quieres quitarlo:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\uninstall-autostart.ps1
```

Si prefieres que arranque incluso sin iniciar sesion en Windows, usa el instalador de arranque del sistema ejecutandolo una sola vez como administrador:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install-boot-autostart.ps1
```

Y para quitar ese modo:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\uninstall-boot-autostart.ps1
```

## Uso Desde La Web

1. Conecta LinkedIn.
2. Pega un URL de tweet de X.
3. Genera el post con IA.
4. Edita el copy si hace falta.
5. Elige publicar ahora o programar.

La programacion funciona por slots diarios a las `9:00 AM` hora de CDMX/Monterrey. Con el radar activo, esos slots se crean vacios, se preparan cerca de la fecha y solo se publican si apruebas por Telegram. Antes de elegir fuente, el radar arma una memoria editorial desde publicaciones publicadas, priorizando las de mejor desempeno y usando tambien posts manuales/pre-herramienta como referencia de voz. La aprobacion mueve la publicacion a 30 minutos despues del momento de aprobar.

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

Cuando esta activo y `X_AUTO_SCHEDULE_ENABLED=true`:

- revisa likes cada `X_CHECK_INTERVAL_MINUTES`
- hace una semilla inicial para no procesar likes antiguos
- genera posts `x_auto`
- los acomoda en slots consecutivos

Por defecto esta desactivado para que el calendario lo controle el radar editorial diario.

## Bot De Telegram

Si configuras `TELEGRAM_BOT_TOKEN` y `TELEGRAM_USER_ID`, el bot arranca junto con la app y te permite:

- enviar tweets o articulos web para generar posts
- editar previews antes de publicar
- programar o publicar al instante
- aprobar o cancelar posts del radar desde solicitudes abiertas sin vencimiento
- pedir cambios en lenguaje natural con el boton o respondiendo a la tarjeta; cada post conserva sus indicaciones acumuladas
- pedir al radar que busque otra fuente para ese mismo slot
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

## Migracion Cloud

El plan para mover la herramienta a Netlify Free y Supabase Free, sin depender
de esta computadora y sin costo incremental de infraestructura, vive en
[`docs/cloud-migration/README.md`](docs/cloud-migration/README.md). Incluye
arquitectura, historias de usuario, fases, controles de costo, seguridad,
backups, corte, reversa y un registro para reanudar la ejecucion.

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
|       |-- editorial_learning.py
|       |-- editorial_radar.py
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
