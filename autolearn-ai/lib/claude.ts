import Anthropic from "@anthropic-ai/sdk";
import type { Tool, TutorialSlide, Tutorial } from "@/types";

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY!,
});

export async function generateTutorialSlides(
  need: string,
  tool: Tool,
  level: Tutorial["level"] = "beginner"
): Promise<TutorialSlide[]> {
  const prompt = `You are an expert tutorial creator. Generate a step-by-step tutorial for someone who wants to: "${need}" using the tool "${tool.name}" (${tool.url}).

The tutorial is for a ${level} user. Create exactly 5 slides in this format:
1. Intro slide
2-4. Step slides (numbered 1-3)
5. Recap/success slide

Respond with a valid JSON array of slides. Each slide has:
- id: number (1-5)
- type: "intro" | "step" | "recap"
- title: string (short, punchy)
- body: string (2-3 sentences explaining what to do)
- checklist: string[] (3 bullet points, only for "step" type)
- stepNumber: number (only for "step" type)
- totalSteps: number (always 3, only for "step" type)

Respond ONLY with the JSON array, no markdown, no explanation.`;

  const message = await anthropic.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 2048,
    messages: [{ role: "user", content: prompt }],
  });

  const text = message.content[0].type === "text" ? message.content[0].text : "";
  const slides: TutorialSlide[] = JSON.parse(text);
  return slides;
}

export async function rankToolsForNeed(
  need: string,
  tools: { name: string; description: string }[]
): Promise<{ scores: Record<string, number> }> {
  const prompt = `Given the user need: "${need}"
Rate each tool from 0-100 for how well it fits.

Tools:
${tools.map((t, i) => `${i + 1}. ${t.name}: ${t.description}`).join("\n")}

Respond with a JSON object: { "scores": { "ToolName": score, ... } }
Only the JSON, no explanation.`;

  const message = await anthropic.messages.create({
    model: "claude-haiku-4-5-20251001",
    max_tokens: 512,
    messages: [{ role: "user", content: prompt }],
  });

  const text = message.content[0].type === "text" ? message.content[0].text : "{}";
  return JSON.parse(text);
}
