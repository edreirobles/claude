-- ============================================================
-- CV Matcher — Supabase Setup Script
-- Run this entire file in your Supabase SQL Editor once.
-- ============================================================

-- ── 1. PROFILES TABLE ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.profiles (
  id                      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email                   TEXT,
  plan                    TEXT NOT NULL DEFAULT 'free',   -- free | credits | monthly
  credits                 INT  NOT NULL DEFAULT 0,
  free_generations_used   INT  NOT NULL DEFAULT 0,
  stripe_customer_id      TEXT,
  subscription_id         TEXT,
  subscription_end        TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 2. GENERATIONS TABLE ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.generations (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  status              TEXT NOT NULL DEFAULT 'processing',  -- processing | completed | failed
  job_url             TEXT,
  job_text            TEXT,
  job_title           TEXT,
  company             TEXT,
  output_language     TEXT DEFAULT 'auto',
  pdf_storage_path    TEXT,
  output_pdf_path     TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 3. ROW LEVEL SECURITY ────────────────────────────────────
ALTER TABLE public.profiles    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generations ENABLE ROW LEVEL SECURITY;

-- Profiles: users can only read/update their own row
CREATE POLICY "profiles_self_select" ON public.profiles
  FOR SELECT USING (auth.uid() = id);

CREATE POLICY "profiles_self_update" ON public.profiles
  FOR UPDATE USING (auth.uid() = id);

-- Generations: users can only see their own generations
CREATE POLICY "generations_self_select" ON public.generations
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "generations_self_insert" ON public.generations
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "generations_self_update" ON public.generations
  FOR UPDATE USING (auth.uid() = user_id);

-- Service role bypasses RLS (used by backend with SUPABASE_SERVICE_ROLE_KEY)
-- No extra policy needed — service_role always bypasses RLS by default.

-- ── 4. AUTO-CREATE PROFILE ON SIGNUP ─────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  INSERT INTO public.profiles (id, email)
  VALUES (NEW.id, NEW.email)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ── 5. UPDATED_AT TRIGGER ─────────────────────────────────────
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

CREATE TRIGGER profiles_updated_at
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER generations_updated_at
  BEFORE UPDATE ON public.generations
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ── 6. STORAGE BUCKET ────────────────────────────────────────
-- Create the bucket for generated PDFs.
INSERT INTO storage.buckets (id, name, public)
VALUES ('cv-pdfs', 'cv-pdfs', false)
ON CONFLICT (id) DO NOTHING;

-- Allow authenticated users to upload their own PDFs
CREATE POLICY "cv_pdfs_insert" ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (bucket_id = 'cv-pdfs' AND (storage.foldername(name))[1] = auth.uid()::text);

-- Allow authenticated users to read their own PDFs
CREATE POLICY "cv_pdfs_select" ON storage.objects
  FOR SELECT TO authenticated
  USING (bucket_id = 'cv-pdfs' AND (storage.foldername(name))[1] = auth.uid()::text);

-- Allow service role full access (backend uses service role key)
-- No explicit policy needed — service_role bypasses RLS.

-- ── DONE ─────────────────────────────────────────────────────
-- You can verify by running:
--   SELECT * FROM public.profiles;
--   SELECT * FROM public.generations;
