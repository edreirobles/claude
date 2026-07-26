# Plan de migracion

Estado general: LISTO PARA EJECUTAR CUANDO EL USUARIO LO AUTORICE

## Invariantes

Estas condiciones tienen prioridad sobre cualquier conveniencia tecnica:

1. No contratar ni activar recursos pagados.
2. No activar auto recharge ni agregar un medio de pago como parte del flujo.
3. No publicar desde cloud y local al mismo tiempo.
4. No perder ni vencer aprobaciones abiertas.
5. Aprobar crea `publish_at = approved_at + 30 minutes` usando tiempo de base.
6. Cada publicacion tiene una llave de idempotencia estable.
7. Los cambios pedidos por Telegram se acumulan y quedan persistidos.
8. No generar imagenes; usar solo multimedia real de la fuente.
9. Nunca guardar secretos en Git, logs, frontend, URLs o artifacts sin cifrar.
10. Los slots con estado `paused` permanecen pausados.
11. La zona editorial es `America/Mexico_City`; la base guarda `timestamptz` UTC.
12. Cada fase termina con pruebas y una actualizacion de `PROGRESS.md`.

## Estrategia

La migracion se hara por sustitucion progresiva y corte unico:

- El sistema local sigue siendo produccion durante la construccion.
- Cloud opera primero en modo `shadow`, sin permisos para publicar.
- Los datos se importan en un ensayo y se reconcilian por conteos y hashes.
- El corte final detiene local, toma un snapshot, importa el delta, cambia
  Telegram a webhook y habilita publicaciones cloud.
- La base SQLite y el codigo local se conservan para reversa hasta cerrar el
  periodo de estabilizacion.

## Fase 0: preparacion y controles

Objetivo: crear un camino de trabajo seguro antes de tocar servicios cloud.

Tareas:

- Confirmar que Netlify y Supabase siguen ofreciendo los limites gratuitos
  documentados.
- Consultar changelogs oficiales de Supabase y Netlify.
- Crear rama `codex/cloud-netlify-supabase` desde el estado acordado.
- Crear `.dockerignore` y revisar que `.env`, bases, cookies y artifacts no
  entren en builds ni commits.
- Inventariar variables por nombre y clasificar secreto/publica/deprecada.
- Crear pruebas de caracterizacion del flujo local critico.
- Definir presupuesto operativo y umbrales de pausa.

Gate de salida:

- No hay secretos rastreados por Git.
- Las pruebas capturan aprobacion, revision, programacion y publicacion.
- La cuenta Netlify esta en Free y auto recharge no aplica o esta apagado.
- El proyecto Supabase esta en Free.

HUs: HU-001, HU-002, HU-003.

## Fase 1: esqueleto serverless

Objetivo: desplegar una version de preview sin acceso a datos reales.

Tareas:

- Crear workspace TypeScript con versiones fijadas y lockfile.
- Configurar `netlify.toml` con base del monorepo, frontend y functions.
- Portar el frontend estatico sin cambiar su experiencia principal.
- Crear `/api/health` y manejo uniforme de errores y request IDs.
- Implementar Supabase Auth para un solo usuario permitido.
- Proteger todos los endpoints salvo health, callbacks OAuth y webhook Telegram.
- Deshabilitar endpoints de administracion local.

Gate de salida:

- Deploy Preview funcional.
- El dashboard no es accesible sin sesion valida.
- Ningun secreto aparece en bundle, HTML, respuestas o logs.

HUs: HU-004, HU-005, HU-006.

## Fase 2: Postgres y migracion reproducible

Objetivo: crear el modelo durable y demostrar que SQLite puede importarse sin
perdida.

Tareas:

- Crear proyecto Supabase Free y configuracion CLI.
- Crear migraciones mediante Supabase CLI, nunca con filenames manuales.
- Usar esquema privado `app` para datos operativos.
- Crear tablas, constraints, indices, funciones de claim y auditoria.
- Cifrar tokens de LinkedIn con AES-GCM y una llave solo de servidor.
- Construir exportador SQLite e importador Postgres idempotentes.
- Preservar IDs, timestamps, estados, JSON, notas y relaciones.
- Ejecutar advisors y consultas de validacion.

