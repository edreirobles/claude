import { NextRequest, NextResponse } from "next/server";
import { generateTutorialSlides } from "@/lib/claude";
import { createServerClient } from "@/lib/supabase";
import { isMockMode, getMockTutorial } from "@/lib/mock";
import type { GenerateRequest, GenerateResponse, Tutorial } from "@/types";
import { createHash } from "crypto";

export async function POST(req: NextRequest) {
  const { need, tool, level = "beginner" }: GenerateRequest = await req.json();

  if (!need?.trim() || !tool) {
    return NextResponse.json({ error: "need and tool are required" }, { status: 400 });
  }

  // Demo mode — no API keys required
  if (isMockMode()) {
    return NextResponse.json({
      tutorial: getMockTutorial(need, tool),
      demo: true,
    });
  }

  const cacheKey = createHash("md5")
    .update(`${need.toLowerCase()}|${tool.id}|${level}`)
    .digest("hex");

  const db = createServerClient();

  // 1. Check cache — don't regenerate if tutorial already exists
  const { data: existing } = await db
    .from("tutorials")
    .select("*")
    .eq("cache_key", cacheKey)
    .single();

  if (existing) {
    const tutorial: Tutorial = {
      id: existing.id,
      toolId: existing.tool_id,
      toolName: existing.tool_name,
      need: existing.need,
      level: existing.level,
      durationMinutes: existing.duration_minutes,
      slides: existing.slides,
      formats: existing.formats,
      createdAt: existing.created_at,
    };
    return NextResponse.json({ tutorial } satisfies GenerateResponse);
  }

  // 2. Generate with Claude
  const slides = await generateTutorialSlides(need, tool, level);

  const tutorial: Omit<Tutorial, "id" | "createdAt"> = {
    toolId: tool.id,
    toolName: tool.name,
    need,
    level,
    durationMinutes: level === "beginner" ? 10 : level === "intermediate" ? 20 : 30,
    slides,
    formats: ["deck", "steps"],
  };

  // 3. Persist
  const { data: saved, error } = await db
    .from("tutorials")
    .insert({
      tool_id: tutorial.toolId,
      tool_name: tutorial.toolName,
      need: tutorial.need,
      level: tutorial.level,
      duration_minutes: tutorial.durationMinutes,
      slides: tutorial.slides,
      formats: tutorial.formats,
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    tutorial: {
      ...tutorial,
      id: saved.id,
      createdAt: saved.created_at,
    },
  } satisfies GenerateResponse);
}
