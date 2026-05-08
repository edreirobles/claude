/* ── Supabase Auth helpers ──────────────────────────────── */

let _sb = null;

function initSupabase() {
  if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) return null;
  if (_sb) return _sb;
  const { createClient } = supabase; // from CDN
  _sb = createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);
  return _sb;
}

async function getSession() {
  const sb = initSupabase();
  if (!sb) return null;
  const { data: { session } } = await sb.auth.getSession();
  return session;
}

async function getAuthHeaders() {
  if (!window.AUTH_ENABLED) return {};
  const session = await getSession();
  if (!session) return {};
  return { "Authorization": `Bearer ${session.access_token}` };
}

async function requireAuth() {
  if (!window.AUTH_ENABLED) return { user: { id: "local", email: "dev@local" } };
  const session = await getSession();
  if (!session) { window.location.href = "/login"; return null; }
  return session;
}

async function signInWithEmail(email) {
  const sb = initSupabase();
  if (!sb) return new Error("Auth not configured");
  const { error } = await sb.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
  });
  return error;
}

async function signInWithGoogle() {
  const sb = initSupabase();
  if (!sb) return new Error("Auth not configured");
  const { error } = await sb.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  });
  return error;
}

async function signOut() {
  const sb = initSupabase();
  if (sb) await sb.auth.signOut();
  window.location.href = "/login";
}

async function getCurrentUser() {
  const session = await getSession();
  return session?.user || null;
}
