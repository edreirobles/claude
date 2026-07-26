# Inventario de variables cloud

Fecha de auditoria: 2026-07-25

Este documento solo contiene nombres y clasificacion.

## Frontend

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `APP_ENV`

La publishable key no accede al esquema privado `app`.

## Servidor Netlify

Secretos:

- `DATABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`, solo si una operacion futura lo requiere
- `ALLOWED_USER_ID`
- `CREDENTIAL_ENCRYPTION_KEY`
- `DISPATCH_SECRET`
- `WORKER_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_USER_ID`
- `TELEGRAM_WEBHOOK_SECRET`
- `LINKEDIN_CLIENT_ID`
- `LINKEDIN_CLIENT_SECRET`
- `LINKEDIN_REDIRECT_URI`
- `ANTHROPIC_API_KEY` o `OPENAI_API_KEY`

Configuracion:

- `APP_ORIGIN`
- `TEXT_GENERATION_PROVIDER`
- `ANTHROPIC_TEXT_MODEL`
- `OPENAI_TEXT_MODEL`
- `OPENAI_REASONING_EFFORT`
- `LINKEDIN_API_VERSION`
- `LINKEDIN_READ_SCOPE_ENABLED`

`URL` es una variable integrada de Netlify y se usa para invocar el worker del
mismo deploy.

## Kill switches

- `PUBLISHING_ENABLED`
- `TELEGRAM_SEND_ENABLED`
- `RADAR_ENABLED`
- `NONCRITICAL_JOBS_ENABLED`
- `MIGRATION_FREEZE`

Todo deploy nuevo inicia con efectos apagados. No existe handler cloud para
generacion de imagenes.

## GitHub Actions

- `X2LI_DATABASE_URL`
- `X2LI_BACKUP_PASSPHRASE`
- `X2LI_TELEGRAM_BOT_TOKEN`
- `X2LI_TELEGRAM_USER_ID`

Los dos ultimos permiten avisar un backup fallido. Ningun secreto se entrega a
pull requests.

## Heredadas no migradas

- Cookies Voyager y credenciales X antiguas
- `GOOGLE_API_KEY` para imagenes
- `SECRET_KEY` sin consumidor
- `LINKEDIN_LI_AT`
- `LINKEDIN_JSESSIONID`

La capa cloud usa OAuth y APIs HTTP oficiales/versionadas. Playwright, polling,
APScheduler y generacion de imagenes quedan fuera.
