/* ── TRANSLATIONS ─────────────────────────────────────── */
const T = {
  en: {
    nav_history:"History", nav_new:"+ New CV", nav_signin:"Sign in",
    nav_billing:"Manage billing", nav_logout:"Sign out",
    hero_title:'Your CV, <span class="highlight">perfectly tailored</span><br>for every application',
    hero_subtitle:"Upload your CV, paste the job description, and get a professionally adapted CV in seconds — honest, curated, and ATS-optimized.",
    step1_label:"Job posting", step2_label:"Your CV", step3_label:"Download",
    s1_title:"Step 1 — Job posting",
    s1_desc:"Paste the LinkedIn URL or the full job description text below.",
    tab_url:"LinkedIn / URL", tab_text:"Paste text",
    url_label:"Job posting URL", url_ph:"https://www.linkedin.com/jobs/view/...",
    url_hint:'We\'ll try to fetch it automatically. If it fails, switch to "Paste text".',
    text_label:"Job description", text_ph:"Paste the full job description here (any language)...",
    output_lang_label:"CV output language",
    output_lang_hint:"Auto will match the language of the job posting",
    lang_auto:"Auto", lang_en:"English", lang_es:"Español",
    lang_fr:"Français", lang_pt:"Português", lang_de:"Deutsch",
    btn_continue:"Continue →",
    s2_title:"Step 2 — Upload your CV",
    s2_desc:"Upload your current CV in PDF or Word format.",
    upload_drop:"Drop your CV here or", upload_browse:"browse",
    upload_hint:"PDF, DOC or DOCX · Max 10 MB",
    btn_change:"Change", btn_back:"← Back", btn_generate:"Generate CV →",
    loading_title:"Crafting your tailored CV…",
    ls1:"Reading your CV", ls2:"Analyzing job requirements",
    ls3:"Rewriting and curating content", ls4:"Generating PDF",
    loading_note:"This usually takes 20–40 seconds",
    success_title:"Your CV is ready!",
    success_for:"CV adapted for {title} at {company}",
    btn_download:"Download PDF", btn_start_over:"Generate another",
    error_title:"Something went wrong", btn_retry:"Try again",
    f1_title:"Honest adaptation",
    f1_desc:"We only reframe what's already in your CV — no invented skills or experience.",
    f2_title:"Smart curation",
    f2_desc:"Irrelevant content is removed. Only what strengthens your application stays.",
    f3_title:"Professional PDF",
    f3_desc:"Clean, classic layout ready to impress recruiters and pass ATS filters.",
    // Pricing section
    pricing_title:"Simple, transparent pricing",
    pricing_subtitle:"Start free, pay only when you need more.",
    plan_free_label:"Free",
    plan_free_price:"$0",
    plan_free_f1:"{n} free CVs to try",
    plan_free_f2:"All features included",
    plan_free_f3:"No credit card needed",
    plan_free_btn:"Get started",
    plan_single_label:"Single CV",
    plan_single_f1:"1 tailored CV",
    plan_single_f2:"Never expires",
    plan_single_f3:"Instant PDF download",
    plan_single_btn:"Buy now",
    plan_monthly_label:"Monthly",
    plan_monthly_badge:"Best value",
    plan_monthly_f1:"30 CVs per month",
    plan_monthly_f2:"Extra CVs at $0.99 each",
    plan_monthly_f3:"Cancel anytime",
    plan_monthly_btn:"Subscribe",
    taxes_note:"Taxes may apply",
    footer_privacy:"Privacy Policy",
    footer_terms:"Terms & Conditions",
    hist_title:"Generation history",
    hist_view_posting:"View posting ↗", hist_preview:"Job description preview",
    hist_download:"Download PDF", hist_failed:"Failed", hist_processing:"Processing",
    empty_title:"No CVs generated yet",
    empty_desc:"Your generated CVs will appear here once you create one.",
    empty_cta:"Generate your first CV",
    alert_no_job:"Please enter a job URL or paste the job description text.",
    alert_bad_file:"Please upload a PDF or Word document (.pdf, .doc, .docx)",
    alert_too_large:"File is too large. Maximum 10 MB.",
    usage_free:"{n} free CV{s} left",
    usage_credits:"{n} credit{s} remaining",
    usage_monthly:"Monthly · {n} CV{s} left",
    usage_monthly_empty:"Monthly · No CVs left",
    usage_dev:"Dev mode",
    // Paywall
    paywall_title:"You've used your free CVs",
    paywall_desc:"Choose a plan to continue:",
    paywall_title_sub:"You've used all your monthly CVs",
    paywall_desc_sub:"Buy an extra CV or wait for your monthly renewal.",
    price_single_label:"Single CV",
    price_single_f1:"1 CV generation",
    price_single_f2:"Never expires",
    price_single_f3:"Download as PDF",
    price_single_btn:"Buy now",
    price_monthly_label:"Monthly",
    price_monthly_badge:"Best value",
    price_monthly_f1:"30 CVs per month",
    price_monthly_f2:"Cancel anytime",
    price_monthly_f3:"Extra CVs at $0.99 each",
    price_monthly_btn:"Subscribe",
    price_extra_label:"Extra CV",
    price_extra_f1:"1 CV generation",
    price_extra_f2:"Subscriber exclusive",
    price_extra_f3:"Download as PDF",
    price_extra_btn:"Buy extra CV",
    paywall_close:"Maybe later",
    // Claim state (anonymous → sign in to download)
    claim_title:"Your CV is ready!",
    claim_subtitle:"Sign in with Google to download it free — no credit card needed.",
    claim_btn:"Sign in to download free",
    claim_note:"One free CV per Google account.",
    // Login
    login_title:"Sign in to CV Matcher",
    login_subtitle:"Create tailored CVs for every job application.",
    login_email_label:"Your email address",
    login_email_ph:"you@example.com",
    login_btn:"Send magic link →",
    login_sent_title:"Check your email!",
    login_sent_desc:"We sent a magic link to:",
    login_no_password:"No password needed. One click and you're in.",
    // Payment success
    pay_success_title:"Payment successful!",
    pay_success_desc:"Your account has been updated. You can now generate CVs.",
    pay_success_btn:"Start generating →",
    pay_success_note:"A receipt has been sent to your email.",
  },
  es: {
    nav_history:"Historial", nav_new:"+ Nuevo CV", nav_signin:"Iniciar sesión",
    nav_billing:"Gestionar facturación", nav_logout:"Cerrar sesión",
    hero_title:'Tu CV, <span class="highlight">perfectamente adaptado</span><br>para cada solicitud',
    hero_subtitle:"Sube tu CV, pega la descripción de la vacante y obtén un CV profesionalmente adaptado en segundos — honesto, curado y optimizado para ATS.",
    step1_label:"Vacante", step2_label:"Tu CV", step3_label:"Descargar",
    s1_title:"Paso 1 — Vacante",
    s1_desc:"Pega el enlace de LinkedIn o el texto completo de la vacante.",
    tab_url:"LinkedIn / URL", tab_text:"Pegar texto",
    url_label:"URL de la vacante", url_ph:"https://www.linkedin.com/jobs/view/...",
    url_hint:'Intentaremos obtenerla automáticamente. Si falla, usa "Pegar texto".',
    text_label:"Descripción de la vacante", text_ph:"Pega aquí el texto completo de la vacante (en cualquier idioma)...",
    output_lang_label:"Idioma de salida del CV",
    output_lang_hint:"Auto detectará el idioma de la vacante",
    lang_auto:"Auto", lang_en:"English", lang_es:"Español",
    lang_fr:"Français", lang_pt:"Português", lang_de:"Deutsch",
    btn_continue:"Continuar →",
    s2_title:"Paso 2 — Sube tu CV",
    s2_desc:"Sube tu CV actual en formato PDF o Word.",
    upload_drop:"Arrastra tu CV aquí o", upload_browse:"busca",
    upload_hint:"PDF, DOC o DOCX · Máx. 10 MB",
    btn_change:"Cambiar", btn_back:"← Atrás", btn_generate:"Generar CV →",
    loading_title:"Creando tu CV adaptado…",
    ls1:"Leyendo tu CV", ls2:"Analizando los requisitos del puesto",
    ls3:"Reescribiendo y curando el contenido", ls4:"Generando el PDF",
    loading_note:"Esto suele tardar entre 20 y 40 segundos",
    success_title:"¡Tu CV está listo!",
    success_for:"CV adaptado para {title} en {company}",
    btn_download:"Descargar PDF", btn_start_over:"Generar otro",
    error_title:"Algo salió mal", btn_retry:"Intentar de nuevo",
    f1_title:"Adaptación honesta",
    f1_desc:"Solo reformulamos lo que ya está en tu CV — sin inventar habilidades ni experiencia.",
    f2_title:"Curación inteligente",
    f2_desc:"El contenido irrelevante se elimina. Solo queda lo que fortalece tu solicitud.",
    f3_title:"PDF profesional",
    f3_desc:"Diseño limpio y clásico listo para impresionar reclutadores y pasar filtros ATS.",
    pricing_title:"Precios simples y transparentes",
    pricing_subtitle:"Empieza gratis, paga solo cuando necesites más.",
    plan_free_label:"Gratis",
    plan_free_price:"$0",
    plan_free_f1:"{n} CVs gratis para probar",
    plan_free_f2:"Todas las funciones incluidas",
    plan_free_f3:"Sin tarjeta de crédito",
    plan_free_btn:"Empezar gratis",
    plan_single_label:"CV único",
    plan_single_f1:"1 CV adaptado",
    plan_single_f2:"Sin caducidad",
    plan_single_f3:"PDF instantáneo",
    plan_single_btn:"Comprar",
    plan_monthly_label:"Mensual",
    plan_monthly_badge:"Mejor valor",
    plan_monthly_f1:"30 CVs por mes",
    plan_monthly_f2:"CVs extra a $0.99 cada uno",
    plan_monthly_f3:"Cancela en cualquier momento",
    plan_monthly_btn:"Suscribirse",
    taxes_note:"Pueden aplicarse impuestos",
    footer_privacy:"Política de Privacidad",
    footer_terms:"Términos y Condiciones",
    hist_title:"Historial de generaciones",
    hist_view_posting:"Ver vacante ↗", hist_preview:"Vista previa de la vacante",
    hist_download:"Descargar PDF", hist_failed:"Fallido", hist_processing:"Procesando",
    empty_title:"Aún no hay CVs generados",
    empty_desc:"Tus CVs generados aparecerán aquí una vez que crees uno.",
    empty_cta:"Genera tu primer CV",
    alert_no_job:"Por favor ingresa una URL o pega el texto de la vacante.",
    alert_bad_file:"Por favor sube un PDF o documento Word (.pdf, .doc, .docx)",
    alert_too_large:"El archivo es demasiado grande. Máximo 10 MB.",
    usage_free:"Te quedan {n} CV{s} gratis",
    usage_credits:"Te quedan {n} crédito{s}",
    usage_monthly:"Mensual · {n} CV{s} restante{s}",
    usage_monthly_empty:"Mensual · Sin CVs disponibles",
    usage_dev:"Modo desarrollo",
    paywall_title:"Has usado tus CVs gratuitos",
    paywall_desc:"Elige una opción para continuar:",
    paywall_title_sub:"Has usado todos tus CVs del mes",
    paywall_desc_sub:"Compra un CV extra o espera a tu renovación mensual.",
    price_single_label:"CV único",
    price_single_f1:"1 generación de CV",
    price_single_f2:"Sin caducidad",
    price_single_f3:"Descarga en PDF",
    price_single_btn:"Comprar",
    price_monthly_label:"Mensual",
    price_monthly_badge:"Mejor valor",
    price_monthly_f1:"30 CVs por mes",
    price_monthly_f2:"Cancela en cualquier momento",
    price_monthly_f3:"CVs extra a $0.99 cada uno",
    price_monthly_btn:"Suscribirse",
    price_extra_label:"CV extra",
    price_extra_f1:"1 generación de CV",
    price_extra_f2:"Solo para suscriptores",
    price_extra_f3:"Descarga en PDF",
    price_extra_btn:"Comprar CV extra",
    paywall_close:"Quizás más tarde",
    // Claim state
    claim_title:"¡Tu CV está listo!",
    claim_subtitle:"Inicia sesión con Google para descargarlo gratis — sin tarjeta de crédito.",
    claim_btn:"Iniciar sesión para descargar gratis",
    claim_note:"Un CV gratis por cuenta de Google.",
    login_title:"Inicia sesión en CV Matcher",
    login_subtitle:"Crea CVs adaptados para cada solicitud de empleo.",
    login_email_label:"Tu correo electrónico",
    login_email_ph:"tú@ejemplo.com",
    login_btn:"Enviar enlace mágico →",
    login_sent_title:"¡Revisa tu correo!",
    login_sent_desc:"Enviamos un enlace mágico a:",
    login_no_password:"Sin contraseña. Un clic y listo.",
    pay_success_title:"¡Pago exitoso!",
    pay_success_desc:"Tu cuenta ha sido actualizada. Ya puedes generar CVs.",
    pay_success_btn:"Empezar a generar →",
    pay_success_note:"El recibo fue enviado a tu correo.",
  },
};

