/* ─────────────────────────────────────────────────────────
   TRANSLATIONS  — every key must exist in BOTH en and es
───────────────────────────────────────────────────────── */
const T = {
  en: {
    // Header
    nav_history: "History",
    nav_new: "+ New CV",
    // Hero
    hero_title: 'Your CV, <span class="highlight">perfectly tailored</span><br>for every application',
    hero_subtitle: "Upload your CV, paste the job description, and get a professionally adapted CV in seconds — honest, curated, and optimized for the role.",
    // Stepper
    step1_label: "Job posting",
    step2_label: "Your CV",
    step3_label: "Download",
    // Step 1
    s1_title: "Step 1 — Job posting",
    s1_desc: "Paste the LinkedIn URL or the full job description text below.",
    tab_url: "LinkedIn / URL",
    tab_text: "Paste text",
    url_label: "Job posting URL",
    url_ph: "https://www.linkedin.com/jobs/view/...",
    url_hint: 'We\'ll try to fetch it automatically. If it fails, switch to "Paste text".',
    text_label: "Job description",
    text_ph: "Paste the full job description here (any language)...",
    // Output language
    output_lang_label: "CV output language",
    output_lang_hint: "Auto will match the language of the job posting",
    lang_auto: "Auto",
    lang_en: "English",
    lang_es: "Español",
    lang_fr: "Français",
    lang_pt: "Português",
    lang_de: "Deutsch",
    // Step 1 button
    btn_continue: "Continue →",
    // Step 2
    s2_title: "Step 2 — Upload your CV",
    s2_desc: "Upload your current CV in PDF or Word format.",
    upload_drop: "Drop your CV here or",
    upload_browse: "browse",
    upload_hint: "PDF, DOC or DOCX · Max 10 MB",
    btn_change: "Change",
    btn_back: "← Back",
    btn_generate: "Generate CV →",
    // Step 3 loading
    loading_title: "Crafting your tailored CV…",
    ls1: "Reading your CV",
    ls2: "Analyzing job requirements",
    ls3: "Rewriting and curating content",
    ls4: "Generating PDF",
    loading_note: "This usually takes 20–40 seconds",
    // Step 3 success
    success_title: "Your CV is ready!",
    success_for: "CV adapted for {title} at {company}",
    btn_download: "Download PDF",
    btn_start_over: "Generate another",
    // Step 3 error
    error_title: "Something went wrong",
    btn_retry: "Try again",
    // Features
    f1_title: "Honest adaptation",
    f1_desc: "We only reframe what's already in your CV — no invented experience, no lies.",
    f2_title: "Smart curation",
    f2_desc: "Irrelevant content is removed. Only what strengthens your application stays.",
    f3_title: "Professional PDF",
    f3_desc: "Clean, classic layout ready to impress recruiters and pass ATS filters.",
    // History page
    hist_title: "Generation history",
    hist_view_posting: "View posting ↗",
    hist_preview: "Job description preview",
    hist_download: "Download PDF",
    hist_failed: "Failed",
    hist_processing: "Processing",
    // Empty state
    empty_title: "No CVs generated yet",
    empty_desc: "Your generated CVs will appear here once you create one.",
    empty_cta: "Generate your first CV",
    // Alerts
    alert_no_job: "Please enter a job URL or paste the job description text.",
    alert_bad_file: "Please upload a PDF or Word document (.pdf, .doc, .docx)",
    alert_too_large: "File is too large. Maximum 10 MB.",
  },

  es: {
    // Header
    nav_history: "Historial",
    nav_new: "+ Nuevo CV",
    // Hero
    hero_title: 'Tu CV, <span class="highlight">perfectamente adaptado</span><br>para cada solicitud',
    hero_subtitle: "Sube tu CV, pega la descripción de la vacante y obtén un CV profesionalmente adaptado en segundos — honesto, curado y optimizado para el puesto.",
    // Stepper
    step1_label: "Vacante",
    step2_label: "Tu CV",
    step3_label: "Descargar",
    // Step 1
    s1_title: "Paso 1 — Vacante",
    s1_desc: "Pega el enlace de LinkedIn o el texto completo de la vacante.",
    tab_url: "LinkedIn / URL",
    tab_text: "Pegar texto",
    url_label: "URL de la vacante",
    url_ph: "https://www.linkedin.com/jobs/view/...",
    url_hint: 'Intentaremos obtenerla automáticamente. Si falla, usa "Pegar texto".',
    text_label: "Descripción de la vacante",
    text_ph: "Pega aquí el texto completo de la vacante (en cualquier idioma)...",
    // Output language
    output_lang_label: "Idioma de salida del CV",
    output_lang_hint: "Auto detectará el idioma de la vacante",
    lang_auto: "Auto",
    lang_en: "English",
    lang_es: "Español",
    lang_fr: "Français",
    lang_pt: "Português",
    lang_de: "Deutsch",
    // Step 1 button
    btn_continue: "Continuar →",
    // Step 2
    s2_title: "Paso 2 — Sube tu CV",
    s2_desc: "Sube tu CV actual en formato PDF o Word.",
    upload_drop: "Arrastra tu CV aquí o",
    upload_browse: "busca",
    upload_hint: "PDF, DOC o DOCX · Máx. 10 MB",
    btn_change: "Cambiar",
    btn_back: "← Atrás",
    btn_generate: "Generar CV →",
    // Step 3 loading
    loading_title: "Creando tu CV adaptado…",
    ls1: "Leyendo tu CV",
    ls2: "Analizando los requisitos del puesto",
    ls3: "Reescribiendo y curando el contenido",
    ls4: "Generando el PDF",
    loading_note: "Esto suele tardar entre 20 y 40 segundos",
    // Step 3 success
    success_title: "¡Tu CV está listo!",
    success_for: "CV adaptado para {title} en {company}",
    btn_download: "Descargar PDF",
    btn_start_over: "Generar otro",
    // Step 3 error
    error_title: "Algo salió mal",
    btn_retry: "Intentar de nuevo",
    // Features
    f1_title: "Adaptación honesta",
    f1_desc: "Solo reformulamos lo que ya está en tu CV — sin inventar experiencia ni habilidades.",
    f2_title: "Curación inteligente",
    f2_desc: "El contenido irrelevante se elimina. Solo queda lo que fortalece tu solicitud.",
    f3_title: "PDF profesional",
    f3_desc: "Diseño limpio y clásico listo para impresionar reclutadores y pasar filtros ATS.",
    // History page
    hist_title: "Historial de generaciones",
    hist_view_posting: "Ver vacante ↗",
    hist_preview: "Vista previa de la vacante",
    hist_download: "Descargar PDF",
    hist_failed: "Fallido",
    hist_processing: "Procesando",
    // Empty state
    empty_title: "Aún no hay CVs generados",
    empty_desc: "Tus CVs generados aparecerán aquí una vez que crees uno.",
    empty_cta: "Genera tu primer CV",
    // Alerts
    alert_no_job: "Por favor ingresa una URL o pega el texto de la vacante.",
    alert_bad_file: "Por favor sube un PDF o documento Word (.pdf, .doc, .docx)",
    alert_too_large: "El archivo es demasiado grande. Máximo 10 MB.",
  },
};

