export interface Tool {
  id: string;
  name: string;
  url: string;
  description: string;
  tags: string[];
  score: number;
  icon: string;
  sponsored?: boolean;
  source: "taaft" | "google" | "manual";
}

export interface TutorialSlide {
  id: number;
  type: "intro" | "step" | "video" | "recap";
  title: string;
  body: string;
  checklist?: string[];
  screenshotUrl?: string;
  videoUrl?: string;
  stepNumber?: number;
  totalSteps?: number;
}

export interface Tutorial {
  id: string;
  toolId: string;
  toolName: string;
  need: string;
  level: "beginner" | "intermediate" | "advanced";
  durationMinutes: number;
  slides: TutorialSlide[];
  createdAt: string;
  formats: ("deck" | "video" | "steps")[];
}

export interface DiscoverRequest {
  need: string;
}

export interface DiscoverResponse {
  tools: Tool[];
  query: string;
}

export interface GenerateRequest {
  need: string;
  tool: Tool;
  level?: Tutorial["level"];
}

export interface GenerateResponse {
  tutorial: Tutorial;
}
