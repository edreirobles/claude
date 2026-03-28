export function DemoBanner() {
  return (
    <div className="text-center text-xs py-2 px-4"
      style={{ background: "#a78bfa22", borderBottom: "1px solid #a78bfa44", color: "#c4b5fd" }}>
      Modo demo — agrega tus API keys en{" "}
      <code className="px-1 py-0.5 rounded" style={{ background: "#a78bfa33" }}>.env.local</code>
      {" "}para activar Claude + Supabase.{" "}
      <a href="https://github.com/edreirobles/claude/blob/main/autolearn-ai/.env.example"
        className="underline hover:text-white" target="_blank" rel="noopener noreferrer">
        Ver instrucciones →
      </a>
    </div>
  );
}
