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
  loadSettings();
  loadLinkedInScraperStatus();
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
  // Ya no se usa: el backend asigna automáticamente el próximo slot 5 AM / 4 PM CDMX
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
    showError('generate-error', 'Por favor ingresa un URL válido.');
    urlInput.focus();
    return;
  }

  if (!/^https?:\/\//i.test(url)) {
    showError('generate-error', 'El URL debe comenzar con http:// o https://');
    return;
  }

  hideError('generate-error');
  const isTweet = /^https?:\/\/(www\.)?(twitter|x)\.com\/.+\/status\/\d+/i.test(url);
  showLoading(isTweet ? 'Extrayendo contenido del tweet...' : 'Analizando contenido del enlace...');

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

  // Para imagen: usar la imagen seleccionada en el UI.
  // Para video: pasar también el thumbnail del tweet como fallback por si yt-dlp falla.
  const imageUrls = state.mediaType === 'image'
    ? getSelectedImages()
    : state.suggestedImages.slice(0, 1);

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

  const linkedinText = document.getElementById('linkedin-text').value.trim();
  if (!linkedinText) {
    showToast('El texto del post está vacío', 'error');
    return;
  }

  const imageUrls = state.mediaType === 'image'
    ? getSelectedImages()
    : state.suggestedImages.slice(0, 1);

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
        media_type: state.mediaType,
        pdf_url: state.pdfUrl,
        document_title: state.documentTitle,
      }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Error al programar');

    const slotDate = data.scheduled_at ? new Date(data.scheduled_at + 'Z') : null;
    const dateStr = slotDate ? slotDate.toLocaleString('es-MX', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Mexico_City'
    }) : '';
    showPublishResult(`✅ Post programado para el ${dateStr} CDMX`, 'success');
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

// Calendar state
const calState = {
  view: 'list',       // 'list' | 'calendar'
  year: new Date().getFullYear(),
  month: new Date().getMonth(), // 0-based
  posts: [],
  selectedDay: null,
};

async function loadHistory() {
  try {
    const res = await fetch('/api/posts');
    const posts = await res.json();
    calState.posts = posts || [];
    renderHistory(posts);
  } catch (e) {
    console.error('Error loading history:', e);
  }
}

function switchHistoryView(view) {
  calState.view = view;
  const isList = view === 'list';
  document.getElementById('history-list').classList.toggle('hidden', !isList);
  document.getElementById('history-calendar').classList.toggle('hidden', isList);
  document.getElementById('btn-view-list').classList.toggle('active', isList);
  document.getElementById('btn-view-cal').classList.toggle('active', !isList);
  if (!isList) renderCalendar();
}

function calNavigate(delta) {
  calState.month += delta;
  if (calState.month > 11) { calState.month = 0; calState.year++; }
  if (calState.month < 0)  { calState.month = 11; calState.year--; }
  calState.selectedDay = null;
  document.getElementById('cal-day-detail').classList.add('hidden');
  renderCalendar();
}

