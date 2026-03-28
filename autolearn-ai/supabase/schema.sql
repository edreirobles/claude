-- Run this in your Supabase project: SQL Editor → New query → paste → Run

-- Tools catalog (cached from discovery)
create table if not exists tools (
  id text primary key,
  name text not null,
  url text not null,
  description text,
  tags text[] default '{}',
  icon text default '🔧',
  sponsored boolean default false,
  source text default 'manual',
  created_at timestamptz default now()
);

-- Tutorials (cached so they're not regenerated)
create table if not exists tutorials (
  id uuid primary key default gen_random_uuid(),
  tool_id text references tools(id),
  tool_name text not null,
  need text not null,
  level text default 'beginner',
  duration_minutes int default 10,
  slides jsonb not null default '[]',
  formats text[] default '{deck,steps}',
  -- Cache key: same need + tool + level → return existing tutorial
  cache_key text generated always as (
    md5(lower(need) || '|' || tool_id || '|' || level)
  ) stored,
  created_at timestamptz default now()
);

create unique index if not exists tutorials_cache_key_idx on tutorials(cache_key);

-- Screenshots stored in Supabase Storage bucket "screenshots"
-- Videos stored in Supabase Storage bucket "videos"

-- Enable Row Level Security
alter table tools enable row level security;
alter table tutorials enable row level security;

-- Public read access
create policy "Anyone can read tools" on tools for select using (true);
create policy "Anyone can read tutorials" on tutorials for select using (true);

-- Only service role can write (API routes use service role key)
create policy "Service role inserts tools" on tools for insert
  with check (auth.role() = 'service_role');
create policy "Service role inserts tutorials" on tutorials for insert
  with check (auth.role() = 'service_role');

-- Seed a few tools
insert into tools (id, name, url, description, tags, icon, sponsored, source) values
  ('make', 'Make', 'https://make.com', 'Visual automation platform. Connect apps and automate workflows without code.', array['automation','no-code','integrations'], '⚡', false, 'manual'),
  ('zapier', 'Zapier', 'https://zapier.com', 'Connect 6,000+ apps and automate repetitive tasks.', array['automation','no-code','popular'], '🔗', false, 'manual'),
  ('n8n', 'n8n', 'https://n8n.io', 'Open-source workflow automation. Self-host for full control.', array['automation','open-source'], '🔧', false, 'manual'),
  ('claude', 'Claude', 'https://claude.ai', 'AI assistant for analysis, writing, coding, and reasoning.', array['ai','writing','coding'], '🤖', false, 'manual'),
  ('midjourney', 'Midjourney', 'https://midjourney.com', 'AI image generation from text descriptions.', array['ai','images','design'], '🎨', false, 'manual'),
  ('notion-ai', 'Notion AI', 'https://notion.so', 'AI built into your workspace for writing and organizing.', array['productivity','writing','ai'], '📝', false, 'manual')
on conflict (id) do nothing;
