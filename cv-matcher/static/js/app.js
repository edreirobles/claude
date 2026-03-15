/* ── TRANSLATIONS ──────────────────────────────────────── */
const T = {
  en: {
    nav_history:    "History",
    nav_new:        "+ New CV",
    hero_title:     'Your CV, <span class="highlight">perfectly tailored</span><br>for every application',
    hero_subtitle:  "Upload your CV, paste the job description, and get a professionally adapted CV in seconds — honest and optimized for the role.",
    step1_label:    "Job posting",
    step2_label:    "Your CV",
    step3_label:    "Download",
    s1_title:       "Step 1 — Job posting",
    s1_desc:        "Paste the LinkedIn URL or the full job description text below.",
    tab_url:        "LinkedIn / URL",
    tab_text:       "Paste text",
    url_label:      "Job posting URL",
    url_placeholder:"https://www.linkedin.com/jobs/view/...",
    url_hint:       'We\'ll try to fetch it automatically. If it fails, switch to "Paste text".',
    text_label:     "Job description",
    text_placeholder:"Paste the full job description here (any language)...",
    btn_continue:   "Continue →",
    s2_title:       "Step 2 — Upload your CV",
    s2_desc:        "Upload your current CV in PDF or Word format.",
    upload_label:   "Drop your CV here or",
    upload_browse:  "browse",
    upload_hint:    "PDF, DOC or DOCX · Max 10 MB",
    btn_change:     "Change",
    btn_back:       "← Back",
    btn_generate:   "Generate CV →",
    loading_title:  "Crafting your tailored CV…",
    ls1:            "Reading your CV",
    ls2:            "Analyzing job requirements",
    ls3:            "Rewriting and optimizing",
    ls4:            "Generating PDF",
    loading_note:   "This usually takes 20–40 seconds",
    success_title:  "Your CV is ready!",
    btn_download:   "Download PDF",
    btn_start_over: "Generate another",
    error_title:    "Something went wrong",
    btn_retry:      "Try again",
    f1_title:       "Honest adaptation",
    f1_desc:        "We only reframe what's already true — no invented experience, no lies.",
    f2_title:       "Keyword optimized",
    f2_desc:        "Your CV speaks the language of the job posting, improving ATS scoring.",
    f3_title:       "Professional PDF",
    f3_desc:        "Clean, classic layout designed to impress — ready to send immediately.",
    hist_title:     "Generation history",
    hist_view_posting: "View posting ↗",
    hist_preview:   "Job description preview",
    hist_download:  "Download PDF",
    hist_failed:    "Failed",
    hist_processing:"Processing",
    empty_title:    "No CVs generated yet",
    empty_desc:     "Your generated CVs will appear here once you create one.",
    empty_cta:      "Generate your first CV",
    success_for:    "CV adapted for {title} at {company}",
  },
  es: {
    nav_history:    "Historial",
    nav_new:        "+ Nuevo CV",
    hero_title:     'Tu CV, <span class="highlight">perfectamente adaptado</span><br>para cada solicitud',
    hero_subtitle:  "Sube tu CV, pega la descripción del trabajo y obtén un CV profesionalmente adaptado en segundos — honesto y optimizado para el puesto.",
    step1_label:    "Vacante",
    step2_label:    "Tu CV",
    step3_label:    "Descargar",
    s1_title:       "Paso 1 — Vacante",
    s1_desc:        "Pega el enlace de LinkedIn o el texto completo de la vacante.",
    tab_url:        "LinkedIn / URL",
    tab_text:       "Pegar texto",
    url_label:      "URL de la vacante",
    url_placeholder:"https://www.linkedin.com/jobs/view/...",
    url_hint:       'Intentaremos obtenerla automáticamente. Si falla, usa "Pegar texto".',
    text_label:     "Descripción de la vacante",
    text_placeholder:"Pega aquí el texto completo de la vacante (en cualquier idioma)...",
    btn_continue:   "Continuar →",
    s2_title:       "Paso 2 — Sube tu CV",
    s2_desc:        "Sube tu CV actual en formato PDF o Word.",
    upload_label:   "Arrastra tu CV aquí o",
    upload_browse:  "busca",
    upload_hint:    "PDF, DOC o DOCX · Máx. 10 MB",
    btn_change:     "Cambiar",
    btn_back:       "← Atrás",
    btn_generate:   "Generar CV →",
    loading_title:  "Creando tu CV adaptado…",
    ls1:            "Leyendo tu CV",
    ls2:            "Analizando los requisitos del puesto",
    ls3:            "Reescribiendo y optimizando",
    ls4:            "Generando PDF",
    loading_note:   "Esto suele tardar entre 20 y 40 segundos",
    success_title:  "¡Tu CV está listo!",
    btn_download:   "Descargar PDF",
    btn_start_over: "Generar otro",
    error_title:    "Algo salió mal",
    btn_retry:      "Intentar de nuevo",
    f1_title:       "Adaptación honesta",
    f1_desc:        "Solo reformulamos lo que ya es verdad — sin experiencia inventada, sin mentiras.",
    f2_title:       "Optimizado por palabras clave",
    f2_desc:        "Tu CV habla el idioma de la oferta de trabajo, mejorando el score en ATS.",
    f3_title:       "PDF profesional",
    f3_desc:        "Diseño limpio y clásico listo para impresionar — puedes enviarlo de inmediato.",
    hist_title:     "Historial de generaciones",
    hist_view_posting: "Ver vacante ↗",
    hist_preview:   "Vista previa de la vacante",
    hist_download:  "Descargar PDF",
    hist_failed:    "Fallido",
    hist_processing:"Procesando",
    empty_title:    "Aún no hay CVs generados",
    empty_desc:     "Tus CVs generados aparecerán aquí una vez que crees uno.",
    empty_cta:      "Genera tu primer CV",
    success_for:    "CV adaptado para {title} en {company}",
  },
};

