/* Shared logic for /privacy and /terms pages */
(function () {
  const STORAGE_KEY = "cv_ui_lang";

  function getLang() {
    return localStorage.getItem(STORAGE_KEY) || "en";
  }

  function applyLang(lang) {
    document.querySelectorAll("[data-lang]").forEach(el => {
      el.style.display = el.dataset.lang === lang ? "" : "none";
    });
    const lbl = document.getElementById("lang-label");
    if (lbl) lbl.textContent = lang === "en" ? "ES" : "EN";
    document.documentElement.lang = lang;
  }

  function applyDark() {
    const dark = localStorage.getItem("cv_dark") === "true";
    document.body.classList.toggle("dark", dark);
    document.getElementById("icon-sun")?.classList.toggle("hidden", dark);
    document.getElementById("icon-moon")?.classList.toggle("hidden", !dark);
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyDark();
    applyLang(getLang());

    document.getElementById("lang-toggle")?.addEventListener("click", () => {
      const next = getLang() === "en" ? "es" : "en";
      localStorage.setItem(STORAGE_KEY, next);
      applyLang(next);
    });

    document.getElementById("dark-toggle")?.addEventListener("click", () => {
      const dark = !document.body.classList.contains("dark");
      document.body.classList.toggle("dark", dark);
      localStorage.setItem("cv_dark", dark);
      document.getElementById("icon-sun")?.classList.toggle("hidden", dark);
      document.getElementById("icon-moon")?.classList.toggle("hidden", !dark);
    });
  });
})();
