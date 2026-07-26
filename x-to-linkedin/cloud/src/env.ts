type NetlifyRuntime = {
  env?: {
    get(name: string): string | undefined;
  };
};

function runtimeValue(name: string): string | undefined {
  const runtime = (globalThis as typeof globalThis & { Netlify?: NetlifyRuntime }).Netlify;
  return runtime?.env?.get(name) ?? process.env[name];
}

export function env(name: string, fallback = ""): string {
  return runtimeValue(name)?.trim() || fallback;
}

export function requiredEnv(name: string): string {
  const value = env(name);
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export function envBoolean(name: string, fallback = false): boolean {
  const value = runtimeValue(name);
  if (value === undefined || value === "") return fallback;
  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

export function envInteger(name: string, fallback: number): number {
  const parsed = Number.parseInt(env(name), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export const switches = {
  publishingEnabled: () => envBoolean("PUBLISHING_ENABLED", false),
  telegramSendEnabled: () => envBoolean("TELEGRAM_SEND_ENABLED", false),
  radarEnabled: () => envBoolean("RADAR_ENABLED", true),
  noncriticalJobsEnabled: () => envBoolean("NONCRITICAL_JOBS_ENABLED", true),
  migrationFreeze: () => envBoolean("MIGRATION_FREEZE", false)
};