/* ── STATE ─────────────────────────────────────────────── */
let lang = localStorage.getItem("cv_lang") || "en";
let dark = localStorage.getItem("cv_dark") === "true";
let selectedFile = null;
let activeTab = "url";

/* ── INIT ──────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  applyDark();
  applyLang();
  initUI();
});

/* ── LANGUAGE ──────────────────────────────────────────── */
function applyLang() {
  document.documentElement.lang = lang;
  const labelEl = document.getElementById("lang-label");
  if (labelEl) labelEl.textContent = lang === "en" ? "ES" : "EN";

  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.dataset.i18n;
    if (T[lang][key] !== undefined) {
      el.innerHTML = T[lang][key];
    }
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    const key = el.dataset.i18nPlaceholder;
    if (T[lang][key] !== undefined) {
      el.placeholder = T[lang][key];
    }
  });
}

document.addEventListener("click", e => {
  if (e.target.closest("#lang-toggle")) {
    lang = lang === "en" ? "es" : "en";
    localStorage.setItem("cv_lang", lang);
    applyLang();
  }
});

/* ── DARK MODE ─────────────────────────────────────────── */
function applyDark() {
  document.body.classList.toggle("dark", dark);
  const sun = document.getElementById("icon-sun");
  const moon = document.getElementById("icon-moon");
  if (sun) sun.classList.toggle("hidden", dark);
  if (moon) moon.classList.toggle("hidden", !dark);
}

document.addEventListener("click", e => {
  if (e.target.closest("#dark-toggle")) {
    dark = !dark;
    localStorage.setItem("cv_dark", dark);
    applyDark();
  }
});