function renderCalendar() {
  const { year, month, posts } = calState;

  // Label del mes
  const label = new Date(year, month, 1).toLocaleDateString('es-MX', { month: 'long', year: 'numeric' });
  document.getElementById('cal-month-label').textContent =
    label.charAt(0).toUpperCase() + label.slice(1);

  // Agrupar posts por fecha local YYYY-MM-DD, guardar también el datetime
  const byDay = {};
  posts.forEach(p => {
    const raw = p.scheduled_at || p.published_at || p.created_at;
    if (!raw) return;
    const dt = new Date(raw + (raw.includes('Z') ? '' : 'Z'));
    const key = `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
    if (!byDay[key]) byDay[key] = [];
    byDay[key].push({ post: p, dt });
  });

  // Ordenar dentro de cada día por hora
  Object.values(byDay).forEach(arr => arr.sort((a, b) => a.dt - b.dt));

  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();

  let html = '';

  for (let i = 0; i < firstDay; i++) {
    html += '<div class="cal-cell cal-cell--empty"></div>';
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${year}-${String(month+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const dayEntries = byDay[key] || [];
    const isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === d;
    const isSelected = calState.selectedDay === key;

    const chips = dayEntries.map(({ post: p, dt }) => {
      const timeStr = dt.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', hour12: true });
      const snippet = (p.linkedin_text || '').replace(/\s+/g, ' ').trim().slice(0, 32);
      const statusClass = {
        published: 'cal-chip--published',
        scheduled: 'cal-chip--scheduled',
        failed:    'cal-chip--failed',
        cancelled: 'cal-chip--cancelled',
      }[p.status] || 'cal-chip--scheduled';
      return `<div class="cal-chip ${statusClass}" title="${escHtml((p.linkedin_text||'').slice(0,200))}">
        <span class="cal-chip-time">${escHtml(timeStr)}</span>
        <span class="cal-chip-text">${escHtml(snippet)}${snippet.length >= 32 ? '…' : ''}</span>
      </div>`;
    }).join('');

    html += `
      <div
        class="cal-cell${isToday ? ' cal-cell--today' : ''}${dayEntries.length ? ' cal-cell--has-posts' : ''}${isSelected ? ' cal-cell--selected' : ''}"
        onclick="${dayEntries.length ? `calSelectDay('${key}')` : ''}"
        data-key="${key}"
      >
        <div class="cal-cell-head">
          <span class="cal-day-num">${d}</span>
        </div>
        ${chips ? `<div class="cal-chips">${chips}</div>` : ''}
      </div>`;
  }

  document.getElementById('cal-grid').innerHTML = html;
}

function calSelectDay(key) {
  calState.selectedDay = key;
  // Re-render para marcar el selected
  renderCalendar();

  const dayPosts = calState.posts.filter(p => {
    const raw = p.scheduled_at || p.published_at || p.created_at;
    if (!raw) return false;
    const dt = new Date(raw + (raw.includes('Z') ? '' : 'Z'));
    const k = `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
    return k === key;
  });

  const detailEl = document.getElementById('cal-day-detail');
  if (!dayPosts.length) {
    detailEl.innerHTML = `<div class="cal-detail-empty">Sin publicaciones este día.</div>`;
  } else {
    const [y, m, d] = key.split('-');
    const dateLabel = new Date(+y, +m-1, +d).toLocaleDateString('es-MX', { weekday: 'long', day: 'numeric', month: 'long' });
    const statusLabel = { published: 'Publicado', scheduled: 'Programado', failed: 'Error', cancelled: 'Cancelado', pending: 'Pendiente' };
    detailEl.innerHTML = `
      <div class="cal-detail-header">${dateLabel.charAt(0).toUpperCase() + dateLabel.slice(1)}</div>
      ${dayPosts.map(p => {
        const mediaIcon = { image: '🖼', video: '🎬', document: '📄' }[p.media_type] || '';
        const hasImages = p.image_urls && p.image_urls.length > 0;
        const mediaBadge = (p.media_type && p.media_type !== 'auto' && p.media_type !== 'none')
          ? `<span class="media-badge">${mediaIcon} ${escHtml(p.media_type)}</span>`
          : (hasImages ? `<span class="media-badge">🖼 ${p.image_urls.length} img</span>` : '');
        const canGenImg = p.status === 'scheduled' || p.status === 'pending';
        const calGenImgBtn = canGenImg
          ? `<button class="btn-gen-image-small" onclick="generatePostImage(${p.id})">🎨 Imagen</button>`
          : '';
        const actions = p.status === 'scheduled'
          ? `<div class="cal-detail-actions">
               <button class="btn-edit-small" onclick="editPost(${p.id})">Editar</button>
               ${calGenImgBtn}
               <button class="btn-cancel-small" onclick="cancelPost(${p.id})">Cancelar</button>
             </div>`
          : (canGenImg
            ? `<div class="cal-detail-actions">
                 <button class="btn-edit-small" onclick="editPost(${p.id})">Editar</button>
                 ${calGenImgBtn}
               </div>`
            : `<div class="cal-detail-actions">
                 <button class="btn-edit-small" onclick="editPost(${p.id})">Ver</button>
               </div>`);
        const calImgThumb = p.generated_image_path
          ? `<div class="gen-image-thumb gen-image-thumb--cal"><img src="${escHtml(p.generated_image_path)}?v=${p.id}" alt="Imagen generada" loading="lazy"></div>`
          : '';
        return `
        <div class="cal-detail-item">
          <div class="cal-detail-item-top">
            <span class="history-status status-${escHtml(p.status)}">${escHtml(statusLabel[p.status] || p.status)}</span>
            <span class="cal-detail-text">${escHtml((p.linkedin_text || '').slice(0, 140))}${(p.linkedin_text || '').length > 140 ? '…' : ''}</span>
            ${mediaBadge}
            ${p.li_likes != null || p.li_comments != null
              ? `<span class="cal-detail-metrics">👍 ${p.li_likes ?? '—'} &nbsp; 💬 ${p.li_comments ?? '—'}</span>`
              : ''}
          </div>
          ${calImgThumb}
          ${actions}
        </div>`;
      }).join('')}
    `;
  }
  detailEl.classList.remove('hidden');
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

    const editBtn = `<button class="btn-edit-small" onclick="editPost(${post.id})" title="Editar post">Editar</button>`;
    const canGenerateImage = post.status === 'scheduled' || post.status === 'pending';
    const genImgBtn = canGenerateImage
      ? `<button class="btn-gen-image-small" onclick="generatePostImage(${post.id})" title="Generar imagen con Nano Banana">🎨 Imagen</button>`
      : '';
    const cancelBtn = post.status === 'scheduled'
      ? `${editBtn}${genImgBtn}<button class="btn-cancel-small" onclick="cancelPost(${post.id})" title="Cancelar">Cancelar</button>`
      : (canGenerateImage ? `${editBtn}${genImgBtn}` : '');

    // Métricas
    let metricsHtml = '';
    if (post.status === 'published') {
      const likes = post.li_likes != null ? post.li_likes : '—';
      const comments = post.li_comments != null ? post.li_comments : '—';
      const impressions = post.li_impressions != null ? post.li_impressions.toLocaleString('es-MX') : '—';
      const clicks = post.li_clicks != null ? post.li_clicks : null;
      const shares = post.li_shares != null ? post.li_shares : null;
      const updatedAt = post.metrics_updated_at
        ? new Date(post.metrics_updated_at + 'Z').toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })
        : null;
      const engRate = (post.li_impressions && post.li_likes != null)
        ? (((post.li_likes || 0) + (post.li_comments || 0) + (post.li_clicks || 0)) / post.li_impressions * 100).toFixed(2)
        : null;
      metricsHtml = `
        <div class="history-metrics">
          <span title="Likes">👍 ${likes}</span>
          <span title="Comentarios">💬 ${comments}</span>
          <span title="Impresiones">👁 ${impressions}</span>
          ${clicks != null ? `<span title="Clicks">🖱 ${clicks}</span>` : ''}
          ${shares != null ? `<span title="Compartidos">🔁 ${shares}</span>` : ''}
          ${engRate != null ? `<span title="Engagement" style="color:var(--success)">${engRate}%</span>` : ''}
          <button class="btn-refresh-metrics" onclick="refreshMetrics(${post.id})" title="Actualizar métricas">↺</button>
          <button class="btn-refresh-metrics" onclick="debugMetrics(${post.id})" title="Ver diagnóstico" style="opacity:0.5">🔍</button>
          ${updatedAt ? `<span class="metrics-date">actualizado ${updatedAt}</span>` : ''}
        </div>`;
    }

    // ISO string for datetime-local input (strip seconds)
    const scheduledIso = post.scheduled_at
      ? new Date(post.scheduled_at + 'Z').toISOString().slice(0, 16)
      : '';

    // Media badge
    const mediaIcon = { image: '🖼', video: '🎬', document: '📄', none: '', auto: '' }[post.media_type] || '';
    const hasImages = post.image_urls && post.image_urls.length > 0;
    const mediaLabel = post.media_type && post.media_type !== 'auto' && post.media_type !== 'none'
      ? `<span class="media-badge" title="Tipo media: ${escHtml(post.media_type)}">${mediaIcon} ${escHtml(post.media_type)}</span>`
      : (hasImages ? `<span class="media-badge">🖼 ${post.image_urls.length} img</span>` : '');

    const genImageThumb = post.generated_image_path
      ? `<div class="gen-image-thumb"><img src="${escHtml(post.generated_image_path)}?v=${post.id}" alt="Imagen generada" loading="lazy"></div>`
      : '';

    return `
      <div class="history-item" id="history-item-${post.id}">
        <span class="history-status status-${escHtml(post.status)}">${escHtml(statusLabel)}</span>
        <div class="history-content">
          <div class="history-text" id="post-text-${post.id}">${escHtml(post.linkedin_text)}</div>
          ${genImageThumb}
          <div class="history-meta">
            <span id="post-date-${post.id}">${post.status === 'scheduled' ? '📅 Programado: ' : '📤 '}${escHtml(dateStr)}</span>
            ${post.tweet_author ? `<span>🐦 ${escHtml(post.tweet_author)}</span>` : ''}
            ${mediaLabel}
            ${post.error_message ? `<span style="color:var(--error)">⚠ ${escHtml(post.error_message)}</span>` : ''}
          </div>
          ${metricsHtml}
        </div>
        <div class="history-actions">${cancelBtn}</div>
      </div>
    `;
  }).join('');
}