/* ─────────────────────────────────────────────────────────
   STATE
───────────────────────────────────────────────────────── */
let uiLang     = localStorage.getItem("cv_ui_lang") || "en";
let dark       = localStorage.getItem("cv_dark") === "true";
let selectedFile = null;
let activeTab  = "url";
let cvOutputLang = "auto";  // what language to write the CV in

/* ─────────────────────────────────────────────────────────
   HELPERS
───────────────────────────────────────────────────────── */
function t(key) {
  return T[uiLang][key] ?? T["en"][key] ?? key;
}

function applyLang() {
  document.documentElement.lang = uiLang;

  // Update toggle label — show the OTHER language (what you'll switch TO)
  const labelEl = document.getElementById("lang-label");
  if (labelEl) labelEl.textContent = uiLang === "en" ? "ES" : "EN";

  // Translate all data-i18n elements
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.dataset.i18n;
    const val = T[uiLang][key];
    if (val !== undefined) el.innerHTML = val;
  });

  // Translate all placeholder attributes
  document.querySelectorAll("[data-i18n-ph]").forEach(el => {
    const key = el.dataset.i18nPh;
    const val = T[uiLang][key];
    if (val !== undefined) el.placeholder = val;
  });
}

function applyDark() {
  document.body.classList.toggle("dark", dark);
  document.getElementById("icon-sun")?.classList.toggle("hidden", dark);
  document.getElementById("icon-moon")?.classList.toggle("hidden", !dark);
}

