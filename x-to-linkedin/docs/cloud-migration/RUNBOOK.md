# Runbook de ejecucion

Este documento contiene el procedimiento ejecutable. No contiene valores de
secretos.

## Protocolo de reanudacion

Antes de cambiar codigo o servicios:

1. Leer `README.md`, `PLAN.md`, `BACKLOG.md` y `PROGRESS.md` completos.
2. Leer el `README.md` principal del proyecto.
3. Ejecutar `git status --short` desde `C:\Users\victo\claude\x-to-linkedin`.
4. No revertir cambios existentes del usuario.
5. Verificar precios y limites oficiales actuales.
6. Revisar el changelog de Supabase y documentacion Netlify relevante.
7. Cargar las skills de Supabase, Netlify Functions, Netlify Config y Netlify
   CLI/Deploy.
8. Leer las compuertas externas vigentes en `PROGRESS.md`.
9. Mantener produccion local intacta hasta el checklist de corte.
10. Ejecutar pruebas y registrar evidencia antes de cambiar un estado.

## Gates que requieren al usuario

Codex puede preparar codigo, migraciones, pruebas, CLI, previews, imports y
validaciones. Solo debe pedir intervencion cuando el proveedor exija una accion
personal no delegable:

- Elegir que proyecto Supabase Free se libera o reutiliza.
- Rotar `LINKEDIN_CLIENT_SECRET` en LinkedIn Developers.
- Consentimiento OAuth de LinkedIn.
- Permiso para crear repository secrets de GitHub Actions.
- Autorizacion del momento exacto de freeze y corte.

Nunca aceptar cobros, pruebas Pro ni tarjetas por inferencia.

## Ramas y despliegues

- Rama de trabajo prevista: `codex/cloud-netlify-supabase`.
- El repositorio Git es un monorepo cuyo root es `C:\Users\victo\claude`.
- El proyecto vive en `x-to-linkedin/`.
- Netlify debe configurar ese subdirectorio como `base`.
- Sitio creado: `x2li-radar-victor`.
- Site ID: `5d1f0cf3-b981-495d-ba47-90a7fc0ff575`.
- URL: `https://x2li-radar-victor.netlify.app`.
- El deploy actual es seguro para efectos, pero no es el artefacto de corte.
- Netlify agoto creditos gratuitos; esperar renovacion, no comprar creditos.
- Desplegar el artefacto final una vez que el limite lo permita.

No hacer commit de cambios de otros proyectos del monorepo.

## Inventario de variables

### Publicas en frontend

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `APP_ENV`

Estas variables no conceden acceso a tablas privadas por si mismas.

### Secretos de Netlify Functions

- `DATABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`, solo si una API oficial lo requiere
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
- `TEXT_GENERATION_PROVIDER`
- Modelo y configuracion del proveedor ya existente

### Feature flags

- `APP_ENV=preview|production`
- `PUBLISHING_ENABLED=false` hasta el corte
- `TELEGRAM_SEND_ENABLED=false` en shadow
- `RADAR_ENABLED=false` hasta shadow
- `NONCRITICAL_JOBS_ENABLED=true`
- `MIGRATION_FREEZE=true` hasta el corte

Configuracion LinkedIn:

- `LINKEDIN_API_VERSION=202605` o una version soportada mas nueva.
- `LINKEDIN_READ_SCOPE_ENABLED=false` salvo que la app tenga
  `r_member_social`.

### GitHub Actions

- `X2LI_DATABASE_URL`
- `X2LI_BACKUP_PASSPHRASE`
- `X2LI_TELEGRAM_BOT_TOKEN`
- `X2LI_TELEGRAM_USER_ID`

Usar GitHub Environments para impedir que workflows de pull request reciban
secretos. El repo es publico, por lo que todo artifact debe considerarse
descargable por terceros y debe permanecer cifrado.

## Reglas de base de datos

- Usar Supabase CLI `--help` para descubrir comandos actuales.
- Crear migraciones con `supabase migration new <nombre>`.
- Iterar SQL con herramientas de consulta; no llenar historial de migraciones
  durante la exploracion.
