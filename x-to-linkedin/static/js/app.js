/* ═══════════════════════════════════════════════════
   X → LinkedIn AI Publisher — Frontend Logic
   ═══════════════════════════════════════════════════ */

'use strict';

// ── Estado global ──────────────────────────────────────
const state = {
  tweetData: null,
  generatedText: '',
  suggestedImages: [],
  selectedImageIndex: 0,   // 0 = ninguna, 1+ = imagen índice-1
  linkedInConnected: false,
  mediaType: 'auto',        // image | video | document | generate | auto
  pdfUrl: null,
  documentTitle: 'Documento',
};

// ── Inicialización ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkAuthStatus();
  loadHistory();
  setupCharCounter();
  checkUrlParams();
  setDefaultScheduleTime();
  loadXMonitorStatus();
});

function checkUrlParams() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('connected') === 'true') {
    showToast('¡LinkedIn conectado exitosamente!', 'success');
    history.replaceState({}, '', '/');
    checkAuthStatus();
  }
  if (params.get('error')) {
    showToast(`Error de autenticación: ${params.get('error')}`, 'error');
    history.replaceState({}, '', '/');
  }
}

function setDefaultScheduleTime() {
  const dt = document.getElementById('schedule-datetime');
  if (!dt) return;
  const now = new Date();
  now.setHours(now.getHours() + 1);
  now.setMinutes(0, 0, 0);
  // Formato datetime-local: YYYY-MM-DDTHH:MM
  dt.value = now.toISOString().slice(0, 16);
  dt.min = new Date().toISOString().slice(0, 16);
}

function setupCharCounter() {
  const textarea = document.getElementById('linkedin-text');
  const counter  = document.getElementById('char-count');
  if (!textarea || !counter) return;
  textarea.addEventListener('input', () => {
    const len = textarea.value.length;
    counter.textContent = len;
    counter.parentElement.classList.toggle('over', len > 3000);
  });
}

// ── Auth / LinkedIn Status ─────────────────────────────
async function checkAuthStatus() {
  try {
    const res = await fetch('/auth/status');
    const data = await res.json();
    state.linkedInConnected = data.connected;
    updateAuthUI(data);
  } catch (e) {
    console.error('Error checking auth:', e);
  }
}

function updateAuthUI(data) {
  const container = document.getElementById('auth-status');
  if (!container) return;

  if (data.connected) {
    container.innerHTML = `
      <div class="auth-user">
        ${data.person_picture ? `<img src="${escHtml(data.person_picture)}" class="auth-avatar" alt="avatar" />` : ''}
        <span class="auth-name">${escHtml(data.person_name || 'LinkedIn')}</span>
        <button class="btn btn-ghost btn-sm" onclick="disconnectLinkedIn()" title="Desconectar">✕</button>
      </div>
    `;
  } else {
    container.innerHTML = `
      <button class="btn btn-secondary btn-sm" onclick="connectLinkedIn()">
        Conectar LinkedIn
      </button>
    `;
  }
}

function connectLinkedIn() {
  document.getElementById('modal-connect').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-connect').classList.add('hidden');
}

async function disconnectLinkedIn() {
  if (!confirm('¿Desconectar tu cuenta de LinkedIn?')) return;
  try {
    await fetch('/auth/linkedin', { method: 'DELETE' });
    state.linkedInConnected = false;
    updateAuthUI({ connected: false });
    showToast('Cuenta de LinkedIn desconectada', 'info');
  } catch (e) {
    showToast('Error al desconectar', 'error');
  }
}

