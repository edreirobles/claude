import { env, requiredEnv } from "./env.js";

type GenerateOptions = {
  system: string;
  user: string;
  maxTokens?: number;
};

async function responseJson(response: Response): Promise<Record<string, unknown>> {
  const payload = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    const message = JSON.stringify(payload).slice(0, 500);
    throw new Error(`Text provider returned ${response.status}: ${message}`);
  }
  return payload;
}

async function generateAnthropic(options: GenerateOptions): Promise<string> {
  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": requiredEnv("ANTHROPIC_API_KEY"),
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify({
      model: env("ANTHROPIC_TEXT_MODEL", "claude-opus-4-6"),
      max_tokens: options.maxTokens ?? 1600,
      system: options.system,
      messages: [{ role: "user", content: options.user }]
    })
  });
  const payload = await responseJson(response);
  const content = payload.content as Array<{ type?: string; text?: string }> | undefined;
  return content?.find((item) => item.type === "text")?.text?.trim() ?? "";
}

async function generateOpenAi(options: GenerateOptions): Promise<string> {
  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      authorization: `Bearer ${requiredEnv("OPENAI_API_KEY")}`,
      "content-type": "application/json"
    },
    body: JSON.stringify({
      model: env("OPENAI_TEXT_MODEL", "gpt-5-mini"),
      reasoning: { effort: env("OPENAI_REASONING_EFFORT", "minimal") },
      max_output_tokens: options.maxTokens ?? 1600,
      instructions: options.system,
      input: options.user
    })
  });
  const payload = await responseJson(response);
  if (typeof payload.output_text === "string") return payload.output_text.trim();
  const output = payload.output as
    | Array<{ content?: Array<{ type?: string; text?: string }> }>
    | undefined;
  return (
    output
      ?.flatMap((item) => item.content ?? [])
      .find((item) => item.type === "output_text")
      ?.text?.trim() ?? ""
  );
}

export async function generateText(options: GenerateOptions): Promise<string> {
  const provider = env("TEXT_GENERATION_PROVIDER", "anthropic").toLowerCase();
  const result =
    provider === "openai"
      ? await generateOpenAi(options)
      : await generateAnthropic(options);
  if (!result) throw new Error("Text provider returned an empty response");
  return result;
}

export function extractJsonObject<T>(text: string): T {
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed) as T;
  } catch {
    const match = trimmed.match(/\{[\s\S]*\}/);
    if (!match) throw new Error("Provider response did not contain JSON");
    return JSON.parse(match[0]) as T;
  }
}
