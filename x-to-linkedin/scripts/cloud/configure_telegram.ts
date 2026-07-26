import { requiredEnv } from "../../cloud/src/env.js";

const origin = requiredEnv("APP_ORIGIN").replace(/\/+$/, "");
const token = requiredEnv("TELEGRAM_BOT_TOKEN");
const secret = requiredEnv("TELEGRAM_WEBHOOK_SECRET");
const response = await fetch(`https://api.telegram.org/bot${token}/setWebhook`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    url: `${origin}/api/telegram/webhook`,
    secret_token: secret,
    allowed_updates: ["message", "callback_query"],
    drop_pending_updates: false,
    max_connections: 10
  }),
  signal: AbortSignal.timeout(10_000)
});
const payload = (await response.json()) as { ok?: boolean; description?: string };
if (!response.ok || !payload.ok) {
  throw new Error(`Telegram rejected webhook setup: ${payload.description ?? response.status}`);
}
const infoResponse = await fetch(`https://api.telegram.org/bot${token}/getWebhookInfo`, {
  signal: AbortSignal.timeout(10_000)
});
const info = (await infoResponse.json()) as {
  ok?: boolean;
  result?: { url?: string; has_custom_certificate?: boolean; pending_update_count?: number };
};
if (!info.ok || info.result?.url !== `${origin}/api/telegram/webhook`) {
  throw new Error("Telegram webhook verification failed");
}
process.stdout.write(
  JSON.stringify({
    configured: true,
    url: info.result.url,
    pending_updates: info.result.pending_update_count ?? 0
  }) + "\n"
);
