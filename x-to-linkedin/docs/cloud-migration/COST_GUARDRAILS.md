# Guardas de costo cero

Fecha de verificacion: 2026-07-25.

## Restricciones

- Netlify debe permanecer en Free, sin auto recharge, Pro, add-ons, dominio
  pagado ni AI Gateway.
- Supabase debe permanecer en Free y usar solo un proyecto para produccion.
- No se incorpora ningun proveedor que requiera tarjeta o cobro por excedente.
- La aplicacion local sigue siendo produccion hasta completar el corte.

Netlify Free ofrece 300 creditos mensuales y aplica un limite duro. Supabase Free
ofrece 500 MB de base y 5 GB de egress; no incluye backups automaticos.

Fuentes:

- https://www.netlify.com/pricing/
- https://supabase.com/pricing

## Presupuesto Netlify

Estimacion minima mensual:

`15 * deploys_produccion + 10 * GB_hora_funciones + 2 * requests/10000`

Se agregara cualquier otra categoria que muestre el panel antes de tomar una
decision de consumo. Los Deploy Previews se agrupan y se evita desplegar por cada
commit.

| Nivel | Creditos | Accion |
| --- | ---: | --- |
| 50% | 150 | Avisar por Telegram y revisar tendencia |
| 70% | 210 | Detener deploys no esenciales y reducir radar auxiliar |
| 85% | 255 | Suspender metricas y comentarios automaticos |
| 90% | 270 | Conservar solo Telegram, aprobacion y publicacion |
| 100% | 300 | Aceptar la pausa dura; no habilitar cobro |

## Presupuesto Supabase

| Recurso | Aviso | Accion de contencion |
| --- | ---: | --- |
| Base de datos | 350 MB | Purgar auditoria prescindible y revisar indices |
| Base de datos | 425 MB | Detener ingesta auxiliar |
| Egress | 3.5 GB | Reducir consultas de dashboard y metricas |
| Egress | 4.25 GB | Conservar solo operaciones esenciales |

Los backups cifrados salen a GitHub Actions porque el plan Free no ofrece backup
automatico.

La medicion, degradacion y alertas ya estan implementadas en
`cloud/src/cost.ts` y el job `cost_monitor`. El 2026-07-25 Netlify rechazo un
build con `Skipped due to account credit usage exceeded`; esto confirma el
limite duro de la cuenta. Se espera la renovacion del ciclo y no se habilita
compra de creditos.
