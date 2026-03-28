"use client";
import { useEffect, useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import type { Tool, DiscoverResponse } from "@/types";

function scoreColor(score: number) {
  if (score >= 85) return "var(--purple)";
  if (score >= 70) return "var(--blue)";
  return "var(--muted)";
}

function ResultsContent() {
  const params = useSearchParams();
  const router = useRouter();
  const need = params.get("q") ?? "";
  const [tools, setTools] = useState<Tool[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!need) return;
    setLoading(true);
    fetch("/api/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ need }),
    })
      .then((r) => r.json())
      .then((data: DiscoverResponse) => {
        setTools(data.tools);
        if (data.tools.length > 0) setSelected(data.tools[0].id);
      })
      .catch(() => setError("Error al buscar herramientas. Revisa tu conexión."))
      .finally(() => setLoading(false));
  }, [need]);

  function handleTutorial() {
    const tool = tools.find((t) => t.id === selected);
    if (!tool) return;
    router.push(`/tutorial?need=${encodeURIComponent(need)}&tool=${encodeURIComponent(JSON.stringify(tool))}`);
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      <div className="flex items-center gap-2 text-sm mb-6" style={{ color: "var(--muted)" }}>
        <a href="/" className="hover:text-white">Inicio</a>
        <span style={{ color: "#333" }}>›</span>
        <span>Resultados</span>
      </div>

      <div className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: "var(--purple)" }}>
        Catálogo Google + There's An AI For That
      </div>
      <h2 className="text-2xl font-bold mb-1">{need}</h2>
      <p className="mb-8" style={{ color: "var(--muted)" }}>
        {loading ? "Buscando herramientas..." : `${tools.length} herramientas encontradas`}
      </p>

      {error && <p style={{ color: "#f87171" }}>{error}</p>}

      {loading ? (
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="rounded-2xl p-5 animate-pulse" style={{ background: "var(--surface)", border: "1px solid var(--border)", height: 180 }} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4 mb-8">
          {tools.map((tool) => (
            <div
              key={tool.id}
              onClick={() => setSelected(tool.id)}
              className="rounded-2xl p-5 cursor-pointer transition-all"
              style={{
                background: "var(--surface)",
                border: `1px solid ${selected === tool.id ? "var(--purple)" : "var(--border)"}`,
              }}
            >
              <div className="flex items-center gap-3 mb-3">
                <div className="text-3xl">{tool.icon}</div>
                <div>
                  <div className="font-bold">{tool.name}</div>
                  <div className="text-xs" style={{ color: "var(--muted)" }}>{new URL(tool.url).hostname}</div>
                </div>
                {tool.sponsored && (
                  <span className="ml-auto text-xs px-2 py-0.5 rounded-full" style={{ background: "#60a5fa22", color: "var(--blue)" }}>
                    Sponsor
                  </span>
                )}
              </div>
              <p className="text-sm mb-3 leading-relaxed" style={{ color: "var(--muted)" }}>{tool.description}</p>
              <div className="flex flex-wrap gap-1 mb-3">
                {tool.tags.slice(0, 3).map((tag) => (
                  <span key={tag} className="text-xs px-2 py-0.5 rounded" style={{ background: "var(--bg)", color: "#666" }}>{tag}</span>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1 rounded-full" style={{ background: "var(--bg)" }}>
                  <div className="h-1 rounded-full" style={{ width: `${tool.score}%`, background: "linear-gradient(90deg, var(--purple), var(--blue))" }} />
                </div>
                <span className="text-xs font-semibold" style={{ color: scoreColor(tool.score) }}>{tool.score}%</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && tools.length > 0 && (
        <div className="flex items-center gap-4">
          <button
            onClick={handleTutorial}
            disabled={!selected}
            className="px-6 py-3.5 rounded-xl font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: "linear-gradient(135deg, var(--purple), var(--blue))" }}
          >
            Ver tutorial de {tools.find((t) => t.id === selected)?.name} →
          </button>
          <span className="text-sm" style={{ color: "var(--muted)" }}>Deck · Screenshots · Paso a paso</span>
        </div>
      )}
    </div>
  );
}

export default function ResultsPage() {
  return (
    <Suspense fallback={<div className="p-10 text-center" style={{ color: "var(--muted)" }}>Cargando...</div>}>
      <ResultsContent />
    </Suspense>
  );
}
