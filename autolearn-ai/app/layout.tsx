import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AutoLearn AI — Aprende cualquier herramienta de IA en 10 minutos",
  description: "Dinos qué quieres automatizar y te conseguimos la herramienta + tutorial personalizado.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <nav className="flex items-center justify-between px-10 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <a href="/" className="text-xl font-bold" style={{ color: "var(--purple)" }}>
            auto<span style={{ color: "#e8e8f0" }}>learn</span>.ai
          </a>
          <div className="flex gap-6 text-sm" style={{ color: "var(--muted)" }}>
            <a href="/" className="hover:text-white transition-colors">Inicio</a>
            <a href="#" className="hover:text-white transition-colors">Biblioteca</a>
          </div>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
