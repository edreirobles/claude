# Backlog de historias de usuario

Estados permitidos: `TODO`, `IN_PROGRESS`, `BLOCKED`, `DONE`.

Prioridades:

- P0: necesaria para cortar a cloud.
- P1: necesaria para cerrar la migracion con paridad operativa.
- P2: puede completarse despues del corte sin comprometer el flujo diario.

## Epica A: costo, seguridad y base cloud

### HU-001 Control de costo cero

Prioridad: P0

Como propietario quiero que la infraestructura tenga un limite efectivo de USD
0 para que la automatizacion nunca genere un cargo inesperado.

Criterios de aceptacion:

- Netlify y Supabase estan en planes Free.
- No se habilita auto recharge, Pro, add-ons, dominio pagado ni AI Gateway.
- El sistema registra uso estimado y avisa al 50%, 70% y 85% del presupuesto.
- Al 90%, se suspenden metricas y comentarios antes que radar, Telegram o
  publicacion.
- Alcanzar el limite pausa servicio; nunca habilita cobro.

Dependencias: ninguna.

### HU-002 Higiene de repositorio y secretos

Prioridad: P0

Como propietario quiero que ningun secreto o dato operativo entre a Git o a un
build para poder usar un repositorio publico sin exponer la cuenta.

Criterios de aceptacion:

- `.env`, SQLite, cookies, logs, dumps y media generada estan ignorados.
- Existe `.dockerignore` aunque Docker deje de ser el destino principal.
- Secret scanning local no encuentra valores reales en archivos rastreados.
- Los logs redactan tokens, cookies, Authorization y payloads sensibles.
- Dependencias y acciones estan fijadas a versiones revisables.

Dependencias: ninguna.

### HU-003 Caracterizacion del sistema actual

Prioridad: P0

Como implementador quiero pruebas del comportamiento actual para portar sus
reglas sin reinterpretarlas.

Criterios de aceptacion:

- Hay fixtures para approval, revision, cancelacion y aprobacion repetida.
- Se prueba `approved_at + 30 minutes` en cambio de dia y horario de verano.
- Se prueba que approval no expira y que paused no se agenda.
- Se prueba que no se genera imagen cuando falta multimedia.
- Hay snapshot de conteos por tabla, estado y fuente.

Dependencias: ninguna.

### HU-004 Esqueleto Netlify

Prioridad: P0

Como implementador quiero un Deploy Preview serverless para validar la
aplicacion sin consumir produccion.

Criterios de aceptacion:

- TypeScript compila con lockfile comprometido.
- `netlify.toml` usa `x-to-linkedin` como base del monorepo.
- `/api/health` responde con version, entorno y request ID, sin secretos.
- Deploy Preview no puede publicar ni usar credenciales productivas.

Dependencias: HU-001, HU-002.

### HU-005 Acceso privado al dashboard

Prioridad: P0

Como propietario quiero ser el unico usuario del dashboard cloud para que la
interfaz y las acciones administrativas no queden publicas.

Criterios de aceptacion:

- Login usa Supabase Auth.
- Solo el `user_id` permitido puede consumir APIs.
- Todos los endpoints privados validan el JWT en servidor.
- El frontend contiene solo URL y publishable key de Supabase.
- `service_role`, DB password y secretos nunca llegan al navegador.

Dependencias: HU-004.

### HU-006 Superficie HTTP segura

Prioridad: P0

Como propietario quiero endpoints minimos y protegidos para reducir el riesgo de
poner una herramienta local en internet.

Criterios de aceptacion:

- Metodos HTTP no esperados devuelven 405.
- Requests mutables requieren autenticacion o firma especifica.
- Telegram y LinkedIn callbacks validan secreto o `state` de un solo uso.
- Endpoints `git-pull`, `restart` y `pull-and-restart` no existen en cloud.
- Hay limites de payload y rate limiting basico.

Dependencias: HU-004, HU-005.

## Epica B: datos y respaldo

### HU-101 Esquema Postgres privado

Prioridad: P0

