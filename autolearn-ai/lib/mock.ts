/**
 * Mock data used when DEMO_MODE=true or API keys are missing.
 * The app is fully functional with this data — no external calls needed.
 */
import type { Tool, Tutorial, TutorialSlide } from "@/types";

export const MOCK_TOOLS: Tool[] = [
  {
    id: "make",
    name: "Make",
    url: "https://make.com",
    description: "Automatiza flujos completos sin código. Ideal para conectar CRM → Sheets → email.",
    tags: ["automation", "no-code", "integrations"],
    score: 92,
    icon: "⚡",
    source: "manual",
  },
  {
    id: "zapier",
    name: "Zapier",
    url: "https://zapier.com",
    description: "El estándar de automatización. 6,000+ apps conectadas. Más simple que Make.",
    tags: ["automation", "no-code", "popular"],
    score: 85,
    icon: "🔗",
    source: "manual",
    sponsored: true,
  },
  {
    id: "n8n",
    name: "n8n",
    url: "https://n8n.io",
    description: "Open source y self-hosted. Máximo control y sin límites de operaciones.",
    tags: ["automation", "open-source", "free"],
    score: 78,
    icon: "🔧",
    source: "manual",
  },
];

function mockSlides(need: string, toolName: string): TutorialSlide[] {
  return [
    {
      id: 1,
      type: "intro",
      title: `Automatiza "${need}" con ${toolName}`,
      body: `En 10 minutos vas a tener tu automatización funcionando. No necesitas código ni experiencia previa. Solo sigue los pasos.`,
    },
    {
      id: 2,
      type: "step",
      title: `Crea tu cuenta en ${toolName}`,
      body: `Ve al sitio web y regístrate gratis. El plan gratuito es más que suficiente para empezar.`,
      checklist: [
        `Ir a ${toolName.toLowerCase()}.com`,
        "Click en "Get started free"",
        "Registrarse con Google (más rápido)",
      ],
      stepNumber: 1,
      totalSteps: 3,
    },
    {
      id: 3,
      type: "step",
      title: "Crea tu primer flujo",
      body: `Un flujo en ${toolName} conecta dos o más aplicaciones. Haz click en el botón "+" para comenzar desde cero.`,
      checklist: [
        "Dashboard → "Create a new scenario"",
        "Elige tu app de origen (ej: Google Sheets)",
        "Selecciona el disparador (ej: "New row")",
      ],
      stepNumber: 2,
      totalSteps: 3,
    },
    {
      id: 4,
      type: "step",
      title: "Configura la acción",
      body: `Ahora conecta la app de destino. ${toolName} se encarga de mover los datos automáticamente cada vez que ocurra el evento.`,
      checklist: [
        "Agrega un módulo de destino",
        "Mapea los campos (arrastra y suelta)",
        "Haz click en "Run once" para probar",
      ],
      stepNumber: 3,
      totalSteps: 3,
    },
    {
      id: 5,
      type: "recap",
      title: "¡Tu automatización está activa!",
      body: `${toolName} se ejecutará automáticamente cada vez que ocurra el evento. Acabas de ahorrar horas de trabajo manual cada semana.`,
    },
  ];
}

export function getMockTutorial(need: string, tool: Tool): Tutorial {
  return {
    id: "demo-" + tool.id,
    toolId: tool.id,
    toolName: tool.name,
    need,
    level: "beginner",
    durationMinutes: 10,
    slides: mockSlides(need, tool.name),
    formats: ["deck", "steps"],
    createdAt: new Date().toISOString(),
  };
}

export function isMockMode(): boolean {
  return (
    process.env.DEMO_MODE === "true" ||
    !process.env.ANTHROPIC_API_KEY ||
    process.env.ANTHROPIC_API_KEY === "sk-ant-..."
  );
}
