# Progreso de migracion

Ultima actualizacion: 2026-07-25

Estado: IMPLEMENTACION_LISTA_ACTIVACION_BLOQUEADA

Rama: `codex/cloud-netlify-supabase`

## Estado ejecutivo

La implementacion cloud esta completa en codigo y validada localmente. La
produccion local sigue activa y no fue detenida, reiniciada ni puesta en freeze.
Todos los efectos del sitio Netlify estan apagados.

Sitio Netlify creado:

- ID: `5d1f0cf3-b981-495d-ba47-90a7fc0ff575`
- URL: `https://x2li-radar-victor.netlify.app`
- Plan: Free
- Deploy activo: `6a65856e40010eee03addb61`
- Entorno: `preview`
- `PUBLISHING_ENABLED=false`
- `TELEGRAM_SEND_ENABLED=false`
- `RADAR_ENABLED=false`
- `NONCRITICAL_JOBS_ENABLED=false`
- `MIGRATION_FREEZE=true`

El deploy activo expone health y las APIs serverless seguras, pero fue creado
antes de agregar la doble proteccion del dashboard. El siguiente deploy ya
incluye Function y Edge Function para la ruta `/`, pero Netlify lo rechazo antes
de construir porque la cuenta agoto sus creditos gratuitos del ciclo. No se
habilito cobro.

Supabase esta autenticado en una organizacion Free. Ya existen dos proyectos
activos, que es el limite gratuito. No se creo ni reutilizo un proyecto sin una
decision explicita del propietario.

## Snapshot mas reciente

Ensayo: `migration-artifacts/snapshot-20260725T221057Z`

| Tabla | Filas |
| --- | ---: |
| settings | 1 |
| linkedin_tokens | 1 |
| posts | 558 |
| x_liked_tweets | 132 |
| linkedin_comments | 172 |

El snapshot usa copia consistente de SQLite, checksums por archivo y tokens
AES-256-GCM. No contiene token de LinkedIn en plaintext.

## Estado de HUs

`DONE` significa implementada y validada sin necesitar un proveedor pendiente.
`BLOCKED` significa que el codigo esta preparado pero el criterio final requiere
Supabase, un nuevo deploy, OAuth, webhook o corte real.