/* ─────────────────────────────────────────────────────────
   BOOT
───────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  applyDark();
  applyLang();
  initUI();
});

/* ─────────────────────────────────────────────────────────
   LANGUAGE TOGGLE (UI language)
───────────────────────────────────────────────────────── */
document.addEventListener("click", e => {
  if (e.target.closest("#lang-toggle")) {
    uiLang = uiLang === "en" ? "es" : "en";
    localStorage.setItem("cv_ui_lang", uiLang);
    applyLang();
  }
});

/* ─────────────────────────────────────────────────────────
   DARK MODE
───────────────────────────────────────────────────────── */
document.addEventListener("click", e => {
  if (e.target.closest("#dark-toggle")) {
    dark = !dark;
    localStorage.setItem("cv_dark", dark);
    applyDark();
  }
});

/* ─────────────────────────────────────────────────────────
   UI INIT
───────────────────────────────────────────────────────── */
function initUI() {

  // ── Tab switcher
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-url")?.classList.toggle("hidden", activeTab !== "url");
      document.getElementById("tab-text")?.classList.toggle("hidden", activeTab !== "text");
    });
  });

  // ── CV output language pills
  document.querySelectorAll(".lang-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".lang-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      cvOutputLang = pill.dataset.cvLang;
    });
  });

  // ── Step 1 → 2
  document.getElementById("next-to-step2")?.addEventListener("click", () => {
    const url  = document.getElementById("job-url")?.value.trim();
    const text = document.getElementById("job-text")?.value.trim();
    if (!url && !text) { alert(t("alert_no_job")); return; }
    goToStep(2);
  });

  // ── Step 2 → 1
  document.getElementById("back-to-step1")?.addEventListener("click", () => goToStep(1));

  // ── File upload
  const uploadZone = document.getElementById("upload-zone");
  const fileInput  = document.getElementById("cv-file");

  uploadZone?.addEventListener("dragover", e => { e.preventDefault(); uploadZone.classList.add("dragover"); });
  uploadZone?.addEventListener("dragleave", () => uploadZone.classList.remove("dragover"));
  uploadZone?.addEventListener("drop", e => {
    e.preventDefault();
    uploadZone.classList.remove("dragover");
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  });
  fileInput?.addEventListener("change", () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });

  document.getElementById("change-file")?.addEventListener("click", () => {
    selectedFile = null;
    if (fileInput) fileInput.value = "";
    document.getElementById("file-selected")?.classList.add("hidden");
    document.getElementById("upload-zone")?.classList.remove("hidden");
    const btn = document.getElementById("generate-btn");
    if (btn) btn.disabled = true;
  });

  // ── Generate
  document.getElementById("generate-btn")?.addEventListener("click", handleGenerate);

  // ── Result buttons
  document.getElementById("try-again")?.addEventListener("click", () => goToStep(2));
  document.getElementById("start-over")?.addEventListener("click", resetAll);
}

/* ─────────────────────────────────────────────────────────
   FILE HANDLING
───────────────────────────────────────────────────────── */
function setFile(file) {
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (![".pdf", ".doc", ".docx"].includes(ext)) { alert(t("alert_bad_file")); return; }
  if (file.size > 10 * 1024 * 1024) { alert(t("alert_too_large")); return; }

  selectedFile = file;
  const nameEl = document.getElementById("file-name");
  if (nameEl) nameEl.textContent = file.name;
  document.getElementById("file-selected")?.classList.remove("hidden");
  document.getElementById("upload-zone")?.classList.add("hidden");
  const btn = document.getElementById("generate-btn");
  if (btn) btn.disabled = false;
}

