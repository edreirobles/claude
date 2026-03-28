import { NextRequest, NextResponse } from "next/server";
import { discoverTools } from "@/lib/discovery";
import { rankToolsForNeed } from "@/lib/claude";
import { createServerClient } from "@/lib/supabase";
import type { DiscoverRequest, DiscoverResponse, Tool } from "@/types";

export async function POST(req: NextRequest) {
  const { need }: DiscoverRequest = await req.json();

  if (!need?.trim()) {
    return NextResponse.json({ error: "need is required" }, { status: 400 });
  }

  // 1. Get tool candidates
  const candidates = await discoverTools(need);

  // 2. Ask Claude to rank them
  const { scores } = await rankToolsForNeed(
    need,
    candidates.map((t) => ({ name: t.name, description: t.description }))
  );

  // 3. Apply scores and sort
  const ranked: Tool[] = candidates
    .map((t) => ({ ...t, score: scores[t.name] ?? 50 }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  // 4. Cache top tools to Supabase (fire and forget)
  try {
    const db = createServerClient();
    await db.from("tools").upsert(
      ranked.map((t) => ({
        id: t.id,
        name: t.name,
        url: t.url,
        description: t.description,
        tags: t.tags,
        icon: t.icon,
        sponsored: t.sponsored ?? false,
        source: t.source,
      })),
      { onConflict: "id" }
    );
  } catch {
    // Non-fatal: continue even if DB write fails
  }

  const response: DiscoverResponse = { tools: ranked, query: need };
  return NextResponse.json(response);
}