Modelo minimo:

| Tabla | Responsabilidad |
| --- | --- |
| `app.settings` | Configuracion editorial versionada |
| `app.linkedin_tokens` | Tokens cifrados y expiracion |
| `app.posts` | Historial, borradores, estados, programacion y metricas |
| `app.linkedin_comments` | Comentarios y respuestas |
| `app.x_liked_tweets` | Historia heredada de X |
| `app.job_queue` | Ejecucion diferida, leases, retries y deduplicacion |
| `app.telegram_updates` | Idempotencia de webhooks por `update_id` |
| `app.telegram_messages` | Relacion mensaje, post y tipo de tarjeta |
| `app.telegram_sessions` | Modos de edicion y borradores persistentes |
| `app.radar_candidates` | Candidatas, ranking y decisiones del radar |
| `app.editorial_profiles` | Perfil aprendido, version y muestra usada |
| `app.event_log` | Auditoria operativa sin secretos |

Estados de job:

`pending`, `claimed`, `running`, `succeeded`, `retry_wait`, `dead`, `cancelled`.

Estados de post conservados:

`radar_slot`, `approval_pending`, `scheduled`, `published`, `failed`,
`cancelled`, `paused` y los estados historicos que aparezcan en el snapshot.

Gate de salida:

- Conteos por tabla, estado y fuente coinciden con SQLite.
- Una segunda importacion no duplica filas.
- Los 10 approvals y 43 paused de la linea base conservan su estado.
- Advisors sin hallazgos criticos.
- Tokens almacenados solo como ciphertext versionado.

HUs: HU-101 a HU-105.

## Fase 3: Telegram stateless

Objetivo: reemplazar polling y memoria de proceso por webhook y Postgres.

Tareas:

- Crear webhook con validacion de secret token y `TELEGRAM_USER_ID`.
- Deduplicar cada `update_id` antes de ejecutar acciones.
- Persistir tarjetas, mensajes, modos y borradores.
- Portar comandos y callbacks prioritarios.
- Hacer que las revisiones largas creen un job y respondan rapido.
- Mantener fallback por texto `Post #N` para respuestas a tarjetas antiguas.
- Implementar reenvio de tarjetas revisadas sin cerrar la aprobacion.

Gate de salida:

- Los callbacks repetidos no duplican acciones.
- Reiniciar o redesplegar no pierde estados de conversacion.
- Varias aprobaciones pueden coexistir indefinidamente.
- Una respuesta a una tarjeta vieja identifica el post correcto.

HUs: HU-201 a HU-203. HU-204 y HU-205 se completan cuando sus APIs de consulta
y comentarios esten disponibles.

## Fase 4: cola, Cron y ejecucion

Objetivo: reemplazar APScheduler con una cola durable y de bajo consumo.

Tareas:

- Crear `claim_due_jobs` atomico con `FOR UPDATE SKIP LOCKED`.
- Crear dedupe keys y leases recuperables.
- Configurar Supabase Cron para comprobar jobs cada minuto.
- Invocar Netlify solo cuando exista trabajo vencido.
- Crear dispatcher autenticado y Background Function generica.
- Implementar backoff acotado y dead-letter operativo.
- Crear jobs periodicos de mantenimiento sin materializar miles de jobs.

Cadencias iniciales para cuidar creditos:

| Trabajo | Cadencia |
| --- | --- |
| Dispatch de jobs vencidos | Cada minuto en SQL; HTTP solo si hay trabajo |
| Mantenimiento de slots radar | Cada 6 horas en SQL ligero |
| Preparacion radar | Una vez por slot, hasta 48 h antes |
| Solicitud de aprobacion | Una vez por borrador, 60 min antes del slot original |
| Publicacion | Exactamente 30 min despues de aprobar, precision objetivo 0-60 s |
| Comentarios | Cada 60 min, incremental |
| Metricas | Una vez al dia y bajo demanda |
| Perfil editorial | Al cambiar metricas relevantes o cada 24 h |
| Respaldo | Nocturno |

