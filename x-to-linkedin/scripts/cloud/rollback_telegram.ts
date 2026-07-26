import { requiredEnv } from "../../cloud/src/env.js";

const token = requiredEnv("TELEGRAM_BOT_TOKEN");
const response = await fetch(`https://api.telegram.org/bot${token}/deleteWebhook`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ drop_pending_updates: false }),
  signal: AbortSignal.timeout(10_000)
});
const payload = (await response.json()) as { ok?: boolean; description?: string };
if (!response.ok || !payload.ok) {
  throw new Error(`Telegram rejected webhook removal: ${payload.description ?? response.status}`);
}
process.stdout.write(JSON.stringify({ webhook_removed: true, updates_preserved: true }) + "\n");
