import type { Config } from "@netlify/functions";
import {
  processTelegramUpdate,
  type TelegramUpdate,
  validTelegramSecret
} from "../src/telegram.js";
import {
  json,
  methodNotAllowed,
  parseJson,
  requestId,
  toErrorResponse
} from "../src/http.js";

export default async function handler(request: Request): Promise<Response> {
  const id = requestId(request);
  if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
  if (!validTelegramSecret(request.headers.get("x-telegram-bot-api-secret-token"))) {
    return json(
      { error: "unauthorized", request_id: id },
      { status: 401, requestId: id }
    );
  }
  try {
    const update = await parseJson<TelegramUpdate>(request, 128 * 1024);
    const result = await processTelegramUpdate(update);
    return json({ ok: true, ...result, request_id: id }, { requestId: id });
  } catch (error) {
    return toErrorResponse(error, id);
  }
}

export const config: Config = {
  path: "/api/telegram/webhook"
};