- Ejecutar advisors antes de cerrar una migracion.
- Evitar tablas de aplicacion en `public`.
- Si algo se expone por Data API, habilitar RLS y grants explicitos.
- Mantener funciones privilegiadas en schema privado, revocar `PUBLIC` y evitar
  `SECURITY DEFINER` salvo necesidad demostrada.
- Usar pooler transaccional SSL desde funciones efimeras.
- Para `pg_dump` desde GitHub Actions, usar la cadena de conexion recomendada
  por el dashboard para clientes sin IPv6, normalmente el pooler en modo sesion;
  confirmar el host y puerto vigentes antes de implementarlo.
- No depender de sesiones, temp tables o prepared statements persistentes.

## Contrato de cola

Creacion:

1. La transaccion de negocio inserta o actualiza la entidad.
2. Inserta job con `dedupe_key` estable.
3. Commit unico.

Claim:

1. Seleccionar jobs `pending` o `retry_wait` con `run_at <= now()`.
2. Bloquear con `FOR UPDATE SKIP LOCKED`.
3. Cambiar a `claimed`, crear lease token y `lease_expires_at`.
4. Commit y devolver lote pequeno.

Ejecucion:

1. Background Function valida secreto y lease.
2. Cambia a `running`.
3. Revisa kill switch dentro del worker.
4. Escribe outbox antes de un efecto externo.
5. Ejecuta efecto.
6. Guarda identificador externo y marca `succeeded`.

Recuperacion:

- Lease vencido sin efecto confirmado pasa a `retry_wait`.
- Timeout ambiguo en LinkedIn pasa a `reconciling`, no a retry inmediato.
- Maximo de intentos pasa a `dead` y notifica una sola vez.

## Contrato de aprobacion

La aprobacion Telegram debe ejecutarse en una transaccion:

1. Insertar `telegram_update_id`; si existe, devolver estado actual.
2. Bloquear post por ID.
3. Verificar `status = approval_pending`.
4. Establecer `approved_at = transaction_timestamp()`.
5. Establecer `publish_at = approved_at + interval '30 minutes'`.
6. Cambiar status a `scheduled`.
7. Insertar job `publish_post:<post_id>:<approved_at>` con `run_at=publish_at`.
8. Commit.
9. Responder por Telegram con hora CDMX.

No existe expires_at para approval. Nuevas tarjetas no invalidan anteriores.

## Telegram webhook

Orden de validacion:

1. Metodo POST y Content-Type permitido.
2. Header secret de Telegram con comparacion constante.
3. Payload dentro del limite.
4. `from.id` o `message.from.id` coincide con usuario permitido.
5. `update_id` no procesado.

Registrar webhook solo durante el corte, despues de detener polling local:

```text
setWebhook(url=<NETLIFY_URL>/api/telegram/webhook,
           secret_token=<TELEGRAM_WEBHOOK_SECRET>,
           drop_pending_updates=false)
```

No escribir el token del bot en la URL ni en comandos documentados.

## Importacion SQLite

Ensayo:

1. Abrir SQLite en modo read-only y transaccion consistente.
2. Exportar NDJSON por tabla con checksum SHA-256.
3. No exportar APScheduler; reconstruir jobs desde estado de negocio.
4. Importar en orden de FKs con upsert por ID.
5. Ajustar sequences al maximo ID.
6. Verificar conteos, min/max timestamps, sumas de metricas y hashes de texto.
7. Verificar manualmente approvals, paused y JSON.

Corte:

- Repetir con snapshot final.
- Importar delta por ID y `updated_at` cuando exista.
- No crear jobs para `paused`, `cancelled` o `published`.
- Crear jobs de publish solo para `scheduled` futuros.
- Mantener `approval_pending` sin job de publicacion.
- Crear radar prep/approval solo para `radar_slot` futuro.

## Backup nocturno

Workflow permitido solo por `schedule` y `workflow_dispatch` en la rama default:

1. Usar la imagen fijada `postgres:17-alpine`.
2. Ejecutar dump logico custom del schema `app`.
3. Comprimir.
4. Cifrar AES-256-CBC con PBKDF2 e iteraciones fijadas.
5. Borrar plaintext en el runner.
6. Restaurar en un Postgres efimero y comprobar tablas, indices y constraints.
7. Subir solo `.enc` con retencion de 30 dias.
8. Registrar checksum y tamano en `app.backup_runs`.
9. Notificar por Telegram si el workflow falla.