async function generatePostImage(postId) {
  try {
    showToast('Generando imagen con Nano Banana...', 'info');
    const res = await fetch(`/api/posts/${postId}/generate-image`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    showToast('¡Imagen generada y guardada!', 'success');
    await loadHistory();
    if (calState.view === 'calendar' && calState.selectedDay) {
      calSelectDay(calState.selectedDay);
    }
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
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

// ── Edit modal ──────────────────────────────────────────
let _editPostId = null;

function editPost(postId) {
  const post = calState.posts.find(p => p.id === postId);
  if (!post) return;
  _editPostId = postId;

  document.getElementById('edt-text').value = post.linkedin_text || '';

  const dtEl = document.getElementById('edt-dt');
  const dtLabel = document.getElementById('edt-dt-label');
  if (post.scheduled_at) {
    dtEl.value = new Date(post.scheduled_at + 'Z').toISOString().slice(0, 16);
    dtEl.style.display = '';
    dtLabel.style.display = '';
  } else {
    dtEl.style.display = 'none';
    dtLabel.style.display = 'none';
  }

  document.getElementById('edt-media-type').value = post.media_type || 'auto';
  document.getElementById('edt-use-first-img').checked = post.use_first_image !== false;
  document.getElementById('edt-pdf-url').value = post.pdf_url || '';
  document.getElementById('edt-doc-title').value = post.document_title || 'Documento';

  // Images grid
  const grid = document.getElementById('edt-images-grid');
  const imgs = post.image_urls || [];
  if (imgs.length > 0) {
    grid.innerHTML = imgs.map((url, i) => `
      <div class="edit-image-thumb">
        <img src="${escHtml(url)}" alt="imagen ${i + 1}" loading="lazy">
        <a href="${escHtml(url)}" target="_blank" class="edit-image-link" title="Ver original">↗</a>
      </div>`).join('');
    document.getElementById('edt-images-section').style.display = '';
  } else {
    grid.innerHTML = '<span style="color:var(--text-faint);font-size:12px">Sin imágenes</span>';
    document.getElementById('edt-images-section').style.display = '';
  }

  onEditMediaTypeChange();
  document.getElementById('modal-edit-post').classList.remove('hidden');
}

function onEditMediaTypeChange() {
  const mt = document.getElementById('edt-media-type').value;
  document.getElementById('edt-first-img-row').style.display = (mt === 'auto' || mt === 'image') ? '' : 'none';
  document.getElementById('edt-pdf-section').style.display = (mt === 'document') ? '' : 'none';
}

function closeEditModal() {
  _editPostId = null;
  document.getElementById('modal-edit-post').classList.add('hidden');
}

async function saveEditModal() {
  if (!_editPostId) return;
  const body = {
    linkedin_text: document.getElementById('edt-text').value,
    media_type: document.getElementById('edt-media-type').value,
    use_first_image: document.getElementById('edt-use-first-img').checked,
    pdf_url: document.getElementById('edt-pdf-url').value || null,
    document_title: document.getElementById('edt-doc-title').value,
  };
  const dtEl = document.getElementById('edt-dt');
  if (dtEl.style.display !== 'none' && dtEl.value) {
    body.scheduled_at = new Date(dtEl.value).toISOString();
  }
  try {
    const res = await fetch(`/api/posts/${_editPostId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    showToast('Post actualizado', 'success');
    closeEditModal();
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

// ── LinkedIn Scraper status ──────────────────────────────
let _liScraperConfigured = false;

async function loadLinkedInScraperStatus() {
  try {
    const res = await fetch('/api/linkedin-scraper/status');
    if (!res.ok) return;
    const data = await res.json();
    _liScraperConfigured = data.configured;

    const el = document.getElementById('li-scraper-status');
    if (!el) return;

    if (data.configured) {
      el.innerHTML = `
        <div class="li-scraper-badge li-scraper-badge--ok">
          🟢 Cookies de LinkedIn configuradas — las métricas se obtienen con Playwright
          ${data.has_jsessionid ? '' : '<span style="color:var(--warning)"> · Falta JSESSIONID (opcional pero recomendado)</span>'}
        </div>`;
    } else {
      el.innerHTML = `
        <div class="li-scraper-badge li-scraper-badge--warn">
          ⚠️ Cookies de LinkedIn no configuradas — las métricas no se pueden obtener
        </div>
        <div class="x-setup-box" style="margin-top:10px">
          <h4>Cómo activar las métricas (likes, comentarios, impresiones)</h4>
          <ol>
            <li>Abre <strong>linkedin.com</strong> en Chrome con tu cuenta iniciada.</li>
            <li>Presiona <strong>F12</strong> → pestaña <strong>Application</strong> → <strong>Cookies</strong> → <code>https://www.linkedin.com</code></li>
            <li>Copia el valor de la cookie <code>li_at</code></li>
            <li>Copia el valor de la cookie <code>JSESSIONID</code> (sin las comillas que lo rodean)</li>
            <li>Edita el archivo <code>.env</code> y agrega:<br/>
              <code>LINKEDIN_LI_AT=tu_valor_aquí</code><br/>
              <code>LINKEDIN_JSESSIONID=tu_valor_aquí</code>
            </li>
            <li>Reinicia la app con <code>uvicorn app.main:app --reload</code></li>
          </ol>
        </div>`;
    }
  } catch (e) {
    console.error('Error cargando estado del scraper LinkedIn:', e);
  }
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
          <li>Inicia sesión en <strong>x.com</strong> en tu navegador.</li>
          <li>Abre DevTools y ve a <strong>Application → Cookies → x.com</strong>.</li>
          <li>Copia las cookies <strong>auth_token</strong> y <strong>ct0</strong>.</li>
          <li>Edita el archivo <code>.env</code> y agrega:
            <br/><code>X_USERNAME=tu_handle_sin_arroba</code>
            <br/><code>X_AUTH_TOKEN=tu_cookie_auth_token</code>
            <br/><code>X_CT0=tu_cookie_ct0</code>
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
    const statusLabel = { processed: 'publicado', failed: 'error', processing: 'procesando', rejected: 'rechazado' }[like.status] || like.status;
    const isRejected = like.status === 'rejected';
    return `
      <div class="x-like-item${isRejected ? ' x-like-rejected' : ''}">
        <span class="x-like-status ${escHtml(like.status)}">${escHtml(statusLabel)}</span>
        <div class="x-like-info">
          <div class="x-like-author">@${escHtml(like.tweet_author || '—')}</div>
          <div class="x-like-url"><a href="${escHtml(like.tweet_url)}" target="_blank" rel="noopener">${escHtml(like.tweet_url)}</a></div>
          ${isRejected && like.error_message ? `<div class="x-like-reject-reason">No publicado: ${escHtml(like.error_message)}</div>` : ''}
          ${!isRejected && like.error_message ? `<div style="color:var(--error);font-size:11px">⚠ ${escHtml(like.error_message)}</div>` : ''}
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
        <div class="x-stat-label">No publicables</div>
        <div class="x-stat-value" style="${(data.total_rejected || 0) > 0 ? 'color:var(--warning)' : ''}">${escHtml(String(data.total_rejected || 0))}</div>
      </div>
      <div class="x-stat">
        <div class="x-stat-label">Último procesado</div>
        <div class="x-stat-value" style="font-size:12px">${escHtml(lastDate)}</div>
      </div>
    </div>

    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:10px">
      <div style="color:var(--text-muted);font-size:13px">Últimos likes procesados</div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-ghost btn-sm" onclick="checkXNow()">⚡ Revisar ahora</button>
        <button class="btn btn-ghost btn-sm" onclick="repackSchedule()" title="Compacta los posts programados a 5 AM y 4 PM sin huecos">📅 Repaquetar horario</button>
      </div>
    </div>

    ${recentHtml
      ? `<div class="x-likes-list">${recentHtml}</div>`
      : `<div class="empty-state">${data.seeded ? 'Aún no hay likes nuevos desde el inicio.' : 'Esperando primera ejecución…'}</div>`
    }

    <p style="color:var(--text-faint);font-size:11px;margin-top:12px">
      ℹ Posts calendarizados a las <strong>5:00 AM y 4:00 PM hora Monterrey</strong>, máximo 2 auto-posts por día.
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

async function repackSchedule() {
  if (!confirm('¿Reordenar todos los posts programados a los slots 5 AM y 4 PM consecutivos sin huecos?')) return;
  try {
    showToast('Reordenando programación...', 'info');
    const res = await fetch('/api/posts/repack-schedule', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Error');
    const msg = data.repacked === 0
      ? 'La programación ya está compacta, no hubo cambios.'
      : `✅ ${data.repacked} post(s) reordenado(s). Próximos slots:\n${data.slots.join('\n')}`;
    alert(msg);
    loadHistory();
    if (calState.view === 'calendar') renderCalendar();
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

// ── Configuración del prompt ────────────────────────────

let _defaultPrompt = '';

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const data = await res.json();
    _defaultPrompt = data.default_prompt;
    const ta = document.getElementById('settings-prompt');
    if (ta) ta.value = data.custom_prompt || data.default_prompt;
  } catch (e) {
    console.error('Error cargando settings:', e);
  }
}

async function savePrompt() {
  const ta = document.getElementById('settings-prompt');
  const resultEl = document.getElementById('settings-result');
  const prompt = ta.value.trim() || null;
  try {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ custom_prompt: prompt }),
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    resultEl.textContent = 'Prompt guardado correctamente.';
    resultEl.className = 'publish-result publish-result--success';
    show('settings-result');
    setTimeout(() => hide('settings-result'), 3000);
  } catch (e) {
    resultEl.textContent = `Error: ${e.message}`;
    resultEl.className = 'publish-result publish-result--error';
    show('settings-result');
  }
}

async function resetPrompt() {
  if (!confirm('¿Restablecer el prompt al texto original del sistema?')) return;
  try {
    await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ custom_prompt: null }),
    });
    const ta = document.getElementById('settings-prompt');
    if (ta) ta.value = _defaultPrompt;
    showToast('Prompt restablecido al default', 'success');
  } catch (e) {
    showToast('Error al restablecer prompt', 'error');
  }
}

// ── Tab navigation ──────────────────────────────────────

function switchTab(tab) {
  const isPublish = tab === 'publish';
  document.getElementById('page-publish').classList.toggle('hidden', !isPublish);
  document.getElementById('page-analytics').classList.toggle('hidden', isPublish);
  document.getElementById('tab-btn-publish').classList.toggle('active', isPublish);
  document.getElementById('tab-btn-analytics').classList.toggle('active', !isPublish);
  if (!isPublish) loadAnalytics();
}

// ── Analytics dashboard ─────────────────────────────────

const _charts = {};

function _destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

function _chartDefaults() {
  return {
    color: '#8892a4',
    borderColor: '#252538',
    plugins: { legend: { labels: { color: '#8892a4', boxWidth: 12, font: { size: 12 } } } },
    scales: {
      x: { ticks: { color: '#8892a4', font: { size: 11 } }, grid: { color: '#1c1c2e' } },
      y: { ticks: { color: '#8892a4', font: { size: 11 } }, grid: { color: '#1c1c2e' }, beginAtZero: true },
    },
  };
}

async function loadAnalytics() {
  try {
    const res = await fetch('/api/analytics');
    if (!res.ok) return;
    const data = await res.json();
    renderAnalytics(data);
  } catch (e) {
    console.error('Error cargando analytics:', e);
  }
}

function renderAnalytics(data) {
  // KPIs
  document.getElementById('kpi-published').textContent = data.total_published ?? 0;
  const withM = data.posts_with_metrics ?? 0;
  const subM = document.getElementById('kpi-with-metrics');
  if (subM) subM.textContent = withM > 0 ? `${withM} con métricas` : 'sin métricas aún';

  document.getElementById('kpi-impressions').textContent = (data.total_impressions ?? 0).toLocaleString('es-MX');
  const avgImp = document.getElementById('kpi-avg-impressions');
  if (avgImp) avgImp.textContent = data.avg_impressions ? `~${data.avg_impressions.toLocaleString('es-MX')} promedio` : '';

  document.getElementById('kpi-likes').textContent = data.total_likes ?? 0;
  const avgL = document.getElementById('kpi-avg-likes');
  if (avgL) avgL.textContent = data.avg_likes ? `${data.avg_likes} promedio` : '';

  document.getElementById('kpi-comments').textContent = data.total_comments ?? 0;
  document.getElementById('kpi-clicks').textContent = (data.total_clicks ?? 0).toLocaleString('es-MX');

  const engEl = document.getElementById('kpi-engagement');
  if (engEl) {
    const eng = data.engagement_rate ?? 0;
    engEl.textContent = eng > 0 ? `${eng}%` : '—';
    engEl.style.color = eng > 3 ? 'var(--success)' : eng > 1 ? 'var(--primary)' : '';
  }

  // Chart: posts por día
  _destroyChart('by-day');
  const dayCtx = document.getElementById('chart-by-day').getContext('2d');
  _charts['by-day'] = new Chart(dayCtx, {
    type: 'bar',
    data: {
      labels: (data.posts_by_day || []).map(d => {
        const dt = new Date(d.date + 'T00:00:00');
        return dt.toLocaleDateString('es-MX', { month: 'short', day: 'numeric' });
      }),
      datasets: [{
        label: 'Publicaciones',
        data: (data.posts_by_day || []).map(d => d.count),
        backgroundColor: 'rgba(99,102,241,0.7)',
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: {
      ..._chartDefaults(),
      plugins: { legend: { display: false } },
      responsive: true,
      maintainAspectRatio: true,
    },
  });

  // Chart: posts por hora
  _destroyChart('by-hour');
  const hourCtx = document.getElementById('chart-by-hour').getContext('2d');
  const hourCounts = (data.posts_by_hour || []).map(h => h.count);
  const maxHour = Math.max(...hourCounts, 1);
  _charts['by-hour'] = new Chart(hourCtx, {
    type: 'bar',
    data: {
      labels: Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}h`),
      datasets: [{
        label: 'Posts publicados',
        data: hourCounts,
        backgroundColor: hourCounts.map(v =>
          v === maxHour && v > 0 ? 'rgba(16,185,129,0.8)' : 'rgba(99,102,241,0.5)'
        ),
        borderRadius: 3,
        borderSkipped: false,
      }],
    },
    options: {
      ..._chartDefaults(),
      plugins: { legend: { display: false } },
      responsive: true,
      maintainAspectRatio: true,
    },
  });

  // Chart: status
  _destroyChart('status');
  const statusCtx = document.getElementById('chart-status').getContext('2d');
  const statusMap = data.status_breakdown || {};
  const statusLabels = { published: 'Publicados', scheduled: 'Programados', failed: 'Errores', cancelled: 'Cancelados', pending: 'Pendientes' };
  const statusColors = { published: '#10b981', scheduled: '#6366f1', failed: '#ef4444', cancelled: '#64748b', pending: '#f59e0b' };
  const statusKeys = Object.keys(statusMap);
  _charts['status'] = new Chart(statusCtx, {
    type: 'doughnut',
    data: {
      labels: statusKeys.map(k => statusLabels[k] || k),
      datasets: [{
        data: statusKeys.map(k => statusMap[k]),
        backgroundColor: statusKeys.map(k => statusColors[k] || '#8892a4'),
        borderColor: '#141420',
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { position: 'bottom', labels: { color: '#8892a4', boxWidth: 10, font: { size: 11 } } } },
    },
  });

  // Chart: media type
  _destroyChart('media');
  const mediaCtx = document.getElementById('chart-media').getContext('2d');
  const mediaMap = data.media_type_breakdown || {};
  const mediaLabels = { image: 'Imagen', video: 'Video', document: 'Documento', generate: 'IA generada', auto: 'Auto' };
  const mediaColors = ['#6366f1', '#0a66c2', '#10b981', '#f59e0b', '#8892a4'];
  const mediaKeys = Object.keys(mediaMap);
  _charts['media'] = new Chart(mediaCtx, {
    type: 'doughnut',
    data: {
      labels: mediaKeys.map(k => mediaLabels[k] || k),
      datasets: [{
        data: mediaKeys.map(k => mediaMap[k]),
        backgroundColor: mediaColors.slice(0, mediaKeys.length),
        borderColor: '#141420',
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { position: 'bottom', labels: { color: '#8892a4', boxWidth: 10, font: { size: 11 } } } },
    },
  });

  // Top posts
  const topEl = document.getElementById('top-posts-list');
  const topPosts = data.top_posts || [];
  if (!topPosts.length) {
    topEl.innerHTML = '<div class="empty-state">Actualiza las métricas de tus posts publicados para ver el ranking.</div>';
    return;
  }
  const maxTotal = Math.max(...topPosts.map(p => p.total), 1);
  topEl.innerHTML = topPosts.map((p, i) => `
    <div class="top-post-row">
      <span class="top-post-rank">#${i + 1}</span>
      <div class="top-post-body">
        <div class="top-post-text">${escHtml(p.text)}${p.text.length >= 120 ? '…' : ''}</div>
        <div class="top-post-bar-wrap">
          <div class="top-post-bar" style="width:${Math.round(p.total / maxTotal * 100)}%"></div>
        </div>
      </div>
      <div class="top-post-stats">
        <span title="Likes">👍 ${p.likes}</span>
        <span title="Comentarios">💬 ${p.comments}</span>
        ${p.impressions > 0 ? `<span title="Impresiones">👁 ${p.impressions.toLocaleString('es-MX')}</span>` : ''}
        ${p.clicks > 0 ? `<span title="Clicks">🖱 ${p.clicks}</span>` : ''}
        ${p.engagement_rate > 0 ? `<span title="Engagement" style="color:var(--success)">${p.engagement_rate}%</span>` : ''}
      </div>
    </div>
  `).join('');
}

// ── Métricas de LinkedIn ────────────────────────────────

async function refreshMetrics(postId) {
  try {
    showToast('Consultando métricas en LinkedIn...', 'info');
    const res = await fetch(`/api/posts/${postId}/refresh-metrics`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    const parts = [
      data.li_likes != null ? `👍 ${data.li_likes}` : '',
      data.li_comments != null ? `💬 ${data.li_comments}` : '',
      data.li_impressions != null ? `👁 ${data.li_impressions.toLocaleString('es-MX')}` : '',
      data.li_clicks != null ? `🖱 ${data.li_clicks}` : '',
      data.li_shares != null ? `🔁 ${data.li_shares}` : '',
    ].filter(Boolean);
    const summary = parts.join('  ') || '(sin datos — reconecta LinkedIn para habilitar r_member_social)';
    showToast(`Métricas: ${summary}`, data.li_likes != null ? 'success' : 'info');
    loadHistory();
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

async function refreshAllMetrics() {
  const btn = document.getElementById('btn-refresh-all');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Actualizando...'; }
  try {
    showToast('Actualizando métricas de todos los posts...', 'info');
    const res = await fetch('/api/posts/refresh-all-metrics', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    showToast(data.message || `✅ Actualizado: ${data.refreshed} posts`, 'success');
    loadHistory();
    loadAnalytics();
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↺ Actualizar todas las métricas'; }
  }
}

async function debugMetrics(postId) {
  try {
    showToast('Obteniendo diagnóstico...', 'info');
    const res = await fetch(`/api/linkedin-scraper/debug/${postId}`);
    const data = await res.json();
    if (!res.ok) { alert(JSON.stringify(data, null, 2)); return; }
    let msg = `Post DB #${data.db_post_id}\nLinkedIn ID: ${data.db_linkedin_post_id || '(vacío)'}\nURN: ${data.urn}\n\n`;
    for (const r of (data.responses || [])) {
      msg += `─── ${r.url.split('/').slice(-2).join('/')}\nHTTP ${r.status}\n${r.snippet}\n\n`;
    }
    alert(msg);
  } catch (e) {
    alert(`Error de diagnóstico: ${e.message}`);
  }
}
