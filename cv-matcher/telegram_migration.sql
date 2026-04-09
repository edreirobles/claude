-- ============================================================
-- CV Matcher — Telegram Bot Migration
-- Run this in your Supabase SQL Editor (once).
-- ============================================================

CREATE TABLE IF NOT EXISTS public.telegram_profiles (
  telegram_user_id  TEXT PRIMARY KEY,
  username          TEXT,
  plan              TEXT NOT NULL DEFAULT 'free',
  credits           INT  NOT NULL DEFAULT 0,
  free_generations_used INT NOT NULL DEFAULT 0,
  stripe_customer_id TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.telegram_generations (
  id                TEXT PRIMARY KEY,
  telegram_user_id  TEXT NOT NULL REFERENCES public.telegram_profiles(telegram_user_id) ON DELETE CASCADE,
  status            TEXT NOT NULL DEFAULT 'completed',
  job_text          TEXT,
  job_title         TEXT,
  company           TEXT,
  output_language   TEXT DEFAULT 'auto',
  pdf_path          TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- No RLS needed — backend always uses service_role key for telegram tables.