| HU | Estado | Evidencia o bloqueo |
| --- | --- | --- |
| HU-001 | DONE | Planes Free confirmados; limite duro Netlify observado; guardas y alertas 50/70/85/90 implementadas |
| HU-002 | BLOCKED | Arbol actual limpio; falta rotar `LINKEDIN_CLIENT_SECRET` historico |
| HU-003 | DONE | 10 pruebas de caracterizacion pasan |
| HU-004 | DONE | TypeScript, lockfile, Netlify config y health remoto 200 |
| HU-005 | BLOCKED | Auth implementado; falta proyecto Supabase y desplegar proteccion final |
| HU-006 | DONE | 401/405, JWT, CSRF, rate limit, payload limit, state y firmas implementados |
| HU-101 | BLOCKED | Migracion privada lista; falta aplicarla y correr advisors |
| HU-102 | BLOCKED | Cola, leases, SKIP LOCKED y retry manual listos; falta prueba concurrente real |
| HU-103 | BLOCKED | Export e import idempotente listos; falta importar al proyecto elegido |
| HU-104 | DONE | AES-256-GCM, rotacion y llave incorrecta cubiertos por pruebas |
| HU-105 | BLOCKED | Workflow cifrado y restore listos; faltan proyecto y GitHub secrets |
| HU-201 | BLOCKED | Webhook firmado e idempotente listo; falta registrarlo en el corte |
| HU-202 | BLOCKED | Sin TTL y callbacks antiguos implementados; falta validar las aprobaciones importadas |
| HU-203 | BLOCKED | Sesiones durables y revisiones acumulativas listas; falta ciclo shadow con Postgres |
| HU-204 | BLOCKED | Cinco comandos y ultimo backup implementados; falta prueba Telegram cloud |
| HU-205 | BLOCKED | Comentarios durables e idempotentes listos; falta permiso y prueba LinkedIn |
| HU-301 | BLOCKED | Dispatcher y SQL sin HTTP cuando cola vacia listos; falta configurar Cron |
| HU-302 | BLOCKED | Backoff, dead letter, alerta y reintento manual listos; falta ejecucion real |
| HU-303 | BLOCKED | Cadencias y lotes listos; falta medirlos en Free |
| HU-304 | BLOCKED | Outbox y fingerprints listos; falta prueba concurrente contra Postgres |
| HU-305 | DONE | Kill switches activos tambien dentro del worker |
| HU-401 | BLOCKED | Feeds, arXiv, dedupe y filtro LLM listos; falta ciclo radar con DB |
| HU-402 | DONE | Ranking, razon, intencion, angulo y otra fuente persistidos |
| HU-403 | DONE | Perfil historico versionado con metricas y posts pre-herramienta |
| HU-404 | DONE | Copy variable, sin markdown artificial y sin reflexion forzada |
| HU-405 | DONE | Solo media de fuente; build cloud excluye toda imagen generada |
| HU-501 | BLOCKED | OAuth y refresh listos; falta rotacion, redirect y consentimiento |
| HU-502 | DONE | Postgres calcula `transaction_timestamp() + 30 minutes`; pruebas pasan |
| HU-503 | BLOCKED | Posts API actual, outbox y reconciliacion listos; falta prueba real |
| HU-504 | BLOCKED | Verificacion auditable lista; falta probar una fuente real antes de publicar |
| HU-505 | DONE | Generar, editar, ahora, programar y cancelar usan cola durable |
| HU-506 | BLOCKED | HTTP sin Playwright listo; falta confirmar permisos de LinkedIn |
| HU-601 | BLOCKED | Dashboard responsive y API paginada listos; falta login real |
| HU-602 | DONE | Settings con version optimista e invalidacion de perfil |
| HU-603 | DONE | Analitica y CSV escapado implementados |
| HU-604 | BLOCKED | Health, cola detallada y retry listos; falta datos reales |
| HU-605 | DONE | Sin git pull, restart, X auto ni media generada en cloud |
| HU-701 | DONE | Refresh incremental diario y manual; recalculo editorial condicional |
| HU-702 | BLOCKED | Eventos, correlation ID y alertas listos; falta activar Telegram/backup |
| HU-703 | BLOCKED | Script shadow listo; requiere Supabase importado |
| HU-801 | BLOCKED | Checklist listo; requiere aprobar el corte |
| HU-802 | BLOCKED | IDs y callbacks antiguos preservados; requiere import y webhook |
| HU-803 | BLOCKED | Kill switches y export cloud cifrado listos; falta ensayo con DB |
| HU-804 | BLOCKED | Requiere primer ciclo cloud y deshabilitar supervisor local |

## Evidencia ejecutada

- `npm run typecheck`: OK.
- `npm run test`: 23 pruebas cloud pasaron.
- `python -m unittest tests.test_phase0_characterization -v`: 10 pasaron.
- `npm run build`: OK.
- `netlify build --offline`: empaqueta 8 Functions y detecta la Edge Function.
- `/api/health` remoto: 200, `environment=preview`,
  `publishing_enabled=false`.
- Metodos no permitidos: 405.
- API privada anonima: 401.
- Duplicado `/static/index.html`: 404 en el build actualizado.
- Auditor de secretos: cero hallazgos en arbol actual; un secreto historico
  activo pendiente de rotacion.

La evidencia consolidada esta en `EVIDENCE.md`.

## Compuertas externas

1. Liberar un lugar Free de Supabase o autorizar un proyecto existente.
2. Esperar renovacion de creditos Netlify para el deploy final, sin comprar
   creditos.
3. Rotar el secreto LinkedIn y aceptar OAuth.
4. Dar acceso para crear GitHub Actions secrets.
5. Autorizar el momento exacto de freeze, webhook y corte.