Como sistema quiero guardar estado en Postgres para sobrevivir invocaciones,
deploys y concurrencia.

Criterios de aceptacion:

- Las tablas operativas viven en esquema privado `app`.
- Timestamps operativos usan `timestamptz`.
- Estados, relaciones y JSON tienen constraints explicitos.
- Existen indices para status/run_at, source/status, published_at y FKs.
- Ninguna tabla operativa es accesible por `anon` o `authenticated` via Data API.

Dependencias: HU-002.

### HU-102 Cola durable

Prioridad: P0

Como sistema quiero una cola en Postgres para sustituir APScheduler sin perder
trabajo cuando no hay un servidor encendido.

Criterios de aceptacion:

- Cada job tiene tipo, run_at, estado, intentos, lease y dedupe key.
- La dedupe key tiene constraint unique.
- Claim concurrente entrega cada job a un solo worker.
- Leases vencidos se recuperan con backoff.
- Los jobs dead permanecen visibles y reintentables manualmente.

Dependencias: HU-101.

### HU-103 Importacion completa de SQLite

Prioridad: P0

Como propietario quiero conservar toda la historia para que el radar siga
aprendiendo y no se pierdan pendientes.

Criterios de aceptacion:

- Se importan settings, tokens, 544 posts, 132 likes y 170 comentarios de la
  linea base, ajustados al snapshot final.
- IDs, relaciones, timestamps, metricas, JSON y notas se preservan.
- Conteos por estado y fuente coinciden.
- Approvals siguen abiertos; paused no generan jobs.
- El importador se puede ejecutar dos veces sin duplicar datos.

Dependencias: HU-101, HU-104.

### HU-104 Cifrado de credenciales operativas

Prioridad: P0

Como propietario quiero tokens cifrados en reposo para que un dump no permita
usar mi cuenta de LinkedIn.

Criterios de aceptacion:

- Access y refresh tokens usan AES-256-GCM con nonce por valor.
- Ciphertext incluye version de formato para rotacion.
- La llave vive solo como secret de funciones y restore.
- No se registra plaintext en errores ni auditoria.
- Existe prueba de rotacion y de fallo con llave incorrecta.

Dependencias: HU-101.

### HU-105 Respaldo y restauracion gratuitos

Prioridad: P0

Como propietario quiero backups externos probados porque Supabase Free no
incluye backups automaticos.

Criterios de aceptacion:

- GitHub Actions crea un dump nocturno del esquema `app`.
- El dump se comprime y cifra antes de subirlo como artifact.
- El workflow nunca corre con secretos en pull requests.
- La retencion inicial es 30 dias y se mantiene bajo 500 MB.
- Un restore de prueba reproduce conteos y constraints en tablas temporales.

Dependencias: HU-101, HU-104.

## Epica C: Telegram

### HU-201 Webhook autenticado e idempotente

Prioridad: P0

Como propietario quiero que el bot funcione sin polling para no depender de un
proceso residente.

Criterios de aceptacion:

- Telegram apunta a una URL HTTPS Netlify.
- Se valida `X-Telegram-Bot-Api-Secret-Token`.
- Solo `TELEGRAM_USER_ID` puede operar el bot.
- `update_id` se inserta antes de actuar y evita reprocesamiento.
- El webhook responde rapido y encola trabajo pesado.

Dependencias: HU-006, HU-101, HU-102.

### HU-202 Aprobaciones sin vencimiento

Prioridad: P0

Como propietario quiero dejar cualquier aprobacion abierta hasta decidir para
no perder propuestas aunque se encolen otras.

Criterios de aceptacion:

- `approval_pending` no tiene TTL ni job de expiracion.
- Varias aprobaciones abiertas conservan botones funcionales.
- Aprobar o cancelar valida el estado actual de ese post.
- Un callback antiguo devuelve el resultado actual si ya fue procesado.
- Las 10 aprobaciones del snapshot siguen operables despues del corte.

Dependencias: HU-201, HU-103.

### HU-203 Cambios naturales y acumulativos

Prioridad: P0