/* ── STATE ─────────────────────────────────────────────── */
let uiLang       = localStorage.getItem("cv_ui_lang") || "en";
let dark         = localStorage.getItem("cv_dark") === "true";
let selectedFile = null;
let activeTab    = "url";
let cvOutputLang = "auto";
let userInfo     = null;   // cached /api/user response

/* ── I18N ──────────────────────────────────────────────── */
function t(key, vars = {}) {
  let s = T[uiLang][key] ?? T.en[key] ?? key;
  Object.entries(vars).forEach(([k, v]) => { s = s.replace(`{${k}}`, v); });
  return s;
}

function applyLang() {
  document.documentElement.lang = uiLang;
  const lbl = document.getElementById("lang-label");
  if (lbl) lbl.textContent = uiLang === "en" ? "ES" : "EN";
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const val = T[uiLang][el.dataset.i18n];
    if (val !== undefined) el.innerHTML = val;
  });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => {
    const val = T[uiLang][el.dataset.i18nPh];
    if (val !== undefined) el.placeholder = val;
  });
  // Expose for history page
  window._T_HIST = T[uiLang];
}

/* ── DARK MODE ─────────────────────────────────────────── */
function applyDark() {
  document.body.classList.toggle("dark", dark);
  document.getElementById("icon-sun")?.classList.toggle("hidden", dark);
  document.getElementById("icon-moon")?.classList.toggle("hidden", !dark);
}