Nunca imprimir connection strings, comandos expandidos ni variables secretas.

Cada ejecucion nocturna hace un restore efimero antes de subir el artifact. Para
un restore operativo, descargar el artifact, validar `SHA256SUMS`, descifrar con
la passphrase y usar `pg_restore --exit-on-error` sobre un proyecto vacio.

## Orden de activacion

1. Elegir proyecto Supabase y aplicar
   `supabase/migrations/20260726023410_initial_cloud_schema.sql`.
2. Ejecutar advisors y comprobar cero grants a `anon` y `authenticated`.
3. Configurar Auth y copiar `ALLOWED_USER_ID`.
4. Cargar variables Netlify con todos los efectos apagados.
5. Ejecutar `npm run cloud:import -- <snapshot>`.
6. Ejecutar `npm run cloud:reconcile -- <snapshot>`.
7. Ejecutar `npm run cloud:configure`.
8. Desplegar y comprobar redirect `/`, login, health, 401 y 405.
9. Activar solo `RADAR_ENABLED=true` y correr `npm run cloud:shadow`.
10. Rotar LinkedIn, configurar redirect y aceptar OAuth.
11. Ejecutar backup manual y verificar restore.
12. Solicitar autorizacion de corte.

## Presupuesto operativo

Politica inicial:

- Maximo un production deploy por entrega cerrada.
- Background jobs en lotes con limite temporal interno de 12 minutos.
- Comentarios cada 60 minutos.
- Metricas una vez al dia.
- Radar una vez por slot.
- No invocar Netlify cada minuto cuando la cola esta vacia.

Prioridad al acercarse al limite:

1. Mantener webhook Telegram.
2. Mantener aprobacion y publicacion.
3. Mantener radar diario.
4. Reducir comentarios.
5. Suspender metricas automaticas.
6. Suspender analitica no esencial.

## Checklist de corte

- [ ] HUs P0 en DONE.
- [ ] Netlify permite build sin comprar creditos.
- [ ] Proteccion Function/Edge desplegada en `/`.
- [ ] Backup local verificado.
- [ ] Backup Supabase cifrado y restore probado.
- [ ] Shadow completo sin diferencias abiertas.
- [ ] `PUBLISHING_ENABLED=false` en cloud.
- [ ] Local en migration freeze.
- [ ] Polling y scheduler local detenidos.
- [ ] Snapshot final importado y reconciliado.
- [ ] 10 o el conteo final de approvals presentes.
- [ ] Paused conserva conteo y no tiene jobs.
- [ ] Telegram webhook registrado sin descartar updates.
- [ ] LinkedIn OAuth cloud conectado.
- [ ] Smoke tests verdes.
- [ ] `PUBLISHING_ENABLED=true` solo en cloud.
- [ ] Primer ciclo observado.

## Checklist de reversa

- [ ] Desactivar publishing cloud.
- [ ] Cancelar dispatch Cron o volverlo no-op.
- [ ] Esperar o invalidar leases activos.
- [ ] Quitar webhook Telegram sin borrar updates.
- [ ] Exportar delta cloud.
- [ ] Restaurar y reconciliar local.
- [ ] Arrancar polling local.
- [ ] Arrancar scheduler local.
- [ ] Confirmar un solo ejecutor habilitado.
- [ ] Registrar incidente y causa.

Antes de reactivar local, ejecutar:

`npm run cloud:rollback-export -- migration-artifacts/cloud-rollback.json.enc`

El archivo contiene el estado compatible con local dentro de un envelope
AES-256-GCM. Nunca se escribe un snapshot cloud plaintext.

## Evidencia minima por HU

Cada HU marcada DONE debe incluir en `PROGRESS.md`:

- Commit o lista de archivos.
- Comandos de prueba y resultado.
- URL de preview cuando aplique.
- Migracion y advisors cuando aplique.
- Captura de conteos para cambios de datos.
- Riesgos residuales o deuda aceptada.