/* ─────────────────────────────────────────────────────────
   STEP NAVIGATION
───────────────────────────────────────────────────────── */
function goToStep(n) {
  document.querySelectorAll(".step").forEach((el, i) => {
    const s = i + 1;
    el.classList.remove("active", "done");
    if (s < n)      el.classList.add("done");
    else if (s === n) el.classList.add("active");
  });

  document.getElementById("step-1")?.classList.toggle("hidden", n !== 1);
  document.getElementById("step-2")?.classList.toggle("hidden", n !== 2);
  document.getElementById("step-3")?.classList.toggle("hidden", n !== 3);
  document.getElementById("features")?.classList.toggle("hidden", n !== 1);

  if (n === 3) {
    document.getElementById("loading-state")?.classList.remove("hidden");
    document.getElementById("success-state")?.classList.add("hidden");
    document.getElementById("error-state")?.classList.add("hidden");
  }

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetAll() {
  selectedFile = null;
  const fileInput = document.getElementById("cv-file");
  if (fileInput) fileInput.value = "";
  const jobUrl = document.getElementById("job-url");
  if (jobUrl) jobUrl.value = "";
  const jobText = document.getElementById("job-text");
  if (jobText) jobText.value = "";
  document.getElementById("file-selected")?.classList.add("hidden");
  document.getElementById("upload-zone")?.classList.remove("hidden");
  const btn = document.getElementById("generate-btn");
  if (btn) btn.disabled = true;
  goToStep(1);
}

/* ─────────────────────────────────────────────────────────
   GENERATE
───────────────────────────────────────────────────────── */
async function handleGenerate() {
  if (!selectedFile) return;

  const jobUrl  = document.getElementById("job-url")?.value.trim() || "";
  const jobText = document.getElementById("job-text")?.value.trim() || "";

  goToStep(3);
  animateLoadingSteps();

  const formData = new FormData();
  formData.append("cv_file", selectedFile);
  formData.append("job_url", jobUrl);
  formData.append("job_text", jobText);
  formData.append("output_language", cvOutputLang);

  try {
    const resp = await fetch("/api/generate", { method: "POST", body: formData });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Generation failed");

    // Mark all steps done
    document.querySelectorAll(".step").forEach(el => { el.classList.remove("active"); el.classList.add("done"); });

    const subtitle = t("success_for")
      .replace("{title}", data.job_title || "")
      .replace("{company}", data.company || "");
    const subtitleEl = document.getElementById("success-subtitle");
    if (subtitleEl) subtitleEl.textContent = subtitle;

    const dlBtn = document.getElementById("download-btn");
    if (dlBtn) dlBtn.href = data.download_url;

    document.getElementById("loading-state")?.classList.add("hidden");
    document.getElementById("success-state")?.classList.remove("hidden");

  } catch (err) {
    document.getElementById("loading-state")?.classList.add("hidden");
    const errEl = document.getElementById("error-message");
    if (errEl) errEl.textContent = err.message;
    document.getElementById("error-state")?.classList.remove("hidden");
  }
}

/* ─────────────────────────────────────────────────────────
   LOADING ANIMATION
───────────────────────────────────────────────────────── */
function animateLoadingSteps() {
  const ids = ["ls-1","ls-2","ls-3","ls-4"];
  const steps = ids.map(id => document.getElementById(id));
  const delays = [0, 3000, 9000, 20000];

  steps.forEach(s => s && s.classList.remove("active","done"));
  steps[0]?.classList.add("active");

  delays.forEach((delay, i) => {
    if (i === 0) return;
    setTimeout(() => {
      if (document.getElementById("loading-state")?.classList.contains("hidden")) return;
      steps[i-1]?.classList.remove("active");
      steps[i-1]?.classList.add("done");
      steps[i]?.classList.add("active");
    }, delay);
  });
}
