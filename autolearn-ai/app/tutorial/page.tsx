"use client";
import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import type { Tool, Tutorial, TutorialSlide, GenerateResponse } from "@/types";

const FORMATS = [
  { key: "deck", label: "🃏 Deck" },
  { key: "steps", label: "📋 Paso a paso" },
] as const;

function SlideView({ slide, total }: { slide: TutorialSlide; total: number }) {
  if (slide.type === "intro" || slide.type === "recap") {
    return (
      <div className="flex flex-col justify-center p-16 min-h-72"
        style={{ background: "linear-gradient(135deg, #1e1a2e, #1a1e2e)" }}>
        <div className="text-6xl mb-6">{slide.type === "intro" ? "⚡" : "🎉"}</div>
        <div className="text-xs font-semibold uppercase tracking-widest mb-4" style={{ color: "var(--purple)" }}>
          {slide.type === "intro" ? "Bienvenida" : "¡Listo!"}
        </div>
        <h2 className="text-3xl font-extrabold mb-4 leading-tight">{slide.title}</h2>
        <p className="text-base leading-relaxed max-w-lg" style={{ color: "var(--muted)" }}>{slide.body}</p>
      </div>
    );
  }

  return (
    <div className="grid min-h-72" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <div className="p-10 flex flex-col justify-center">
        <div className="text-xs font-semibold uppercase tracking-widest mb-3" style={{ color: "var(--purple)" }}>
          Paso {slide.stepNumber} de {slide.totalSteps ?? total - 2}
        </div>
        <h3 className="text-xl font-bold mb-3 leading-snug">{slide.title}</h3>
        <p className="text-sm leading-relaxed mb-4" style={{ color: "var(--muted)" }}>{slide.body}</p>
        {slide.checklist && (
          <ul className="flex flex-col gap-2">
            {slide.checklist.map((item, i) => (
              <li key={i} className="flex gap-2 items-start text-sm">
                <span style={{ color: "var(--purple)", fontWeight: 700 }}>✓</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex items-center justify-center p-6"
        style={{ background: "var(--bg)", borderLeft: "1px solid var(--border)", position: "relative" }}>
        {slide.screenshotUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={slide.screenshotUrl} alt={slide.title} className="rounded-lg w-full" />
        ) : (
          <div className="w-full rounded-xl p-4" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
            <div className="flex gap-1.5 mb-3">
              <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
              <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
              <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
            </div>
            <div className="space-y-2">
              <div className="h-2 rounded" style={{ background: "var(--border)" }} />
              <div className="h-2 rounded w-3/5" style={{ background: "var(--border)" }} />
              <div className="h-2 rounded" style={{ background: "var(--border)" }} />
              <div className="h-2 rounded w-4/5" style={{ background: "#a78bfa44" }} />
              <div className="h-6 rounded mt-3" style={{ background: "#a78bfa22", border: "1px solid var(--purple)" }} />
            </div>
          </div>
        )}
        <div className="absolute top-3 right-3 text-xs px-2 py-1 rounded"
          style={{ background: "var(--bg)", color: "#555", border: "1px solid var(--border)" }}>
          📸 screenshot real al generar
        </div>
      </div>
    </div>
  );
}

function StepsView({ slides }: { slides: TutorialSlide[] }) {
  const steps = slides.filter((s) => s.type === "step");
  return (
    <div className="p-8 space-y-8">
      {steps.map((slide) => (
        <div key={slide.id} className="flex gap-6">
          <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold"
            style={{ background: "var(--purple)", color: "white" }}>
            {slide.stepNumber}
          </div>
          <div>
            <h4 className="font-bold text-lg mb-2">{slide.title}</h4>
            <p className="text-sm leading-relaxed mb-3" style={{ color: "var(--muted)" }}>{slide.body}</p>
            {slide.checklist && (
              <ul className="space-y-1">
                {slide.checklist.map((item, i) => (
                  <li key={i} className="text-sm flex gap-2">
                    <span style={{ color: "var(--purple)" }}>✓</span> {item}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function TutorialContent() {
  const params = useSearchParams();
  const need = params.get("need") ?? "";
  const toolParam = params.get("tool");
  const tool: Tool | null = toolParam ? JSON.parse(toolParam) : null;

  const [tutorial, setTutorial] = useState<Tutorial | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [slide, setSlide] = useState(0);
  const [format, setFormat] = useState<"deck" | "steps">("deck");

  useEffect(() => {
    if (!need || !tool) return;
    fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ need, tool }),
    })
      .then((r) => r.json())
      .then((data: GenerateResponse) => setTutorial(data.tutorial))
      .catch(() => setError("Error al generar el tutorial."))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [need]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!tutorial) return;
      if (e.key === "ArrowRight") setSlide((s) => Math.min(s + 1, tutorial.slides.length - 1));
      if (e.key === "ArrowLeft") setSlide((s) => Math.max(s - 1, 0));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tutorial]);

  if (!tool) return <p className="p-10" style={{ color: "var(--muted)" }}>Herramienta no especificada.</p>;

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      <div className="flex items-center gap-2 text-sm mb-6" style={{ color: "var(--muted)" }}>
        <a href="/" className="hover:text-white">Inicio</a>
        <span style={{ color: "#333" }}>›</span>
        <a href={`/results?q=${encodeURIComponent(need)}`} className="hover:text-white">Resultados</a>
        <span style={{ color: "#333" }}>›</span>
        <span>Tutorial {tool.name}</span>
      </div>

      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest mb-1" style={{ color: "var(--purple)" }}>
            Tutorial · {tool.name}
          </div>
          <h2 className="text-2xl font-bold">{need}</h2>
        </div>
        <div className="flex gap-2">
          {["10 min", "Principiante", "5 pasos"].map((pill) => (
            <span key={pill} className="text-xs px-3 py-1 rounded-full" style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--muted)" }}>
              {pill}
            </span>
          ))}
        </div>
      </div>

      <div className="flex gap-2 mb-6">
        {FORMATS.map((f) => (
          <button key={f.key} onClick={() => setFormat(f.key)}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            style={{
              background: format === f.key ? "#a78bfa22" : "var(--surface)",
              border: `1px solid ${format === f.key ? "var(--purple)" : "var(--border)"}`,
              color: format === f.key ? "var(--purple)" : "var(--muted)",
            }}>
            {f.label}
          </button>
        ))}
      </div>

      <div className="rounded-2xl overflow-hidden" style={{ border: "1px solid var(--border)", background: "var(--surface)" }}>
        {loading ? (
          <div className="p-16 text-center animate-pulse" style={{ color: "var(--muted)" }}>
            Generando tutorial con Claude...
          </div>
        ) : error ? (
          <p className="p-16 text-center" style={{ color: "#f87171" }}>{error}</p>
        ) : tutorial && format === "deck" ? (
          <>
            <SlideView slide={tutorial.slides[slide]} total={tutorial.slides.length} />
            <div className="flex items-center justify-between px-6 py-4"
              style={{ background: "var(--bg)", borderTop: "1px solid var(--border)" }}>
              <button onClick={() => setSlide((s) => Math.max(s - 1, 0))}
                disabled={slide === 0}
                className="px-5 py-2 rounded-lg text-sm font-semibold disabled:opacity-30"
                style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--muted)" }}>
                ← Anterior
              </button>
              <div className="flex flex-col items-center gap-1">
                <div className="flex gap-1.5">
                  {tutorial.slides.map((_, i) => (
                    <button key={i} onClick={() => setSlide(i)}
                      className="rounded-full transition-all"
                      style={{
                        width: i === slide ? 20 : 6,
                        height: 6,
                        background: i === slide ? "var(--purple)" : "var(--border)",
                      }} />
                  ))}
                </div>
                <span className="text-xs" style={{ color: "#666" }}>{slide + 1} / {tutorial.slides.length}</span>
              </div>
              <button onClick={() => setSlide((s) => Math.min(s + 1, tutorial.slides.length - 1))}
                disabled={slide === tutorial.slides.length - 1}
                className="px-5 py-2 rounded-lg text-sm font-semibold disabled:opacity-30 text-white"
                style={{ background: "linear-gradient(135deg, var(--purple), var(--blue))" }}>
                Siguiente →
              </button>
            </div>
          </>
        ) : tutorial && format === "steps" ? (
          <StepsView slides={tutorial.slides} />
        ) : null}
      </div>

      {tutorial && (
        <div className="mt-12">
          <div className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: "var(--purple)" }}>
            ¿Qué más puedes hacer?
          </div>
          <h3 className="text-xl font-bold mb-5">Tutoriales relacionados</h3>
          <div className="grid grid-cols-3 gap-4">
            {[
              { icon: "📧", title: "Automatizar respuestas de email", desc: "Conecta Gmail para responder leads automáticamente." },
              { icon: "📱", title: "Publicar en redes sociales", desc: "Programa contenido en todas tus redes desde un Sheet." },
              { icon: "🔔", title: "Alertas en Slack desde tu CRM", desc: "Recibe una notificación cada vez que cierras un deal." },
            ].map((card) => (
              <a key={card.title} href="/"
                className="rounded-2xl p-5 block transition-colors"
                style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
                <div className="text-xl mb-2">{card.icon}</div>
                <h4 className="font-semibold text-sm mb-1">{card.title}</h4>
                <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>{card.desc}</p>
                <div className="mt-4 text-lg" style={{ color: "var(--purple)" }}>→</div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function TutorialPage() {
  return (
    <Suspense fallback={<div className="p-10 text-center" style={{ color: "var(--muted)" }}>Cargando...</div>}>
      <TutorialContent />
    </Suspense>
  );
}