// ── Generación de post ─────────────────────────────────
async function generatePost() {
  const urlInput = document.getElementById('tweet-url');
  const url = urlInput.value.trim();

  if (!url) {
    showError('generate-error', 'Por favor ingresa un URL de X/Twitter válido.');
    urlInput.focus();
    return;
  }

  if (!/^https?:\/\/(www\.)?(twitter|x)\.com\/.+\/status\/\d+/.test(url)) {
    showError('generate-error', 'El URL debe ser un enlace directo a un tweet. Ejemplo: https://x.com/usuario/status/123456');
    return;
  }

  hideError('generate-error');
  showLoading('Extrayendo contenido del tweet...');

  const language = document.getElementById('post-language').value;

  try {
    // Actualizar mensaje mientras se espera
    setTimeout(() => setLoadingMessage('Generando post con Claude AI...'), 3000);

    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, language }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || 'Error al generar el post');
    }

    state.tweetData = data.tweet;
    state.generatedText = data.linkedin_text;
    state.suggestedImages = data.suggested_images || [];
    state.mediaType = data.media_type || 'auto';
    state.pdfUrl = data.tweet.pdf_url || null;
    state.documentTitle = data.tweet.paper_info?.title || 'Documento';

    renderTweetPreview(data.tweet);
    renderLinkedInPreview(data.linkedin_text);
    renderMediaBadge(data.media_type);
    renderImageSelector(data.media_type === 'image' ? data.suggested_images : []);

    // Mostrar secciones
    show('section-preview');
    show('section-publish');
    document.getElementById('section-preview').scrollIntoView({ behavior: 'smooth', block: 'start' });

  } catch (e) {
    showError('generate-error', e.message);
  } finally {
    hideLoading();
  }
}

function renderTweetPreview(tweet) {
  const authorEl = document.getElementById('tweet-author');
  const textEl   = document.getElementById('tweet-text');
  const imgsEl   = document.getElementById('tweet-images');
  const paperEl  = document.getElementById('tweet-paper');

  authorEl.textContent = tweet.author_name
    ? `${tweet.author_name}${tweet.author_handle ? ' · @' + tweet.author_handle : ''}`
    : 'Autor desconocido';

  textEl.textContent = tweet.text;

  // Imágenes
  imgsEl.innerHTML = '';
  (tweet.images || []).slice(0, 4).forEach((src, i) => {
    const img = document.createElement('img');
    img.src = src;
    img.className = 'tweet-img';
    img.alt = `Imagen ${i + 1} del tweet`;
    img.loading = 'lazy';
    imgsEl.appendChild(img);
  });

  // Info de paper
  if (tweet.paper_info) {
    const p = tweet.paper_info;
    paperEl.innerHTML = `
      <strong>📄 ${escHtml(p.title || 'Paper académico')}</strong>
      ${p.authors?.length ? '<span>' + escHtml(p.authors.slice(0,3).join(', ')) + '</span>' : ''}
      ${p.abstract ? '<span>' + escHtml(p.abstract.substring(0, 200)) + '...</span>' : ''}
    `;
    paperEl.classList.remove('hidden');
  } else {
    paperEl.classList.add('hidden');
  }
}

function renderMediaBadge(mediaType) {
  // Mostrar un badge indicando qué tipo de media se va a adjuntar
  let existingBadge = document.getElementById('media-badge');
  if (!existingBadge) {
    existingBadge = document.createElement('div');
    existingBadge.id = 'media-badge';
    existingBadge.style.cssText = 'margin:8px 0;padding:6px 12px;border-radius:6px;font-size:0.85rem;font-weight:500;display:inline-block;';
    const tweetTextEl = document.getElementById('tweet-text');
    if (tweetTextEl) tweetTextEl.parentElement.insertBefore(existingBadge, tweetTextEl.nextSibling);
  }
  const badges = {
    video:    { text: '📹 Video detectado — se subirá el video a LinkedIn', color: '#1d4ed8', bg: '#dbeafe' },
    document: { text: '📄 Paper/PDF detectado — se adjuntará el PDF', color: '#065f46', bg: '#d1fae5' },
    generate: { text: '🎨 Sin media — se generará imagen automáticamente con IA', color: '#7c3aed', bg: '#ede9fe' },
    image:    { text: '🖼️ Imagen(es) detectadas — se adjuntará la primera', color: '#92400e', bg: '#fef3c7' },
  };
  const b = badges[mediaType];
  if (b) {
    existingBadge.textContent = b.text;
    existingBadge.style.color = b.color;
    existingBadge.style.background = b.bg;
    existingBadge.classList.remove('hidden');
  } else {
    existingBadge.classList.add('hidden');
  }
}

