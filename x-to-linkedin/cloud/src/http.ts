import { randomUUID } from "node:crypto";
import { redact } from "./redaction.js";

export class AppError extends Error {
  constructor(
    message: string,
    readonly status = 500,
    readonly code = "internal_error"
  ) {
    super(message);
  }
}

export function requestId(request: Request): string {
  const candidate = request.headers.get("x-request-id")?.trim() ?? "";
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    candidate
  )
    ? candidate
    : randomUUID();
}

function responseHeaders(id: string): Headers {
  return new Headers({
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-request-id": id,
    "x-content-type-options": "nosniff"
  });
}

export function json(
  payload: unknown,
  options: { status?: number; requestId: string; headers?: HeadersInit }
): Response {
  const headers = responseHeaders(options.requestId);
  if (options.headers) {
    new Headers(options.headers).forEach((value, key) => headers.set(key, value));
  }
  return new Response(JSON.stringify(payload), {
    status: options.status ?? 200,
    headers
  });
}

export function methodNotAllowed(
  _request: Request,
  allowed: string[],
  id: string
): Response {
  return json(
    { error: "method_not_allowed", allowed },
    {
      status: 405,
      requestId: id,
      headers: { allow: allowed.join(", ") }
    }
  );
}

export async function parseJson<T>(
  request: Request,
  maxBytes = 128 * 1024
): Promise<T> {
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > maxBytes) {
    throw new AppError("Payload too large", 413, "payload_too_large");
  }
  const text = await request.text();
  if (Buffer.byteLength(text, "utf8") > maxBytes) {
    throw new AppError("Payload too large", 413, "payload_too_large");
  }
  try {
    return JSON.parse(text || "{}") as T;
  } catch {
    throw new AppError("Invalid JSON", 400, "invalid_json");
  }
}

export function toErrorResponse(error: unknown, id: string): Response {
  if (error instanceof AppError) {
    return json(
      {
        error: error.code,
        message: error.message,
        detail: error.message,
        request_id: id
      },
      { status: error.status, requestId: id }
    );
  }
  console.error(`request_id=${id} error=${redact(error)}`);
  return json(
    {
      error: "internal_error",
      message: "Unexpected server error",
      detail: "Unexpected server error",
      request_id: id
    },
    { status: 500, requestId: id }
  );
}
