import type { Config, Context } from "@netlify/functions";
import {
  bearerToken,
  clearSessionCookie,
  requireMutationGuard,
  requireUser,
  sessionCookie
} from "../src/auth.js";
import {
  json,
  methodNotAllowed,
  requestId,
  toErrorResponse
} from "../src/http.js";

export default async (request: Request, _context: Context): Promise<Response> => {
  const id = requestId(request);
  try {
    if (!["POST", "DELETE"].includes(request.method)) {
      return methodNotAllowed(request, ["POST", "DELETE"], id);
    }
    requireMutationGuard(request);
    if (request.method === "DELETE") {
      return json(
        { cleared: true },
        {
          requestId: id,
          headers: { "set-cookie": clearSessionCookie() }
        }
      );
    }
    await requireUser(request);
    const token = bearerToken(request);
    return json(
      { authenticated: true },
      {
        requestId: id,
        headers: { "set-cookie": sessionCookie(token) }
      }
    );
  } catch (error) {
    return toErrorResponse(error, id);
  }
};

export const config: Config = {
  path: "/api/session"
};