function renderLinkedInPreview(text) {
  const textarea = document.getElementById('linkedin-text');
  textarea.value = text;
  // Disparar evento para actualizar contador
  textarea.dispatchEvent(new Event('input'));
}

function renderImageSelector(images) {
  const container = document.getElementById('image-selector');
  const optionsEl = document.getElementById('image-options');

  if (!images || images.length === 0) {
    container.classList.add('hidden');
    state.selectedImageIndex = 0;
    return;
  }

  optionsEl.innerHTML = '';
  state.selectedImageIndex = 1; // Por defecto, primera imagen

  // Opción "Sin imagen"
  const noneLabel = document.createElement('label');
  noneLabel.className = 'image-option';
  noneLabel.innerHTML = `
    <input type="radio" name="img-select" value="0" />
    <div class="image-option-none">Sin imagen</div>
  `;
  noneLabel.querySelector('input').addEventListener('change', () => {
    state.selectedImageIndex = 0;
  });
  optionsEl.appendChild(noneLabel);

  // Opciones de imagen
  images.slice(0, 4).forEach((src, i) => {
    const label = document.createElement('label');
    label.className = 'image-option';
    const checked = i === 0 ? 'checked' : '';
    label.innerHTML = `
      <input type="radio" name="img-select" value="${i + 1}" ${checked} />
      <img src="${escHtml(src)}" class="image-option-img" alt="Imagen ${i + 1}" loading="lazy" />
    `;
    label.querySelector('input').addEventListener('change', () => {
      state.selectedImageIndex = i + 1;
    });
    optionsEl.appendChild(label);
  });

  container.classList.remove('hidden');
}

// ── Publicar ahora ─────────────────────────────────────
async function publishNow() {
  if (!state.linkedInConnected) {
    connectLinkedIn();
    return;
  }

  if (!state.tweetData) {
    showToast('Primero genera un post', 'error');
    return;
  }

  const linkedinText = document.getElementById('linkedin-text').value.trim();
  if (!linkedinText) {
    showToast('El texto del post está vacío', 'error');
    return;
  }

  const imageUrls = getSelectedImages();

  showLoading('Publicando en LinkedIn...');
  hidePublishResult();

  try {
    const res = await fetch('/api/publish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tweet_url: state.tweetData.tweet_url,
        tweet_text: state.tweetData.text,
        tweet_author: state.tweetData.author_name || '',
        linkedin_text: linkedinText,
        image_urls: imageUrls,
        use_first_image: imageUrls.length > 0,
        media_type: state.mediaType,
        pdf_url: state.pdfUrl,
        document_title: state.documentTitle,
      }),
    });

    const data = await res.json();

    if (!res.ok) throw new Error(data.detail || 'Error al publicar');

    showPublishResult('¡Post publicado en LinkedIn exitosamente! 🎉', 'success');
    showToast('¡Publicado!', 'success');
    loadHistory();
    resetForm();

  } catch (e) {
    showPublishResult(`Error: ${e.message}`, 'error');
  } finally {
    hideLoading();
  }
}