Gate de salida:

- Simulacion concurrente demuestra un solo claim por job.
- Un timeout y un retry producen un solo efecto externo.
- Un job abandonado vuelve a `retry_wait` tras vencer su lease.
- El dispatcher no es invocable sin firma valida.

HUs: HU-301 a HU-305.

## Fase 5: radar y memoria editorial

Objetivo: portar la decision editorial sin volverla una plantilla automatica.

Tareas:

- Portar feeds, arXiv, deduplicacion y normalizacion de URLs.
- Guardar todas las candidatas evaluadas y el motivo de seleccion.
- Portar score historico y referencias manuales/pre-herramienta.
- Persistir perfiles editoriales versionados, no solo cachearlos en memoria.
- Mantener intenciones variables: presentar, describir, invitar, explicar,
  advertir, analizar o reflexionar.
- Aplicar reglas de estilo sin asteriscos, guiones artificiales ni imagenes
  generadas.
- Reforzar frase ancla cuando no haya multimedia real.

Gate de salida:

- Una ejecucion shadow produce candidato, decision, borrador y trazabilidad.
- Fuentes ya usadas no reaparecen salvo regeneracion explicita.
- Lanzamientos de LLM general quedan fuera salvo justificacion clara.
- Las muestras historicas de alto y bajo rendimiento influyen en el perfil.

HUs: HU-401 a HU-405.

## Fase 6: LinkedIn y publicacion

Objetivo: publicar desde cloud con OAuth, verificacion e idempotencia.

Tareas:

- Cambiar redirect OAuth a la URL Netlify.
- Portar refresh de token y errores de reautenticacion.
- Implementar outbox de publicacion e idempotency key.
- Separar `publishing` de `published` y persistir cada intento.
- Publicar texto y multimedia real compatible.
- Conservar verificacion previa y mensajes de error por Telegram.
- Portar comentarios y metricas basados en HTTP.

Gate de salida:

- Prueba sandbox/mocked de cada tipo de publicacion.
- Una aprobacion crea un unico job a +30 minutos.
- Reintentar el callback o el job no duplica la publicacion.
- Un fallo de autenticacion conserva el post y pide reconexion.

HUs: HU-501 a HU-506 y HU-205.

## Fase 7: dashboard y operacion

Objetivo: recuperar la operacion diaria y hacer visible la salud del sistema.

Tareas:

- Portar listado, edicion, cancelacion, exportacion y ajustes.
- Portar analitica y refresh de metricas.
- Mostrar jobs fallidos, cola, ultimo radar y ultimo respaldo.
- Medir invocaciones, duracion y estimacion de creditos Netlify.
- Crear respaldo GitHub Actions cifrado y prueba de restauracion.
- Documentar incidentes, rotacion de secretos y recuperacion.

Gate de salida:

- Flujos prioritarios funcionan desde web y Telegram.
- Respaldo y restore se prueban en tablas temporales.
- Alertas operativas llegan a Telegram sin filtrar secretos.
- Proyeccion mensual se mantiene por debajo del 70% de la cuota Netlify.

HUs: HU-601 a HU-604, HU-701 y HU-702. HU-605 queda para el cierre posterior
al corte.

## Fase 8: shadow, corte y estabilizacion

Objetivo: cambiar de produccion sin perder eventos ni duplicar publicaciones.

Ensayo shadow:

1. Importar snapshot en cloud.
2. Ejecutar radar, Telegram simulado y jobs con `PUBLISHING_ENABLED=false`.
3. Comparar decisiones, conteos, timestamps y payloads.
4. Operar al menos un ciclo editorial completo en shadow.
5. Corregir y repetir hasta pasar gates.

