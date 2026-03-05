# Deploy en Railway — Guía paso a paso

## Requisitos previos
- Cuenta en [railway.app](https://railway.app) (gratuita para empezar)
- Cuenta de Stripe con un producto creado
- API Key de Anthropic

---

## Paso 1 — Crear el proyecto en Railway

1. Entra a [railway.app](https://railway.app) → **New Project**
2. Elige **Deploy from GitHub repo**
3. Conecta tu cuenta de GitHub y selecciona este repositorio
4. Railway detectará el `Dockerfile` automáticamente

> Si el repo es monorepo (carpeta `saas/` dentro), en Railway ve a:
> **Settings → Source → Root Directory** → escribe `saas`

---

## Paso 2 — Agregar PostgreSQL

1. En tu proyecto de Railway, haz clic en **+ New**
2. Selecciona **Database → PostgreSQL**
3. Railway crea la base de datos y agrega `DATABASE_URL` automáticamente a tu servicio

No necesitas hacer nada más. La app detecta el formato de Railway y usa `asyncpg`.

---

## Paso 3 — Variables de entorno

En Railway → tu servicio → **Variables**, agrega:

```
SECRET_KEY          → genera con: python -c "import secrets; print(secrets.token_hex(32))"
ANTHROPIC_API_KEY   → sk-ant-...  (de console.anthropic.com)
STRIPE_SECRET_KEY   → sk_live_... (de dashboard.stripe.com → API keys)
STRIPE_WEBHOOK_SECRET → whsec_... (ver Paso 5)
STRIPE_PRICE_ID_MONTHLY → price_... (ver abajo)
APP_URL             → https://tu-app.railway.app  (lo verás después del primer deploy)
ENVIRONMENT         → production
```

> `DATABASE_URL` ya la agrega Railway automáticamente en el Paso 2.

### Cómo crear el producto en Stripe

1. Stripe Dashboard → **Products** → **Add product**
2. Nombre: "X to LinkedIn Pro"
3. Precio: $19 → Recurring → Monthly
4. Guarda el `Price ID` (empieza con `price_...`) → eso es `STRIPE_PRICE_ID_MONTHLY`

---

## Paso 4 — Primer deploy

1. Haz push al repositorio (Railway despliega automáticamente con cada push)
2. En Railway verás los logs en tiempo real
3. Espera a que aparezca: `Application startup complete`
4. Copia la URL pública de tu app (algo como `https://saas-production-xxxx.railway.app`)
5. Actualiza la variable `APP_URL` con esa URL

---

## Paso 5 — Configurar webhook de Stripe

1. Stripe Dashboard → **Developers → Webhooks** → **Add endpoint**
2. URL del endpoint: `https://TU-URL.railway.app/billing/webhook`
3. Eventos a escuchar:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
4. Stripe te da un `Signing secret` (empieza con `whsec_...`)
5. Cópialo en Railway como `STRIPE_WEBHOOK_SECRET`

---

## Paso 6 — Dominio personalizado (opcional)

1. Railway → tu servicio → **Settings → Networking → Custom Domain**
2. Agrega tu dominio (ej: `app.tudominio.com`)
3. Railway te da los registros DNS para agregar en tu proveedor de dominio
4. Actualiza `APP_URL` con el nuevo dominio

---

## Verificar que todo funciona

```
https://TU-URL.railway.app/health        → {"status":"ok"}
https://TU-URL.railway.app/docs          → Documentación interactiva de la API
https://TU-URL.railway.app/              → Landing page
https://TU-URL.railway.app/app/          → Dashboard (registro/login)
```

---

## Costos estimados

| Servicio | Costo |
|----------|-------|
| Railway (Hobby plan) | $5/mes |
| PostgreSQL en Railway | Incluido |
| Anthropic (Claude) | ~$0.01 por post generado |
| Stripe | 2.9% + $0.30 por transacción |

Con 10 clientes pagando $19/mes → **$190/mes de ingreso**
Costo operativo → ~$10-15/mes
**Margen: ~92%**

---

## Variables de entorno de desarrollo local

```bash
cp .env.example .env
# Edita .env con tus valores de prueba (usar sk_test_... de Stripe)
./start.sh
```
