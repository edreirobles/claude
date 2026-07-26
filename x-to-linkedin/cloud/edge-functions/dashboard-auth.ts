import type { Config, Context } from "@netlify/edge-functions";

function env(name: string): string {
  return Netlify.env.get(name) ?? "";
}

function readCookie(request: Request, name: string): string {
  const cookies = request.headers.get("cookie") ?? "";
  for (const part of cookies.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return "";
}

export default async (request: Request, context: Context): Promise<Response> => {
  const token = readCookie(request, "x2li_session");
  const supabaseUrl = env("SUPABASE_URL");
  const publishableKey = env("SUPABASE_PUBLISHABLE_KEY");
  const allowedUserId = env("ALLOWED_USER_ID");

  if (!token || !supabaseUrl || !publishableKey || !allowedUserId) {
    return Response.redirect(new URL("/login.html", request.url), 302);
  }

  const authResponse = await fetch(`${supabaseUrl}/auth/v1/user`, {
    headers: {
      authorization: `Bearer ${token}`,
      apikey: publishableKey
    }
  });
  if (!authResponse.ok) {
    return Response.redirect(new URL("/login.html", request.url), 302);
  }
  const user = (await authResponse.json()) as { id?: string };
  if (user.id !== allowedUserId) {
    return new Response("Forbidden", { status: 403 });
  }
  return context.next();
};

export const config: Config = {
  path: ["/", "/static/*"]
};
