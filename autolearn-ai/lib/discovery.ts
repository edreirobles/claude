import type { Tool } from "@/types";

// Curated seed catalog (fallback when APIs are unavailable)
const SEED_TOOLS: Tool[] = [
  {
    id: "make",
    name: "Make",
    url: "https://make.com",
    description: "Visual automation platform. Connect apps and automate workflows without code.",
    tags: ["automation", "no-code", "integrations"],
    score: 0,
    icon: "⚡",
    source: "manual",
  },
  {
    id: "zapier",
    name: "Zapier",
    url: "https://zapier.com",
    description: "Connect 6,000+ apps and automate repetitive tasks. The easiest way to automate.",
    tags: ["automation", "no-code", "popular"],
    score: 0,
    icon: "🔗",
    source: "manual",
    sponsored: false,
  },
  {
    id: "n8n",
    name: "n8n",
    url: "https://n8n.io",
    description: "Open-source workflow automation. Self-host for full control with 400+ integrations.",
    tags: ["automation", "open-source", "self-hosted"],
    score: 0,
    icon: "🔧",
    source: "manual",
  },
  {
    id: "claude",
    name: "Claude",
    url: "https://claude.ai",
    description: "AI assistant for analysis, writing, coding, and complex reasoning tasks.",
    tags: ["ai", "writing", "analysis", "coding"],
    score: 0,
    icon: "🤖",
    source: "manual",
  },
  {
    id: "midjourney",
    name: "Midjourney",
    url: "https://midjourney.com",
    description: "AI image generation. Create stunning visuals from text descriptions.",
    tags: ["ai", "images", "design", "creative"],
    score: 0,
    icon: "🎨",
    source: "manual",
  },
  {
    id: "notion-ai",
    name: "Notion AI",
    url: "https://notion.so",
    description: "AI built into your workspace. Write, summarize, and organize information.",
    tags: ["productivity", "writing", "ai", "notes"],
    score: 0,
    icon: "📝",
    source: "manual",
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    url: "https://elevenlabs.io",
    description: "AI voice generation. Clone voices and generate realistic speech in any language.",
    tags: ["ai", "audio", "voice", "tts"],
    score: 0,
    icon: "🎙️",
    source: "manual",
  },
  {
    id: "perplexity",
    name: "Perplexity",
    url: "https://perplexity.ai",
    description: "AI-powered search engine that gives direct answers with cited sources.",
    tags: ["ai", "search", "research"],
    score: 0,
    icon: "🔍",
    source: "manual",
  },
];

export async function discoverTools(need: string): Promise<Tool[]> {
  const tools = [...SEED_TOOLS];

  // If Google Custom Search API key is set, fetch additional tools
  if (process.env.GOOGLE_SEARCH_API_KEY && process.env.GOOGLE_SEARCH_ENGINE_ID) {
    try {
      const query = encodeURIComponent(`AI tool for: ${need} site:theresanaiforthat.com OR site:producthunt.com`);
      const url = `https://www.googleapis.com/customsearch/v1?key=${process.env.GOOGLE_SEARCH_API_KEY}&cx=${process.env.GOOGLE_SEARCH_ENGINE_ID}&q=${query}&num=5`;
      const res = await fetch(url);
      const data = await res.json();

      if (data.items) {
        const googleTools: Tool[] = data.items.map((item: { title: string; link: string; snippet: string }, i: number) => ({
          id: `google-${i}`,
          name: item.title.split(" - ")[0].split(" | ")[0],
          url: item.link,
          description: item.snippet,
          tags: [],
          score: 0,
          icon: "🌐",
          source: "google" as const,
        }));
        tools.push(...googleTools);
      }
    } catch {
      // Fall through to seed catalog only
    }
  }

  return tools;
}