// ── Programar post ─────────────────────────────────────
async function schedulePost() {
  if (!state.linkedInConnected) {
    connectLinkedIn();
    return;
  }

  if (!state.tweetData) {
    showToast('Primero genera un post', 'error');
    return;
  }

  const scheduledAt = document.getElementById('schedule-datetime').value;
  if (!scheduledAt) {
    showToast('Selecciona una fecha y hora', 'error');
    return;
  }

  const scheduledDate = new Date(scheduledAt);
  if (scheduledDate <= new Date()) {
    showToast('La fecha debe ser en el futuro', 'error');
    return;
  }

  const linkedinText = document.getElementById('linkedin-text').value.trim();
  if (!linkedinText) {
    showToast('El texto del post está vacío', 'error');
    return;
  }

  const imageUrls = getSelectedImages();

  showLoading('Programando publicación...');
  hidePublishResult();

  try {
    const res = await fetch('/api/schedule', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tweet_url: state.tweetData.tweet_url,
        tweet_text: state.tweetData.text,
        tweet_author: state.tweetData.author_name || '',
        linkedin_text: linkedinText,
        image_urls: imageUrls,
        use_first_image: imageUrls.length > 0,
        scheduled_at: scheduledDate.toISOString(),
        media_type: state.mediaType,
        pdf_url: state.pdfUrl,
        document_title: state.documentTitle,
      }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Error al programar');

    const dateStr = scheduledDate.toLocaleString('es-ES', {
      dateStyle: 'medium', timeStyle: 'short'
    });
    showPublishResult(`✅ Post programado para el ${dateStr}`, 'success');
    showToast('Post programado', 'success');
    loadHistory();
    resetForm();

  } catch (e) {
    showPublishResult(`Error: ${e.message}`, 'error');
  } finally {
    hideLoading();
  }
}

function getSelectedImages() {
  if (state.selectedImageIndex === 0 || !state.suggestedImages.length) return [];
  return [state.suggestedImages[state.selectedImageIndex - 1]].filter(Boolean);
}

// ── Historial ──────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch('/api/posts');
    const posts = await res.json();
    renderHistory(posts);
  } catch (e) {
    console.error('Error loading history:', e);
  }
}

function renderHistory(posts) {
  const el = document.getElementById('history-list');
  if (!posts || posts.length === 0) {
    el.innerHTML = '<div class="empty-state">Aún no hay publicaciones. ¡Genera tu primer post!</div>';
    return;
  }

  el.innerHTML = posts.map(post => {
    const date = post.published_at || post.scheduled_at || post.created_at;
    const dateStr = date ? new Date(date + 'Z').toLocaleString('es-ES', {
      dateStyle: 'short', timeStyle: 'short'
    }) : '—';

    const statusLabel = {
      published: 'Publicado',
      scheduled: 'Programado',
      failed: 'Error',
      cancelled: 'Cancelado',
      pending: 'Pendiente',
    }[post.status] || post.status;

    const cancelBtn = post.status === 'scheduled'
      ? `<button class="btn-cancel-small" onclick="cancelPost(${post.id})" title="Cancelar">Cancelar</button>`
      : '';

    return `
      <div class="history-item">
        <span class="history-status status-${escHtml(post.status)}">${escHtml(statusLabel)}</span>
        <div class="history-content">
          <div class="history-text">${escHtml(post.linkedin_text)}</div>
          <div class="history-meta">
            <span>${post.status === 'scheduled' ? '📅 Programado: ' : '📤 '}${escHtml(dateStr)}</span>
            ${post.tweet_author ? `<span>🐦 ${escHtml(post.tweet_author)}</span>` : ''}
            ${post.error_message ? `<span style="color:var(--error)">⚠ ${escHtml(post.error_message)}</span>` : ''}
          </div>
        </div>
        <div class="history-actions">${cancelBtn}</div>
      </div>
    `;
  }).join('');
}