/* ── BOOT ──────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async () => {
  applyDark();
  applyLang();
  initUI();
  await initAuth();
  // Free plan description uses FREE_LIMIT variable
  const freeF1 = document.getElementById("free-f1");
  if (freeF1) freeF1.textContent = t("plan_free_f1", { n: window.FREE_LIMIT || 3 });

  // Auto-download after claim: /?download=<genId>
  const params = new URLSearchParams(window.location.search);
  const genId = params.get("download");
  if (genId && window.AUTH_ENABLED) {
    history.replaceState({}, "", "/");
    try {
      const headers = await getAuthHeaders();
      const resp = await fetch(`/api/download/${genId}`, { headers });
      if (resp.ok) {
        const blob = await resp.blob();
        const cd = resp.headers.get("content-disposition") || "";
        const fnMatch = cd.match(/filename="?([^"]+)"?/);
        const filename = fnMatch ? fnMatch[1] : "CV.pdf";
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = filename; a.click();
        URL.revokeObjectURL(url);
      }
    } catch (e) { /* ignore */ }
  }
});

/* ── TOGGLES (lang + dark) ─────────────────────────────── */
document.addEventListener("click", e => {
  if (e.target.closest("#lang-toggle")) {
    uiLang = uiLang === "en" ? "es" : "en";
    localStorage.setItem("cv_ui_lang", uiLang);
    applyLang();
  }
  if (e.target.closest("#dark-toggle")) {
    dark = !dark;
    localStorage.setItem("cv_dark", dark);
    applyDark();
  }
});

