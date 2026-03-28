"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

const EXAMPLES = [
  { label: "reportes de ventas", icon: "📊" },
  { label: "crear contenido para redes", icon: "✍️" },
  { label: "responder emails automáticamente", icon: "📧" },
  { label: "transcribir reuniones", icon: "🎙️" },
  { label: "generar imágenes para mi marca", icon: "🎨" },
];

export default function HomePage() {
  const [input, setInput] = useState("");
  const router = useRouter();

  function handleSearch(query: string) {
    if (!query.trim()) return;
    router.push(`/results?q=${encodeURIComponent(query.trim())}`);
  }

  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-20">
      <h1 className="text-5xl font-extrabold leading-tight tracking-tight mb-4">
        Aprende cualquier herramienta<br />
        <span style={{ background: "linear-gradient(135deg, var(--purple), var(--blue))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          de IA en 10 minutos.
        </span>
      </h1>
      <p className="text-lg mb-10 max-w-md" style={{ color: "var(--muted)" }}>
        Dinos qué quieres automatizar y te conseguimos la herramienta + tutorial paso a paso.
      </p>

      <div className="flex gap-3 w-full max-w-xl mb-4">
        <input
          className="flex-1 px-5 py-3.5 rounded-xl text-base outline-none"
          style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "#e8e8f0" }}
          placeholder="Ej: quiero automatizar mis reportes de ventas…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch(input)}
          onFocus={(e) => (e.target.style.borderColor = "var(--purple)")}
          onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
        />
        <button
          onClick={() => handleSearch(input)}
          className="px-6 py-3.5 rounded-xl font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: "linear-gradient(135deg, var(--purple), var(--blue))" }}
        >
          Buscar
        </button>
      </div>

      <div className="flex flex-wrap gap-2 justify-center">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            onClick={() => handleSearch(ex.label)}
            className="px-4 py-1.5 rounded-full text-sm transition-colors hover:border-purple-400"
            style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--muted)" }}
          >
            {ex.icon} {ex.label}
          </button>
        ))}
      </div>
    </div>
  );
}
