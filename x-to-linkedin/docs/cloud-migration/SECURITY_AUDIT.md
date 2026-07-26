# Auditoria de seguridad de Fase 0

Fecha: 2026-07-25.

## Resultado

- No se detectaron valores con forma de secreto en archivos rastreados del arbol
  actual.
- `.env`, SQLite y logs ya estaban ignorados.
- Se agregaron exclusiones para dumps, respaldos cifrados, JSONL, media generada,
  diagnosticos, Netlify y estado temporal de Supabase.
- `.dockerignore` impide que secretos y datos operativos entren al contexto de
  build.
- Los logs de la aplicacion pasan por un formatter que redacta Authorization,
  cookies, tokens, passwords y URLs con credenciales.
- Las dependencias Python directas quedaron fijadas a las versiones verificadas
  en el entorno funcional.
- El dashboard tiene defensa doble: Function autenticada en `/` y Edge Function.
- El build cloud excluye media generada y la copia duplicada del dashboard.
- Las APIs privadas validan JWT y usuario exacto; mutaciones agregan guard CSRF.
- Telegram valida secret token, usuario y `update_id` antes de efectos.
- URLs externas bloquean destinos locales, metadata y redirects inseguros.

## Hallazgo historico

El repositorio publico contiene commits antiguos con `x-to-linkedin/.env`.
La comparacion por nombre, sin imprimir valores, encontro:

- Una clave Anthropic historica que ya no coincide con la activa.
- Un `LINKEDIN_CLIENT_SECRET` historico que si coincide con el activo.
- Un `LINKEDIN_CLIENT_ID` historico coincidente; es un identificador, no una
  credencial.
- Un `SECRET_KEY` historico que no coincide con el valor local.

El gate de secretos permanece abierto hasta rotar `LINKEDIN_CLIENT_SECRET`.
Reescribir Git no revoca una credencial y no se hara sin autorizacion explicita.

La API de GitHub Secret Scanning respondio como no disponible para este
repositorio. El control reproducible local es:

`python scripts/audit_phase0_security.py`

El comando solo imprime nombres y conteos. Debe terminar en codigo 0 despues de
la rotacion.