/* ── AUTH INIT ─────────────────────────────────────────── */
async function initAuth() {
  if (!window.AUTH_ENABLED) {
    // Dev mode: hide login button, hide user menu
    document.getElementById("login-btn")?.style.setProperty("display", "none");
    document.getElementById("user-menu")?.classList.add("hidden");
    userInfo = { plan: "dev", credits: 999, free_remaining: 999 };
    updateUsageBadge(userInfo);
    return;
  }

  const session = await getSession();

  if (!session) {
    // Not logged in
    document.getElementById("login-btn")?.style.setProperty("display", "inline-flex");
    document.getElementById("user-menu")?.classList.add("hidden");
    document.getElementById("history-link")?.classList.add("hidden");
    return;
  }

  // Logged in
  document.getElementById("login-btn")?.style.setProperty("display", "none");
  document.getElementById("history-link")?.classList.add("hidden");
  const userMenu = document.getElementById("user-menu");
  if (userMenu) userMenu.classList.remove("hidden");

  const email = session.user.email || "";
  const avatarBtn = document.getElementById("user-avatar-btn");
  if (avatarBtn) avatarBtn.textContent = email[0].toUpperCase();
  const dropEmail = document.getElementById("dropdown-email");
  if (dropEmail) dropEmail.textContent = email;

  // Load user info
  try {
    const headers = await getAuthHeaders();
    const resp = await fetch("/api/user", { headers });
    if (resp.ok) {
      userInfo = await resp.json();
      updateUsageBadge(userInfo);
    }
  } catch (e) { /* ignore */ }

  // Pre-populate pricing amounts
  const singleAmt = document.getElementById("price-single-amount");
  if (singleAmt) singleAmt.textContent = window.PRICE_SINGLE_DISPLAY;
  const monthlyAmt = document.getElementById("price-monthly-amount");
  if (monthlyAmt) monthlyAmt.textContent = window.PRICE_MONTHLY_DISPLAY;
  const extraAmt = document.getElementById("price-extra-amount");
  if (extraAmt) extraAmt.textContent = window.PRICE_EXTRA_DISPLAY;
}