Como propietario quiero pedir cambios por Telegram para iterar el borrador sin
salir de la conversacion.

Criterios de aceptacion:

- El boton Pedir cambios persiste el modo de revision.
- Responder a una tarjeta identifica su post aunque haya otras abiertas.
- Las instrucciones se acumulan sin duplicar lineas identicas.
- Un despliegue entre instruccion y respuesta no pierde el contexto.
- La nueva tarjeta mantiene Aprobar, Pedir cambios, Otra fuente y Cancelar.

Dependencias: HU-201, HU-202, HU-404.

### HU-204 Comandos operativos

Prioridad: P1

Como propietario quiero conservar `/hoy`, `/pendientes`, `/status`, `/dia` y
`/articulos` para operar desde Telegram.

Criterios de aceptacion:

- Los comandos consultan Postgres y no memoria local.
- `/pendientes` prioriza approvals sin ocultar slots o scheduled.
- `/status` muestra DB, cola, LinkedIn, radar y ultimo backup.
- Paginacion evita mensajes que excedan limites de Telegram.

Dependencias: HU-201, HU-601.

### HU-205 Comentarios desde Telegram

Prioridad: P1

Como propietario quiero revisar y responder comentarios desde Telegram para
mantener el flujo actual.

Criterios de aceptacion:

- Un comentario nuevo se guarda antes de notificar.
- Publicar respuesta es idempotente.
- Editar o descartar sobrevive deploys.
- Fallos de LinkedIn no pierden la sugerencia ni el comentario.

Dependencias: HU-201, HU-506.

## Epica D: ejecucion serverless

### HU-301 Dispatcher de bajo consumo

Prioridad: P0

Como sistema quiero invocar Netlify solo cuando haya trabajo para conservar los
300 creditos mensuales.

Criterios de aceptacion:

- Supabase Cron comprueba jobs vencidos cada minuto en SQL.
- No se realiza HTTP cuando no existen jobs vencidos.
- El dispatcher exige firma compartida y limita el lote.
- Cada job pesado se delega a Background Function.

Dependencias: HU-102.

### HU-302 Leases, retries y dead letter

Prioridad: P0

Como sistema quiero recuperarme de timeouts y deploys sin perder ni duplicar
trabajo.

Criterios de aceptacion:

- Worker marca running solo con lease valido.
- Retry usa backoff y conserva el error redactado.
- Tras max intentos pasa a dead y notifica Telegram.
- Un job dead puede reencolarse con nueva dedupe key de intento manual.

Dependencias: HU-102, HU-301.

### HU-303 Jobs periodicos eficientes

Prioridad: P1

Como propietario quiero radar, metricas y comentarios periodicos sin agotar el
plan Free.

Criterios de aceptacion:

- Radar maintenance corre cada 6 horas como SQL ligero.
- Comentarios empiezan cada 60 minutos e incrementalmente.
- Metricas corren diario y bajo demanda.
- Los lotes terminan antes de 15 minutos y guardan cursor.
- Cadencias se pueden reducir automaticamente por presupuesto.

Dependencias: HU-301.

### HU-304 Idempotencia de efectos externos

Prioridad: P0

Como propietario quiero que retries nunca dupliquen posts, respuestas o
notificaciones criticas.

Criterios de aceptacion:

- Cada efecto tiene idempotency key persistente.
- Se escribe outbox antes de llamar al proveedor.
- Respuesta externa y estado local se reconcilian tras timeout ambiguo.
- Prueba concurrente con dos workers produce un solo efecto.

Dependencias: HU-102, HU-302.

### HU-305 Modo shadow y kill switches

Prioridad: P0

Como implementador quiero ejecutar el sistema sin efectos reales para probarlo
antes del corte.

Criterios de aceptacion:

- `PUBLISHING_ENABLED=false` bloquea posts y comentarios externos.
- `TELEGRAM_SEND_ENABLED=false` permite capturar payloads sin enviar.
- `RADAR_ENABLED` y `NONCRITICAL_JOBS_ENABLED` son independientes.
- Los bloqueos se verifican dentro del worker, no solo en UI.

