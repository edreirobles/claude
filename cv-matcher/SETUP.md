# CV Matcher — Setup Guide

This guide walks you through everything you need to go from zero to a live, paid app. No coding experience required. Just follow each step in order.

---

## What you'll set up

1. **Supabase** — handles user login and stores data
2. **Stripe** — handles payments
3. **Railway** — hosts your app on the internet
4. **Environment variables** — connects all the pieces

Total time: about 30–45 minutes.

---

## Part 1 — Supabase (Auth & Database)

### 1.1 Create a Supabase account
1. Go to [supabase.com](https://supabase.com) and click **Start your project**
2. Sign up with GitHub or email
3. Click **New project**
4. Give it a name (e.g. `cv-matcher`), choose a region close to your users, set a database password (save it), click **Create project**
5. Wait ~2 minutes for the project to be ready

### 1.2 Run the database setup script
1. In your Supabase project, click **SQL Editor** in the left sidebar
2. Click **New query**
3. Open the file `supabase_setup.sql` from this project folder
4. Copy its entire contents and paste it into the SQL Editor
5. Click **Run** (or press Ctrl+Enter)
6. You should see "Success. No rows returned" — that means it worked

### 1.3 Enable Email (Magic Link) login
1. In Supabase, go to **Authentication → Providers**
2. Make sure **Email** is enabled (it is by default)
3. Go to **Authentication → Email Templates** if you want to customize the magic link email

### 1.4 Get your API keys
1. Go to **Project Settings** (gear icon at the bottom left) → **API**
2. Copy these three values — you'll need them later:
   - **Project URL** → this is your `SUPABASE_URL`
   - **anon / public key** → this is your `SUPABASE_ANON_KEY`
   - **service_role / secret key** → this is your `SUPABASE_SERVICE_ROLE_KEY`

   > ⚠️ Keep the service_role key secret. Never share it or put it in public code.

---

## Part 2 — Stripe (Payments)

### 2.1 Create a Stripe account
1. Go to [stripe.com](https://stripe.com) and click **Start now**
2. Complete the registration and verify your email
3. To accept real payments, you'll need to complete business verification (takes a few days). For testing, you can use test mode.

### 2.2 Create your products
You need two products: a one-time credit pack and a monthly subscription.

**Credit pack (one-time)**
1. In Stripe, go to **Products** → **+ Add product**
2. Name: `CV Credits Pack` (or whatever you like)
3. Pricing: **One time** — set your price (e.g. $9.00 USD)
4. Click **Save product**
5. On the product page, copy the **Price ID** (starts with `price_`) — save it as `STRIPE_PRICE_CREDITS`

**Monthly subscription**
1. Click **+ Add product** again
2. Name: `CV Matcher Pro`
3. Pricing: **Recurring** → **Monthly** — set your price (e.g. $19.00 USD)
4. Click **Save product**
5. Copy the **Price ID** — save it as `STRIPE_PRICE_MONTHLY`

### 2.3 Get your secret key
1. Go to **Developers → API keys**
2. Copy the **Secret key** (starts with `sk_live_` for live, `sk_test_` for test mode)
3. Save it as `STRIPE_SECRET_KEY`

### 2.4 Set up the webhook (after deploying to Railway)
> You'll come back to this step after Part 3.

1. Go to **Developers → Webhooks** → **+ Add endpoint**
2. Endpoint URL: `https://YOUR-APP-URL.up.railway.app/api/stripe-webhook`
3. Select events to listen to:
   - `checkout.session.completed`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
4. Click **Add endpoint**
5. Click on the new endpoint → click **Reveal** under **Signing secret**
6. Save it as `STRIPE_WEBHOOK_SECRET`

---

## Part 3 — Railway (Hosting)

### 3.1 Create a Railway account
1. Go to [railway.app](https://railway.app) and sign up with GitHub

### 3.2 Deploy the app
1. Click **New Project → Deploy from GitHub repo**
2. Connect your GitHub account if prompted
3. Select the `claude` repository and choose the branch `claude/create-cv-matcher-repo-EPoYN`
   - Railway will auto-detect Python and build from `cv-matcher/`
   - If it doesn't, set the **Root Directory** to `cv-matcher` in project settings
4. Click **Deploy**

### 3.3 Set environment variables
1. In your Railway project, click on your service → **Variables** tab
2. Add each variable below (click **+ New Variable** for each):

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic key |
| `SUPABASE_URL` | From Part 1.4 |
| `SUPABASE_ANON_KEY` | From Part 1.4 |
| `SUPABASE_SERVICE_ROLE_KEY` | From Part 1.4 |
| `STRIPE_SECRET_KEY` | From Part 2.3 |
| `STRIPE_WEBHOOK_SECRET` | From Part 2.4 (add after webhook is created) |
| `STRIPE_PRICE_CREDITS` | Price ID from Part 2.2 |
| `STRIPE_PRICE_MONTHLY` | Price ID from Part 2.2 |
| `APP_URL` | Your Railway URL (e.g. `https://cv-matcher.up.railway.app`) |
| `FREE_GENERATIONS_LIMIT` | `3` |
| `CREDITS_PER_PACK` | `10` |
| `PRICE_CREDITS_DISPLAY` | `$9` |
| `PRICE_MONTHLY_DISPLAY` | `$19/mo` |

3. After saving variables, Railway will redeploy automatically

### 3.4 Get your public URL
1. Go to your Railway service → **Settings** → **Networking**
2. Click **Generate Domain** if you don't have one yet
3. Copy the URL — this is your `APP_URL`

---

## Part 4 — Final connections

### 4.1 Update Supabase with your app URL
1. In Supabase → **Authentication → URL Configuration**
2. Set **Site URL** to your Railway URL (e.g. `https://cv-matcher.up.railway.app`)
3. Under **Redirect URLs**, add: `https://cv-matcher.up.railway.app/auth/callback`
4. Click **Save**

### 4.2 Complete the Stripe webhook (if not done yet)
If you skipped Part 2.4 earlier because you didn't have your URL yet:
1. Go back to Stripe → **Developers → Webhooks → + Add endpoint**
2. Use your Railway URL: `https://your-app.up.railway.app/api/stripe-webhook`
3. Follow the rest of the steps from Part 2.4
4. Add `STRIPE_WEBHOOK_SECRET` to Railway variables and redeploy

### 4.3 Test the full flow
1. Open your app URL
2. Click **Sign in** → enter your email → check your email for the magic link → click it
3. You should be logged in and see "3 free left" badge
4. Try generating a CV — it should work
5. After 3 generations, the paywall should appear
6. Test a Stripe payment using card number `4242 4242 4242 4242` (any future date, any CVC)

---

## Running locally (without Supabase/Stripe)

The app works fully offline for development without any external services:

```bash
cd cv-matcher
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8001
```

Open `http://localhost:8001` — auth and payments are disabled automatically, and SQLite is used instead of Supabase.

---

## Costs summary

| Service | Free tier | Paid |
|---|---|---|
| Supabase | 500 MB DB, 1 GB storage, 50k MAU — free | ~$25/mo if you grow |
| Stripe | Free to use | 2.9% + $0.30 per transaction |
| Railway | $5/mo Hobby plan | Pay for what you use |
| Anthropic API | Pay per use | ~$0.07 per CV generated |

For a small operation (<100 users/month), total infrastructure cost is about **$5–10/month**.
