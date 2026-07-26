# Evidencia de implementacion

Fecha: 2026-07-25

## Pruebas

| Comando | Resultado |
| --- | --- |
| `npm run typecheck` | OK |
| `npm run test` | 7 archivos, 23 pruebas, todas verdes |
| `python -m unittest tests.test_phase0_characterization -v` | 10 pruebas verdes |
| `npm run build` | OK |
| `netlify build --offline` | 8 Functions empaquetadas; Edge detectada |
| `python scripts/audit_phase0_security.py` | Arbol 0; historia 1 pendiente |

El empaquetador Edge local no puede descargar un tipo de Netlify por el
certificado corporativo `UnknownIssuer`. La Function `dashboard` protege `/`
como segunda barrera y fue validada en Netlify Dev.

## HTTP remoto

Sitio: `https://x2li-radar-victor.netlify.app`

| Prueba | Resultado |
| --- | --- |
| `GET /api/health` | 200 |
| `POST /api/health` | 405, `Allow: GET` |
| `GET /api/posts` sin sesion | 401 |
| Cabeceras | CSP, HSTS, frame deny, no-sniff, permissions policy |
| Efectos externos | Todos apagados por variables Netlify |

El deploy remoto activo no contiene aun la Function `dashboard`; el siguiente
build fue rechazado con `Skipped due to account credit usage exceeded`. No se
habilito gasto para resolverlo.

## Datos

Snapshot ensayado:
`migration-artifacts/snapshot-20260725T221057Z`

- 558 posts
- 172 comentarios
- 132 likes de X
- 1 settings
- 1 token cifrado
- Checksums SHA-256 por archivo
- Sin SQLite temporal residual
- Sin token plaintext en el artefacto

## Compatibilidad LinkedIn

La capa cloud usa las APIs versionadas vigentes:

- `POST /rest/posts`
- `POST /rest/images?action=initializeUpload`
- `POST /rest/documents?action=initializeUpload`
- OAuth 3-legged con `w_member_social`

Se retiro el uso cloud de `ugcPosts` y `assets`. La reconciliacion por lectura
requiere `r_member_social`, que es restringido, y se habilita solo con
`LINKEDIN_READ_SCOPE_ENABLED=true`.

Fuentes:

- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/documents-api
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