Dependencias: HU-301.

## Epica E: radar y criterio editorial

### HU-401 Descubrimiento de fuentes

Prioridad: P0

Como propietario quiero que el radar busque fuentes frescas y diversas para no
depender de un calendario predisenado.

Criterios de aceptacion:

- Consulta feeds confiables y arXiv hasta 48 horas antes del slot.
- Normaliza y deduplica URLs contra todo el historial activo.
- Clasifica noticia, paper, herramienta, practica y otros formatos utiles.
- Evita lanzamientos de LLM general salvo relevancia excepcional.
- Un fallo de una fuente no cancela toda la busqueda.

Dependencias: HU-301, HU-101.

### HU-402 Decision editorial trazable

Prioridad: P0

Como propietario quiero que el radar decida la mejor opcion y explique su
criterio para revisar la calidad de sus elecciones.

Criterios de aceptacion:

- Guarda candidatas, score, ranking, seleccion y descartes.
- Decide intencion y angulo por fuente.
- Puede elegir presentar, describir, invitar, explicar, advertir, analizar o
  reflexionar.
- Otra fuente excluye la opcion anterior para ese post y vuelve a decidir.

Dependencias: HU-401, HU-403.

### HU-403 Aprendizaje historico

Prioridad: P0

Como propietario quiero que el radar aprenda de mis mejores publicaciones y de
mi voz anterior a la herramienta.

Criterios de aceptacion:

- Usa publicaciones publicadas con texto y metricas disponibles.
- Pondera likes, comentarios, shares, clicks, impresiones y engagement.
- Incluye referencias manuales/pre-herramienta.
- Contrasta posts fuertes y flojos.
- Persiste perfil, version, fecha y IDs de la muestra.

Dependencias: HU-103.

### HU-404 Copy variable y natural

Prioridad: P0

Como propietario quiero que cada copy responda a la fuente para evitar posts
repetitivos, artificiales o siempre reflexivos.

Criterios de aceptacion:

- La estructura cambia segun intencion y tipo de fuente.
- No fuerza moraleja, pregunta final o reflexion.
- No usa asteriscos, markdown, guiones artificiales ni plantillas repetidas.
- Respeta longitud y lenguaje aprendidos sin copiar frases historicas.
- Pasa validadores de limite LinkedIn y naturalidad.

Dependencias: HU-402, HU-403.

### HU-405 Multimedia y frase ancla

Prioridad: P0

Como propietario quiero usar solo material real y una apertura fuerte cuando no
haya imagen para mantener la publicacion atractiva sin generar visuales.

Criterios de aceptacion:

- No existe llamada activa a generadores de imagen.
- Solo se adjunta imagen, video o PDF proveniente de la fuente.
- Si el adjunto falla, se publica sin adjunto y no se sintetiza reemplazo.
- Sin adjunto, la primera linea recibe validacion reforzada de frase ancla.

Dependencias: HU-404.

## Epica F: LinkedIn

### HU-501 OAuth cloud y renovacion

Prioridad: P0

Como propietario quiero conectar LinkedIn a la URL cloud para que la computadora
local deje de ser necesaria.

Criterios de aceptacion:

- Redirect URI usa HTTPS de Netlify.
- `state` es aleatorio, de un solo uso y con expiracion corta.
- Tokens se cifran antes de commit.
- Refresh conserva el person URN y actualiza expiraciones.
- Fallo de auth pide reconexion sin cancelar approvals.

Dependencias: HU-006, HU-104.

### HU-502 Publicacion 30 minutos despues de aprobar

Prioridad: P0

Como propietario quiero que cada post aprobado se publique 30 minutos despues,
sin importar la hora de aprobacion.

Criterios de aceptacion:

- En una transaccion se guardan approved_at, publish_at y job.
- `publish_at` lo calcula Postgres, no el reloj del navegador o Telegram.
- Objetivo de ejecucion: entre +30:00 y +31:00 minutos.
- Aprobar dos veces devuelve el horario ya creado.
- Si el servicio estuvo pausado, procesa al reanudarse sin duplicar.