async function cancelPost(postId) {
  if (!confirm('¿Cancelar esta publicación programada?')) return;
  try {
    const res = await fetch(`/api/posts/${postId}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    showToast('Post cancelado', 'info');
    loadHistory();
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

// ── Helpers UI ─────────────────────────────────────────
function show(id) {
  document.getElementById(id)?.classList.remove('hidden');
}

function hide(id) {
  document.getElementById(id)?.classList.add('hidden');
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; el.classList.remove('hidden'); }
}

function hideError(id) {
  document.getElementById(id)?.classList.add('hidden');
}

function showLoading(msg = 'Cargando...') {
  document.getElementById('loading-message').textContent = msg;
  document.getElementById('loading-overlay').classList.remove('hidden');
}

function setLoadingMessage(msg) {
  const el = document.getElementById('loading-message');
  if (el) el.textContent = msg;
}

function hideLoading() {
  document.getElementById('loading-overlay').classList.add('hidden');
}

function showPublishResult(msg, type) {
  const el = document.getElementById('publish-result');
  el.textContent = msg;
  el.className = `publish-result ${type}`;
  el.classList.remove('hidden');
}

function hidePublishResult() {
  document.getElementById('publish-result').classList.add('hidden');
}

function showToast(msg, type = 'info') {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className = `toast ${type}`;
  toast.classList.remove('hidden');
  setTimeout(() => toast.classList.add('hidden'), 4000);
}

function resetForm() {
  // Limpiar estado y ocultar secciones de preview/publish
  // (no limpiar el URL input para facilitar re-generación)
  state.tweetData = null;
  state.generatedText = '';
  state.suggestedImages = [];
  state.selectedImageIndex = 0;
  state.mediaType = 'auto';
  state.pdfUrl = null;
  state.documentTitle = 'Documento';
  const badge = document.getElementById('media-badge');
  if (badge) badge.classList.add('hidden');
  hide('section-preview');
  hide('section-publish');
  hidePublishResult();
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Permitir enviar con Enter en el input de URL
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('tweet-url');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') generatePost();
    });
  }
});

// ── Exportar CSV ────────────────────────────────────────
function exportCsv() {
  const fromDate = document.getElementById('export-from').value;
  const toDate   = document.getElementById('export-to').value;

  const params = new URLSearchParams();
  if (fromDate) params.append('from_date', fromDate);
  if (toDate)   params.append('to_date', toDate);

  const url = '/api/posts/export' + (params.toString() ? '?' + params.toString() : '');
  window.location.href = url;
}

// ── X Monitor ───────────────────────────────────────────
async function loadXMonitorStatus() {
  try {
    const res  = await fetch('/api/x-monitor/status');
    const data = await res.json();
    renderXMonitorStatus(data);
  } catch (e) {
    console.error('Error cargando estado de X Monitor:', e);
  }
}

function renderXMonitorStatus(data) {
  const el = document.getElementById('x-monitor-body');
  if (!el) return;

  if (!data.configured) {
    el.innerHTML = `
      <div class="x-status-badge inactive">⚪ No configurado</div>
      <div class="x-setup-box">
        <h4>Cómo activar la automatización</h4>
        <ol>
          <li>Ve a <strong>developer.twitter.com</strong> y crea una App (cuenta gratuita).</li>
          <li>En <em>Keys and tokens</em>, copia el <strong>Bearer Token</strong>.</li>
          <li>Obtén tu <strong>User ID numérico</strong> en
            <a href="https://tweeterid.com" target="_blank" rel="noopener" style="color:var(--accent)">tweeterid.com</a>
            (pon tu @username y te devuelve el ID).
          </li>
          <li>Edita el archivo <code>.env</code> y agrega:
            <br/><code>X_BEARER_TOKEN=tu_token_aquí</code>
            <br/><code>X_USER_ID=tu_id_numerico</code>
            <br/><code>X_MONITOR_START_DATE=2026-03-02T00:00:00</code> (hora Monterrey, opcional)
          </li>
          <li>Reinicia la app con <code>uvicorn app.main:app --reload</code>.</li>
        </ol>
      </div>
    `;
    return;
  }

  // Estado del badge
  let badgeHtml;
  if (data.waiting_for_start) {
    const startLocal = data.start_date
      ? data.start_date.replace('T', ' ') + ' (Monterrey)'
      : '—';
    badgeHtml = `<div class="x-status-badge inactive">🕐 Esperando inicio — arranca el ${escHtml(startLocal)}</div>`;
  } else if (!data.seeded) {
    badgeHtml = `<div class="x-status-badge inactive">⏳ Primera ejecución pendiente — se hará semilla al primer chequeo</div>`;
  } else {
    badgeHtml = `<div class="x-status-badge active">🟢 Activo — revisando cada ${escHtml(String(data.check_interval_minutes))} min</div>`;
  }

  const lastDate = data.last_processed_at
    ? new Date(data.last_processed_at + 'Z').toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })
    : '—';

  const recentHtml = (data.recent_likes || []).map(like => {
    const d = like.processed_at
      ? new Date(like.processed_at + 'Z').toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })
      : '—';
    const statusLabel = { processed: 'publicado', failed: 'error', processing: 'procesando' }[like.status] || like.status;
    return `
      <div class="x-like-item">
        <span class="x-like-status ${escHtml(like.status)}">${escHtml(statusLabel)}</span>
        <div class="x-like-info">
          <div class="x-like-author">@${escHtml(like.tweet_author || '—')}</div>
          <div class="x-like-url"><a href="${escHtml(like.tweet_url)}" target="_blank" rel="noopener">${escHtml(like.tweet_url)}</a></div>
          ${like.error_message ? `<div style="color:var(--error);font-size:11px">⚠ ${escHtml(like.error_message)}</div>` : ''}
        </div>
        <span class="x-like-date">${escHtml(d)}</span>
      </div>
    `;
  }).join('');

  const seedInfo = data.seeded
    ? `✅ Semilla hecha — ${escHtml(String(data.total_skipped))} likes anteriores omitidos`
    : `⏳ Semilla pendiente — se ejecutará en el primer chequeo`;

  el.innerHTML = `
    ${badgeHtml}

    <div style="font-size:12px;color:var(--text-muted);margin-bottom:14px;padding:8px 12px;background:var(--surface-2);border-radius:6px;border:1px solid var(--border)">
      ${seedInfo}
    </div>

    <div class="x-monitor-grid">
      <div class="x-stat">
        <div class="x-stat-label">Posts auto-calendarizados</div>
        <div class="x-stat-value">${escHtml(String(data.pending_auto_posts))}</div>
      </div>
      <div class="x-stat">
        <div class="x-stat-label">Likes nuevos procesados</div>
        <div class="x-stat-value">${escHtml(String(data.total_processed))}</div>
      </div>
      <div class="x-stat">
        <div class="x-stat-label">Último procesado</div>
        <div class="x-stat-value" style="font-size:12px">${escHtml(lastDate)}</div>
      </div>
      <div class="x-stat">
        <div class="x-stat-label">User ID</div>
        <div class="x-stat-value" style="font-size:12px">${escHtml(data.user_id)}</div>
      </div>
    </div>

    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
      <div style="color:var(--text-muted);font-size:13px">Últimos likes procesados</div>
      <button class="btn btn-ghost btn-sm" onclick="checkXNow()">⚡ Revisar ahora</button>
    </div>

    ${recentHtml
      ? `<div class="x-likes-list">${recentHtml}</div>`
      : `<div class="empty-state">${data.seeded ? 'Aún no hay likes nuevos desde el inicio.' : 'Esperando primera ejecución…'}</div>`
    }

    <p style="color:var(--text-faint);font-size:11px;margin-top:12px">
      ℹ Posts calendarizados a las <strong>5:00 AM hora Monterrey</strong>, máximo 1 auto-post por día.
      Las publicaciones manuales no cuentan para ese límite.
    </p>
  `;
}

async function checkXNow() {
  try {
    showToast('Revisando likes en X...', 'info');
    await fetch('/api/x-monitor/check-now', { method: 'POST' });
    showToast('Chequeo iniciado. Actualiza en unos segundos.', 'success');
    setTimeout(loadXMonitorStatus, 5000);
  } catch (e) {
    showToast('Error al iniciar chequeo', 'error');
  }
}
