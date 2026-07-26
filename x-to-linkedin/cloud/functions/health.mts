import type { Config, Context } from "@netlify/functions";
import { env, switches } from "../src/env.js";
import { json, methodNotAllowed, requestId } from "../src/http.js";

export default async (request: Request, _context: Context): Promise<Response> => {
  const id = requestId(request);
  if (request.method !== "GET") {
    return methodNotAllowed(request, ["GET"], id);
  }
  return json(
    {
      status: "ok",
      version: env("COMMIT_REF", "local"),
      environment: env("APP_ENV", "preview"),
      publishing_enabled:
        env("APP_ENV", "preview") === "production"
          ? switches.publishingEnabled()
          : false,
      request_id: id
    },
    { requestId: id }
  );
};

export const config: Config = {
  path: "/api/health"
};