Dependencias: HU-202, HU-304, HU-501.

### HU-503 Publicacion idempotente

Prioridad: P0

Como propietario quiero una sola publicacion en LinkedIn aunque haya retries o
timeouts ambiguos.

Criterios de aceptacion:

- El post pasa por `scheduled`, `publishing` y `published`.
- Solo un worker puede entrar a publishing.
- Se guarda request fingerprint e intento antes de la llamada.
- Timeout ambiguo activa reconciliacion antes de reintentar.
- `linkedin_post_id` tiene unicidad cuando existe.

Dependencias: HU-304, HU-501.

### HU-504 Verificacion previa

Prioridad: P1

Como propietario quiero verificar vigencia y seguridad antes de publicar para
evitar compartir informacion obsoleta o rota.

Criterios de aceptacion:

- La verificacion no sobrescribe ediciones humanas.
- Un cambio valido actualiza copy y conserva instrucciones.
- Cancelar por fuente invalida notifica y no publica.
- La verificacion es idempotente y auditable.

Dependencias: HU-503, HU-401.

### HU-505 Publicacion manual y programacion web

Prioridad: P1

Como propietario quiero conservar generar, editar, publicar ahora y programar
desde el dashboard.

Criterios de aceptacion:

- Las APIs mantienen contratos compatibles con el frontend.
- Publicar ahora tambien usa outbox e idempotencia.
- Programar inserta job durable.
- Cancelar invalida jobs pendientes en una transaccion.

Dependencias: HU-503, HU-601.

### HU-506 Metricas y comentarios por HTTP

Prioridad: P1

Como propietario quiero conservar metricas y comentarios sin un navegador
residente.

Criterios de aceptacion:

- Usa APIs publicas o requests Voyager HTTP ya compatibles.
- No depende de Playwright.
- Cookies opcionales son secrets, nunca columnas publicas ni logs.
- Un fallo parcial conserva cursor y reintenta solo lo pendiente.

Dependencias: HU-501, HU-303.

## Epica G: dashboard

### HU-601 Historial y operacion diaria

Prioridad: P1

Como propietario quiero ver y operar mis posts desde web como hoy.

Criterios de aceptacion:

- Lista published, scheduled, approval_pending, radar_slot, failed y paused.
- Permite editar y cancelar estados validos.
- Muestra hora local CDMX calculada desde UTC.
- Paginacion evita cargar todo el historial en una funcion.

Dependencias: HU-005, HU-103.

### HU-602 Ajustes editoriales

Prioridad: P1

Como propietario quiero mantener mis ajustes y prompt personalizado en cloud.

Criterios de aceptacion:

- Ajustes se leen y actualizan con version optimista.
- Cambios invalidan el perfil editorial cuando corresponde.
- Valores secretos no forman parte de settings editables.

Dependencias: HU-101, HU-601.

### HU-603 Analitica y CSV

Prioridad: P1

Como propietario quiero conservar analitica y exportacion para revisar el
desempeno historico.

Criterios de aceptacion:

- Metricas agregadas coinciden con consultas de control.
- CSV conserva filtros y escapado correcto.
- Exportaciones grandes usan streaming o paginacion compatible.

Dependencias: HU-506, HU-601.

### HU-604 Salud operativa

Prioridad: P1

Como propietario quiero ver si radar, jobs, Telegram, LinkedIn y backups estan
sanos para detectar fallos sin abrir tres paneles.

Criterios de aceptacion:

- Muestra ultimo exito y ultimo error por subsistema.
- Muestra jobs due, running, retry y dead.
- No expone detalles sensibles en frontend.
- Permite reencolar un job dead con confirmacion.

Dependencias: HU-302, HU-601, HU-702.

### HU-605 Retiro de funciones locales

Prioridad: P2

Como propietario quiero que la interfaz cloud no muestre controles que ya no
tienen sentido.

Criterios de aceptacion:

- Se eliminan panel y endpoints de git pull/restart.
- X auto aparece como desactivado o fuera de alcance, sin falsas promesas.
- No quedan referencias a localhost en produccion.

Dependencias: HU-601, HU-801.

## Epica H: observabilidad y corte

### HU-701 Actualizacion de metricas eficiente

Prioridad: P1

Como propietario quiero datos de rendimiento suficientes para el aprendizaje
sin consumir innecesariamente funciones.

Criterios de aceptacion:

- Refresh diario procesa solo posts elegibles y desactualizados.
- Refresh manual de un post sigue disponible.
- Lotes guardan cursor y tiempo de ejecucion.
- El perfil se recalcula solo si cambiaron datos relevantes.

Dependencias: HU-506.

### HU-702 Logs, eventos y alertas

Prioridad: P0

Como propietario quiero enterarme de fallos criticos por Telegram y poder
reconstruir que ocurrio.

Criterios de aceptacion:

- Cada request y job tiene correlation ID.
- Eventos importantes se guardan en `app.event_log`.
- Errores de publish, radar, auth, backup y dead jobs notifican una sola vez.
- Logs tienen retencion acotada y redaccion de secretos.

Dependencias: HU-201, HU-302.

### HU-703 Ensayo shadow y reconciliacion

Prioridad: P0

Como propietario quiero comparar cloud contra local sin publicar para reducir el
riesgo del cambio.

Criterios de aceptacion:

- Cloud corre con publishing y Telegram send apagados.
- Se completa un ciclo editorial de radar a job.
- Conteos y hashes del import coinciden.
- Payload de publicacion queda capturado y revisado.
- Todas las diferencias estan explicadas antes del corte.

Dependencias: HU-001, HU-002, HU-003, HU-004, HU-005, HU-006, HU-101, HU-102, HU-103, HU-104, HU-105, HU-201, HU-202, HU-203, HU-301, HU-302, HU-304, HU-305, HU-401, HU-402, HU-403, HU-404, HU-405, HU-501, HU-502, HU-503 y HU-702.

### HU-801 Corte unico sin doble ejecucion

Prioridad: P0

Como propietario quiero cambiar a cloud sin que local y cloud publiquen al mismo
tiempo.

Criterios de aceptacion:

- Local entra en freeze y se detiene antes de registrar webhook.
- Snapshot final y delta quedan importados y reconciliados.
- Solo cloud tiene publishing habilitado.
- El webhook conserva updates pendientes.
- Smoke tests pasan antes de habilitar publicacion.

Dependencias: HU-703, HU-105, HU-802, HU-803.

### HU-802 Continuidad de tarjetas Telegram antiguas

Prioridad: P0

Como propietario quiero usar botones y respuestas de approvals ya recibidos para
no reiniciar decisiones pendientes.

Criterios de aceptacion:

- Los IDs de post se preservan.
- Callback data antiguo se procesa en el webhook nuevo.
- Respuestas con `Post #N` funcionan como fallback.
- No se obliga a reenviar ni cerrar approvals.

Dependencias: HU-201, HU-202, HU-103.

### HU-803 Reversa probada

Prioridad: P0

Como propietario quiero volver temporalmente a local si cloud falla durante el
corte.

Criterios de aceptacion:

- Cloud puede bloquear efectos externos con un solo secret.
- Existe export de cambios cloud posteriores al snapshot.
- Polling local puede retomarse sin perder updates.
- Se prueba la secuencia sin realizar una publicacion real.

Dependencias: HU-105, HU-305, HU-703.

### HU-804 Cierre de migracion

Prioridad: P1

Como propietario quiero retirar la dependencia de mi computadora una vez que
cloud demuestre estabilidad.

Criterios de aceptacion:

- Primer approval, revision, publish, metric refresh y backup cloud fueron
  confirmados.
- El supervisor local queda detenido y deshabilitado.
- SQLite final se conserva cifrado como snapshot de archivo.
- Runbook y `PROGRESS.md` reflejan el estado real.

Dependencias: HU-801, HU-802, HU-803.