Corte final:

1. Confirmar backup local y cloud restaurable.
2. Activar `MIGRATION_FREEZE=true` local.
3. Detener supervisor, APScheduler y polling Telegram.
4. Tomar snapshot SQLite final e importar delta.
5. Verificar conteos y estados activos.
6. Configurar webhook Telegram con `drop_pending_updates=false`.
7. Actualizar redirect de LinkedIn y reconectar si es necesario.
8. Habilitar dispatcher cloud con publicacion aun apagada.
9. Ejecutar smoke tests.
10. Activar `PUBLISHING_ENABLED=true`.
11. Observar primer approval, primera revision y primera publicacion.

Reversa:

1. Poner cloud en `PUBLISHING_ENABLED=false`.
2. Desactivar webhook Telegram sin borrar updates pendientes.
3. Exportar a SQLite cualquier cambio creado solo en cloud.
4. Restaurar snapshot y delta en local.
5. Reiniciar polling y scheduler local.
6. Confirmar que no existe un job cloud capaz de publicar.

Gate de salida:

- Primer ciclo completo cloud confirmado por Telegram y LinkedIn.
- Cero publicaciones duplicadas.
- Cero aprobaciones o revisiones perdidas.
- Sistema local detenido, pero snapshot y runbook conservados.

HUs: HU-703, HU-801 a HU-804 y HU-605.

## Matriz de pruebas

| Nivel | Cobertura minima |
| --- | --- |
| Unitarias | normalizacion, scoring, tiempos, estilos, cifrado, dedupe |
| Base | constraints, claims concurrentes, leases, transiciones, import idempotente |
| Contrato | Telegram, LinkedIn, IA, RSS, arXiv y Supabase mediante fixtures |
| Integracion | webhook a DB, Cron a dispatcher, background a DB |
| E2E preview | login, generar, editar, aprobar, cancelar, exportar |
| Shadow | ciclo diario completo con efectos externos bloqueados |
| Restore | dump cifrado, descifrado e importacion en tablas temporales |

## Riesgos principales

| Riesgo | Prevencion | Respuesta |
| --- | --- | --- |
| Agotar 300 creditos Netlify | SQL Cron, lotes, metricas diarias, pocos deploys | Pausar jobs no criticos; Free se detiene sin cobrar |
| Pausa de Supabase por inactividad | Actividad diaria real y health operativo | Reanudar proyecto y procesar jobs vencidos con leases |
| Publicacion duplicada | outbox, unique key, claim atomico | Bloquear job, auditar LinkedIn y reconciliar |
| Perdida de datos | dump nocturno cifrado y restore probado | Restaurar ultimo dump y reproducir eventos |
| Token filtrado | cifrado, secretos server-only, redaccion de logs | Revocar, rotar y reautorizar |
| Callback Telegram repetido | `update_id` unique y transaccion atomica | Devolver resultado ya aplicado |
| Deploy durante job activo | leases y estado en Postgres | Nuevo deploy reanuda o recupera job |
| Scraping X bloqueado | extractores HTTP y degradacion explicita | Pedir otra fuente; no agregar navegador pagado |
| Cambio de limites gratuitos | revisar precios antes de cada fase | Detener migracion y redisenar sin aceptar cobro |

## Definicion global de terminado

La migracion termina cuando:

- Toda la operacion normal ocurre sin que la computadora local este encendida.
- El costo incremental de infraestructura es USD 0.
- El historial completo esta reconciliado y respaldado.
- Telegram funciona por webhook y conserva aprobaciones/revisiones.
- Una aprobacion se publica una sola vez 30 minutos despues.
- Radar y aprendizaje producen variedad con trazabilidad.
- No existe ningun camino activo de generacion de imagenes.
- El dashboard esta autenticado.
- Backup, restore y reversa fueron probados.
- `PROGRESS.md` marca todas las HUs P0 y P1 como `DONE`.