/* ── UI INIT ───────────────────────────────────────────── */
function initUI() {
  // Tabs
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      btn.classList.add("active");
      const urlPanel = document.getElementById("tab-url");
      const textPanel = document.getElementById("tab-text");
      if (urlPanel) urlPanel.classList.toggle("hidden", activeTab !== "url");
      if (textPanel) textPanel.classList.toggle("hidden", activeTab !== "text");
    });
  });

  // Step navigation
  const nextBtn = document.getElementById("next-to-step2");
  if (nextBtn) nextBtn.addEventListener("click", () => {
    const url = document.getElementById("job-url")?.value.trim();
    const text = document.getElementById("job-text")?.value.trim();
    if (!url && !text) {
      alert(lang === "es"
        ? "Por favor ingresa una URL o pega el texto de la vacante."
        : "Please enter a job URL or paste the job description text.");
      return;
    }
    goToStep(2);
  });

  const backBtn = document.getElementById("back-to-step1");
  if (backBtn) backBtn.addEventListener("click", () => goToStep(1));

  // File upload
  const uploadZone = document.getElementById("upload-zone");
  const fileInput = document.getElementById("cv-file");

  if (uploadZone) {
    uploadZone.addEventListener("dragover", e => { e.preventDefault(); uploadZone.classList.add("dragover"); });
    uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragover"));
    uploadZone.addEventListener("drop", e => {
      e.preventDefault();
      uploadZone.classList.remove("dragover");
      if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
    });
  }

  if (fileInput) fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
  });

  const changeBtn = document.getElementById("change-file");
  if (changeBtn) changeBtn.addEventListener("click", () => {
    selectedFile = null;
    if (fileInput) fileInput.value = "";
    document.getElementById("file-selected")?.classList.add("hidden");
    document.getElementById("upload-zone")?.classList.remove("hidden");
    const genBtn = document.getElementById("generate-btn");
    if (genBtn) genBtn.disabled = true;
  });

  // Generate
  const generateBtn = document.getElementById("generate-btn");
  if (generateBtn) generateBtn.addEventListener("click", handleGenerate);

  // Result actions
  document.getElementById("try-again")?.addEventListener("click", () => goToStep(2));
  document.getElementById("start-over")?.addEventListener("click", () => {
    selectedFile = null;
    if (fileInput) fileInput.value = "";
    document.getElementById("job-url") && (document.getElementById("job-url").value = "");
    document.getElementById("job-text") && (document.getElementById("job-text").value = "");
    document.getElementById("file-selected")?.classList.add("hidden");
    document.getElementById("upload-zone")?.classList.remove("hidden");
    const genBtn = document.getElementById("generate-btn");
    if (genBtn) genBtn.disabled = true;
    goToStep(1);
  });
}

/* ── FILE ──────────────────────────────────────────────── */
function setFile(file) {
  const allowed = [".pdf", ".doc", ".docx"];
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!allowed.includes(ext)) {
    alert(lang === "es"
      ? "Por favor sube un PDF o documento Word (.pdf, .doc, .docx)"
      : "Please upload a PDF or Word document (.pdf, .doc, .docx)");
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    alert(lang === "es" ? "El archivo es demasiado grande. Máximo 10 MB." : "File is too large. Maximum 10 MB.");
    return;
  }
  selectedFile = file;
  const nameEl = document.getElementById("file-name");
  if (nameEl) nameEl.textContent = file.name;
  document.getElementById("file-selected")?.classList.remove("hidden");
  document.getElementById("upload-zone")?.classList.add("hidden");
  const genBtn = document.getElementById("generate-btn");
  if (genBtn) genBtn.disabled = false;
}

/* ── STEP NAVIGATION ───────────────────────────────────── */
function goToStep(n) {
  document.querySelectorAll(".step").forEach((el, i) => {
    const s = i + 1;
    el.classList.remove("active", "done");
    if (s < n) el.classList.add("done");
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

/* ── GENERATE ──────────────────────────────────────────── */
async function handleGenerate() {
  if (!selectedFile) return;

  const url = document.getElementById("job-url")?.value.trim() || "";
  const text = document.getElementById("job-text")?.value.trim() || "";

  goToStep(3);
  animateLoadingSteps();

  const formData = new FormData();
  formData.append("cv_file", selectedFile);
  formData.append("job_url", url);
  formData.append("job_text", text);

  try {
    const resp = await fetch("/api/generate", { method: "POST", body: formData });
    const data = await resp.json();

    if (!resp.ok) throw new Error(data.detail || "Generation failed");

    document.querySelectorAll(".step").forEach(el => { el.classList.remove("active"); el.classList.add("done"); });

    const tmpl = T[lang]["success_for"] || "CV adapted for {title} at {company}";
    const subtitleEl = document.getElementById("success-subtitle");
    if (subtitleEl) subtitleEl.textContent = tmpl
      .replace("{title}", data.job_title)
      .replace("{company}", data.company);

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

/* ── LOADING ANIMATION ─────────────────────────────────── */
function animateLoadingSteps() {
  const steps = ["ls-1", "ls-2", "ls-3", "ls-4"].map(id => document.getElementById(id));
  const delays = [0, 3000, 9000, 20000];
  steps.forEach(s => s && s.classList.remove("active", "done"));
  if (steps[0]) steps[0].classList.add("active");
  delays.forEach((delay, i) => {
    if (i === 0) return;
    setTimeout(() => {
      if (document.getElementById("loading-state")?.classList.contains("hidden")) return;
      if (steps[i - 1]) { steps[i - 1].classList.remove("active"); steps[i - 1].classList.add("done"); }
      if (steps[i]) steps[i].classList.add("active");
    }, delay);
  });
}