function updateUsageBadge(info) {
  const badge = document.getElementById("usage-badge");
  if (!badge) return;
  badge.classList.remove("hidden");
  const plan = info.plan;
  if (plan === "dev") {
    badge.textContent = t("usage_dev");
    badge.className = "usage-badge badge-dev";
  } else if (plan === "monthly") {
    const n = info.credits || 0;
    if (n > 0) {
      badge.textContent = t("usage_monthly", { n, s: n !== 1 ? "s" : "" });
      badge.className = "usage-badge badge-pro";
    } else {
      badge.textContent = t("usage_monthly_empty");
      badge.className = "usage-badge badge-empty";
    }
  } else if (plan === "credits") {
    const n = info.credits || 0;
    badge.textContent = t("usage_credits", { n, s: n !== 1 ? "s" : "" });
    badge.className = "usage-badge badge-credits";
  } else {
    const n = Math.max(0, (info.free_remaining ?? 0));
    badge.textContent = t("usage_free", { n, s: n !== 1 ? "s" : "" });
    badge.className = `usage-badge ${n === 0 ? "badge-empty" : "badge-free"}`;
  }
}

/* ── USER MENU DROPDOWN ────────────────────────────────── */
document.addEventListener("click", async e => {
  const dropdown = document.getElementById("user-dropdown");
  if (!dropdown) return;

  if (e.target.closest("#user-avatar-btn")) {
    dropdown.classList.toggle("hidden");
    return;
  }
  if (!e.target.closest("#user-menu")) {
    dropdown.classList.add("hidden");
  }
  if (e.target.closest("#logout-btn")) {
    await signOut();
  }
  if (e.target.closest("#billing-btn")) {
    dropdown.classList.add("hidden");
    const headers = await getAuthHeaders();
    const resp = await fetch("/api/billing-portal", { method: "POST", headers });
    if (resp.ok) {
      const { portal_url } = await resp.json();
      window.location.href = portal_url;
    }
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
      document.getElementById("tab-url")?.classList.toggle("hidden", activeTab !== "url");
      document.getElementById("tab-text")?.classList.toggle("hidden", activeTab !== "text");
    });
  });

  // CV output language pills
  document.querySelectorAll(".lang-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".lang-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      cvOutputLang = pill.dataset.cvLang;
    });
  });

  // Step navigation
  document.getElementById("next-to-step2")?.addEventListener("click", () => {
    const url = document.getElementById("job-url")?.value.trim();
    const txt = document.getElementById("job-text")?.value.trim();
    if (!url && !txt) { alert(t("alert_no_job")); return; }
    goToStep(2);
  });
  document.getElementById("back-to-step1")?.addEventListener("click", () => goToStep(1));

  // File upload
  const zone = document.getElementById("upload-zone");
  const fi = document.getElementById("cv-file");
  zone?.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("dragover"); });
  zone?.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone?.addEventListener("drop", e => { e.preventDefault(); zone.classList.remove("dragover"); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });
  fi?.addEventListener("change", () => { if (fi.files[0]) setFile(fi.files[0]); });
  document.getElementById("change-file")?.addEventListener("click", () => {
    selectedFile = null;
    if (fi) fi.value = "";
    document.getElementById("file-selected")?.classList.add("hidden");
    zone?.classList.remove("hidden");
    const btn = document.getElementById("generate-btn");
    if (btn) btn.disabled = true;
  });

  // Generate
  document.getElementById("generate-btn")?.addEventListener("click", handleGenerate);
  document.getElementById("try-again")?.addEventListener("click", () => goToStep(2));
  document.getElementById("start-over")?.addEventListener("click", resetAll);

  // Download button: fetch with auth headers → blob → trigger download
  document.getElementById("download-btn")?.addEventListener("click", async (e) => {
    e.preventDefault();
    const url = document.getElementById("download-btn")?.getAttribute("href");
    if (!url || url === "#") return;
    try {
      const headers = await getAuthHeaders();
      const resp = await fetch(url, { headers });
      if (!resp.ok) throw new Error();
      const blob = await resp.blob();
      const cd = resp.headers.get("content-disposition") || "";
      const m = cd.match(/filename="?([^"]+)"?/);
      const fname = m ? m[1] : "CV.pdf";
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = fname;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch {
      alert("Download failed. Please try again.");
    }
  });

  // Claim sign-in button
  document.getElementById("claim-btn")?.addEventListener("click", () => {
    if (window.signInWithGoogle) signInWithGoogle();
    else window.location.href = "/login";
  });

  // Paywall
  document.getElementById("paywall-close")?.addEventListener("click", () => {
    document.getElementById("paywall-modal")?.classList.add("hidden");
  });
  document.getElementById("buy-single-btn")?.addEventListener("click", () => startCheckout("single"));
  document.getElementById("buy-monthly-btn")?.addEventListener("click", () => startCheckout("monthly"));
  document.getElementById("buy-extra-btn")?.addEventListener("click", () => startCheckout("extra"));
}

