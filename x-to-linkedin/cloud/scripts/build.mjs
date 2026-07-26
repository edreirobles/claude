import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import * as cheerio from "cheerio";
import { build } from "esbuild";

const root = resolve(import.meta.dirname, "../..");
const dist = resolve(root, "dist");
const staticDir = resolve(root, "static");

await rm(dist, { recursive: true, force: true });
await mkdir(resolve(dist, "static"), { recursive: true });
await cp(resolve(staticDir, "css"), resolve(dist, "static/css"), { recursive: true });
await cp(resolve(staticDir, "js"), resolve(dist, "static/js"), { recursive: true });

const sourceHtml = await readFile(resolve(staticDir, "index.html"), "utf8");
const $ = cheerio.load(sourceHtml);

$(".admin-controls, #admin-modal, #section-x-monitor").remove();
const currentTitle = $("title");
currentTitle.text("Radar Editorial");
$(".logo-icon, .logo-arrow, .logo-li").remove();
$(".logo-text").text("Radar Editorial");
$(
  "#tab-btn-publish > span, #tab-btn-analytics > span, #btn-generate .btn-icon, .history-badge"
).remove();
$("#li-scraper-status").remove();
$("[data-cloud-remove]").remove();
$(".publish-subtitle")
  .filter((_index, element) =>
    $(element).text().includes("Se asigna automáticamente al próximo slot")
  )
  .first()
  .text("Se programa 30 minutos después de confirmar.");
$("a[href='/auth/linkedin']")
  .attr("href", "#")
  .attr("data-cloud-linkedin-connect", "true");

$("head").append('<link rel="stylesheet" href="/cloud.css">');
$(".header-inner").append(
  '<button id="cloud-logout" class="btn btn-ghost btn-sm" title="Cerrar sesion">Salir</button>'
);

const publicConfig = {
  supabaseUrl: process.env.SUPABASE_URL ?? "",
  supabasePublishableKey: process.env.SUPABASE_PUBLISHABLE_KEY ?? "",
  appEnv: process.env.APP_ENV ?? "preview"
};
const configSource =
  `window.__CLOUD_CONFIG__=${JSON.stringify(publicConfig).replaceAll("<", "\\u003c")};\n`;
const appScript = $("script[src^='/static/js/app.js']").first();
appScript.before('<script src="/cloud-config.js"></script>');
appScript.before('<script src="/cloud-auth.js"></script>');

await writeFile(resolve(dist, "index.html"), $.html(), "utf8");
await writeFile(resolve(dist, "cloud-config.js"), configSource, "utf8");
const cloudAppPath = resolve(dist, "static/js/app.js");
const cloudAppSource = await readFile(cloudAppPath, "utf8");
await writeFile(
  cloudAppPath,
  cloudAppSource
    .replace("Generando post con Claude AI...", "Decidiendo el mejor tratamiento editorial...")
    .replace("¡Post publicado en LinkedIn exitosamente! 🎉", "Publicación aceptada y encolada.")
    .replace("¡Publicado!", "Publicación encolada")
    .replace("Post programado", "Publicación programada"),
  "utf8"
);
await cp(resolve(root, "cloud/web/login.html"), resolve(dist, "login.html"));
await cp(resolve(root, "cloud/web/cloud.css"), resolve(dist, "cloud.css"));

await build({
  entryPoints: [resolve(root, "cloud/web/auth.ts")],
  outfile: resolve(dist, "cloud-auth.js"),
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "es2022",
  minify: true,
  sourcemap: false,
  legalComments: "none"
});
