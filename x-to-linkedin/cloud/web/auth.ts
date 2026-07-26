import { createClient, type Session } from "@supabase/supabase-js";

type CloudConfig = {
  supabaseUrl: string;
  supabasePublishableKey: string;
  appEnv: string;
};

declare global {
  interface Window {
    __CLOUD_CONFIG__?: CloudConfig;
  }
}

const config = window.__CLOUD_CONFIG__;
const nativeFetch = window.fetch.bind(window);

if (!config?.supabaseUrl || !config.supabasePublishableKey) {
  const status = document.getElementById("cloud-login-status");
  if (status) {
    status.textContent = "Este entorno no tiene Supabase configurado.";
    status.classList.add("is-error");
  }
  throw new Error("Missing public Supabase configuration");
}

const supabase = createClient(config.supabaseUrl, config.supabasePublishableKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true
  }
});

let activeSession: Session | null = null;

async function syncServerCookie(session: Session): Promise<void> {
  const response = await nativeFetch("/api/session", {
    method: "POST",
    headers: {
      authorization: `Bearer ${session.access_token}`,
      "content-type": "application/json",
      "x-app-request": "1"
    },
    body: "{}"
  });
  if (!response.ok) {
    throw new Error("La cuenta no esta autorizada para este dashboard.");
  }
}

async function resolveSession(): Promise<Session | null> {
  const { data, error } = await supabase.auth.getSession();
  if (error) {
    throw error;
  }
  activeSession = data.session;
  if (activeSession) {
    await syncServerCookie(activeSession);
  }
  return activeSession;
}

function installFetchProtection(ready: Promise<Session | null>): void {
  window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const session = await ready;
    const url = new URL(
      typeof input === "string" ? input : input instanceof URL ? input.href : input.url,
      window.location.origin
    );
    if (url.origin !== window.location.origin) {
      return nativeFetch(input, init);
    }
    const headers = new Headers(init.headers);
    if (session?.access_token) {
      headers.set("authorization", `Bearer ${session.access_token}`);
    }
    if ((init.method ?? "GET").toUpperCase() !== "GET") {
      headers.set("x-app-request", "1");
    }
    return nativeFetch(input, { ...init, headers });
  };
}

function setStatus(message: string, error = false): void {
  const status = document.getElementById("cloud-login-status");
  if (!status) return;
  status.textContent = message;
  status.classList.toggle("is-error", error);
}

async function finishLogin(session: Session | null): Promise<void> {
  if (!session) {
    setStatus("No se recibio una sesion valida.", true);
    return;
  }
  await syncServerCookie(session);
  window.location.assign("/");
}

function configureLoginPage(): void {
  const form = document.getElementById("cloud-login-form") as HTMLFormElement | null;
  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = (document.getElementById("cloud-email") as HTMLInputElement).value.trim();
    const password = (document.getElementById("cloud-password") as HTMLInputElement).value;
    setStatus("Validando acceso...");
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      setStatus(error.message, true);
      return;
    }
    await finishLogin(data.session);
  });

  document.getElementById("cloud-magic-link")?.addEventListener("click", async () => {
    const email = (document.getElementById("cloud-email") as HTMLInputElement).value.trim();
    if (!email) {
      setStatus("Escribe primero tu correo.", true);
      return;
    }
    setStatus("Enviando enlace...");
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/login.html` }
    });
    setStatus(error ? error.message : "Revisa tu correo para continuar.", Boolean(error));
  });
}

function configureDashboard(): void {
  document.getElementById("cloud-logout")?.addEventListener("click", async () => {
    await nativeFetch("/api/session", {
      method: "DELETE",
      headers: { "x-app-request": "1" }
    });
    await supabase.auth.signOut();
    window.location.assign("/login.html");
  });

  document.addEventListener("click", async (event) => {
    const target = (event.target as Element | null)?.closest("[data-cloud-linkedin-connect]");
    if (!target) return;
    event.preventDefault();
    const response = await window.fetch("/api/auth/linkedin/start", {
      method: "POST"
    });
    const payload = (await response.json()) as { url?: string; error?: string };
    if (!response.ok || !payload.url) {
      window.alert(payload.error ?? "No se pudo iniciar LinkedIn.");
      return;
    }
    window.location.assign(payload.url);
  });
}

const ready = resolveSession();
installFetchProtection(ready);
configureLoginPage();

void ready
  .then((session) => {
    if (document.getElementById("cloud-login-form")) {
      if (session) void finishLogin(session);
      return;
    }
    if (!session) {
      window.location.assign("/login.html");
      return;
    }
    configureDashboard();
  })
  .catch((error: unknown) => {
    setStatus(error instanceof Error ? error.message : "No se pudo validar la sesion.", true);
    if (!document.getElementById("cloud-login-form")) {
      window.location.assign("/login.html");
    }
  });

supabase.auth.onAuthStateChange((_event, session) => {
  activeSession = session;
  if (session) void syncServerCookie(session);
});