/* ── FILE ──────────────────────────────────────────────── */
function setFile(file) {
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (![".pdf", ".doc", ".docx"].includes(ext)) { alert(t("alert_bad_file")); return; }
  if (file.size > 10 * 1024 * 1024) { alert(t("alert_too_large")); return; }
  selectedFile = file;
  document.getElementById("file-name").textContent = file.name;
  document.getElementById("file-selected")?.classList.remove("hidden");
  document.getElementById("upload-zone")?.classList.add("hidden");
  document.getElementById("generate-btn").disabled = false;
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

function resetAll() {
  selectedFile = null;
  const fi = document.getElementById("cv-file");
  if (fi) fi.value = "";
  const ju = document.getElementById("job-url"); if (ju) ju.value = "";
  const jt = document.getElementById("job-text"); if (jt) jt.value = "";
  document.getElementById("file-selected")?.classList.add("hidden");
  document.getElementById("upload-zone")?.classList.remove("hidden");
  document.getElementById("generate-btn").disabled = true;
  goToStep(1);
}

/* ── GENERATE ──────────────────────────────────────────── */
async function handleGenerate() {
  if (!selectedFile) return;

  // Only block authenticated users who've exhausted credits
  if (window.AUTH_ENABLED && userInfo && userInfo.can_generate === false) {
    showPaywall();
    return;
  }

  goToStep(3);
  animateLoadingSteps();

  const formData = new FormData();
  formData.append("cv_file", selectedFile);
  formData.append("job_url", document.getElementById("job-url")?.value.trim() || "");
  formData.append("job_text", document.getElementById("job-text")?.value.trim() || "");
  formData.append("output_language", cvOutputLang);

  try {
    const headers = await getAuthHeaders();
    const resp = await fetch("/api/generate", { method: "POST", body: formData, headers });
    const data = await resp.json();

    if (resp.status === 402) {
      goToStep(2);
      showPaywall();
      return;
    }
    if (!resp.ok) throw new Error(data.detail || "Generation failed");

    document.querySelectorAll(".step").forEach(el => { el.classList.remove("active"); el.classList.add("done"); });
    document.getElementById("loading-state")?.classList.add("hidden");

    if (data.claim_token) {
      // Anonymous generation — gate download behind sign-in
      showClaimState(data.claim_token, data.job_title, data.company);
    } else {
      // Authenticated generation — show download button
      const subtitle = t("success_for").replace("{title}", data.job_title || "").replace("{company}", data.company || "");
      document.getElementById("success-subtitle").textContent = subtitle;
      document.getElementById("download-btn").href = data.download_url;
      document.getElementById("success-state")?.classList.remove("hidden");

      // Refresh usage badge
      if (window.AUTH_ENABLED) {
        const authH = await getAuthHeaders();
        const ur = await fetch("/api/user", { headers: authH });
        if (ur.ok) { userInfo = await ur.json(); updateUsageBadge(userInfo); }
      }
    }

  } catch (err) {
    document.getElementById("loading-state")?.classList.add("hidden");
    document.getElementById("error-message").textContent = err.message;
    document.getElementById("error-state")?.classList.remove("hidden");
  }
}

/* ── CLAIM STATE ───────────────────────────────────────── */
function showClaimState(claimToken, jobTitle, company) {
  localStorage.setItem("cv_claim_token", claimToken);
  const subtitle = t("success_for").replace("{title}", jobTitle || "").replace("{company}", company || "");
  document.getElementById("claim-subtitle").textContent = subtitle;
  document.getElementById("claim-title-el").textContent = t("claim_title");
  document.getElementById("claim-cta").textContent = t("claim_subtitle");
  document.getElementById("claim-btn-label").textContent = t("claim_btn");
  document.getElementById("claim-note").textContent = t("claim_note");
  document.getElementById("claim-state")?.classList.remove("hidden");
}

/* ── PAYWALL ───────────────────────────────────────────── */
function showPaywall() {
  const isSubscriberEmpty = userInfo && userInfo.plan === "monthly" && (userInfo.credits || 0) === 0;
  document.getElementById("paywall-cards-default")?.classList.toggle("hidden", isSubscriberEmpty);
  document.getElementById("paywall-cards-extra")?.classList.toggle("hidden", !isSubscriberEmpty);

  const titleEl = document.getElementById("paywall-title-el");
  const descEl  = document.getElementById("paywall-desc-el");
  if (titleEl) titleEl.textContent = t(isSubscriberEmpty ? "paywall_title_sub" : "paywall_title");
  if (descEl)  descEl.textContent  = t(isSubscriberEmpty ? "paywall_desc_sub"  : "paywall_desc");

  const singleAmt = document.getElementById("price-single-amount");
  if (singleAmt) singleAmt.textContent = window.PRICE_SINGLE_DISPLAY || "";
  const monthlyAmt = document.getElementById("price-monthly-amount");
  if (monthlyAmt) monthlyAmt.textContent = window.PRICE_MONTHLY_DISPLAY || "";
  const extraAmt = document.getElementById("price-extra-amount");
  if (extraAmt) extraAmt.textContent = window.PRICE_EXTRA_DISPLAY || "";

  document.getElementById("paywall-modal")?.classList.remove("hidden");
}

async function startCheckout(product) {
  document.getElementById("paywall-modal")?.classList.add("hidden");
  const headers = await getAuthHeaders();
  const form = new FormData();
  form.append("product", product);
  const resp = await fetch("/api/create-checkout", { method: "POST", body: form, headers });
  if (resp.ok) {
    const { checkout_url } = await resp.json();
    window.location.href = checkout_url;
  } else {
    alert("Could not start checkout. Please try again.");
  }
}

/* ── LOADING ANIMATION ─────────────────────────────────── */
function animateLoadingSteps() {
  const steps = ["ls-1","ls-2","ls-3","ls-4"].map(id => document.getElementById(id));
  const delays = [0, 3000, 9000, 20000];
  steps.forEach(s => s?.classList.remove("active","done"));
  steps[0]?.classList.add("active");
  delays.forEach((delay, i) => {
    if (i === 0) return;
    setTimeout(() => {
      if (document.getElementById("loading-state")?.classList.contains("hidden")) return;
      steps[i-1]?.classList.remove("active"); steps[i-1]?.classList.add("done");
      steps[i]?.classList.add("active");
    }, delay);
  });
}
