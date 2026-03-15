/* ── STATE ─────────────────────────────────────────────── */
let currentStep = 1;
let selectedFile = null;
let activeTab = 'url';

/* ── DOM REFS ──────────────────────────────────────────── */
const stepEls = document.querySelectorAll('.step');
const step1 = document.getElementById('step-1');
const step2 = document.getElementById('step-2');
const step3 = document.getElementById('step-3');
const features = document.getElementById('features');

const jobUrlInput = document.getElementById('job-url');
const jobTextInput = document.getElementById('job-text');

const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('cv-file');
const fileSelected = document.getElementById('file-selected');
const fileNameEl = document.getElementById('file-name');
const generateBtn = document.getElementById('generate-btn');

const loadingState = document.getElementById('loading-state');
const successState = document.getElementById('success-state');
const errorState = document.getElementById('error-state');
const downloadBtn = document.getElementById('download-btn');
const successSubtitle = document.getElementById('success-subtitle');
const errorMessage = document.getElementById('error-message');

/* ── TABS ──────────────────────────────────────────────── */
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    activeTab = btn.dataset.tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-url').classList.toggle('hidden', activeTab !== 'url');
    document.getElementById('tab-text').classList.toggle('hidden', activeTab !== 'text');
  });
});

/* ── STEP NAVIGATION ───────────────────────────────────── */
document.getElementById('next-to-step2').addEventListener('click', () => {
  const url = jobUrlInput.value.trim();
  const text = jobTextInput.value.trim();
  if (!url && !text) {
    alert('Please enter a job URL or paste the job description text.');
    return;
  }
  goToStep(2);
});

document.getElementById('back-to-step1').addEventListener('click', () => goToStep(1));

function goToStep(n) {
  currentStep = n;

  // Update stepper
  stepEls.forEach((el, i) => {
    const s = i + 1;
    el.classList.remove('active', 'done');
    if (s < n) el.classList.add('done');
    else if (s === n) el.classList.add('active');
  });

  step1.classList.toggle('hidden', n !== 1);
  step2.classList.toggle('hidden', n !== 2);
  step3.classList.toggle('hidden', n !== 3);
  features.classList.toggle('hidden', n !== 1);

  if (n === 3) {
    loadingState.classList.remove('hidden');
    successState.classList.add('hidden');
    errorState.classList.add('hidden');
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ── FILE UPLOAD ───────────────────────────────────────── */
uploadZone.addEventListener('dragover', e => {
  e.preventDefault();
  uploadZone.classList.add('dragover');
});
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  const file = e.dataTransfer.files[0];
  if (file) setFile(file);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

document.getElementById('change-file').addEventListener('click', () => {
  selectedFile = null;
  fileSelected.classList.add('hidden');
  uploadZone.classList.remove('hidden');
  generateBtn.disabled = true;
  fileInput.value = '';
});

function setFile(file) {
  const allowed = ['.pdf', '.doc', '.docx'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!allowed.includes(ext)) {
    alert('Please upload a PDF or Word document (.pdf, .doc, .docx)');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    alert('File is too large. Maximum size is 10 MB.');
    return;
  }
  selectedFile = file;
  fileNameEl.textContent = file.name;
  fileSelected.classList.remove('hidden');
  uploadZone.classList.add('hidden');
  generateBtn.disabled = false;
}

/* ── GENERATE ──────────────────────────────────────────── */
generateBtn.addEventListener('click', async () => {
  if (!selectedFile) return;

  const url = jobUrlInput.value.trim();
  const text = jobTextInput.value.trim();

  goToStep(3);
  animateLoadingSteps();

  const formData = new FormData();
  formData.append('cv_file', selectedFile);
  formData.append('job_url', url);
  formData.append('job_text', text);

  try {
    const resp = await fetch('/api/generate', { method: 'POST', body: formData });
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || 'Generation failed');
    }

    // Mark step 3 done in stepper
    stepEls.forEach((el, i) => {
      el.classList.remove('active');
      if (i < 3) el.classList.add('done');
    });

    successSubtitle.textContent = `CV adapted for ${data.job_title} at ${data.company}`;
    downloadBtn.href = data.download_url;

    loadingState.classList.add('hidden');
    successState.classList.remove('hidden');

  } catch (err) {
    loadingState.classList.add('hidden');
    errorMessage.textContent = err.message;
    errorState.classList.remove('hidden');
  }
});

/* ── LOADING STEPS ANIMATION ───────────────────────────── */
function animateLoadingSteps() {
  const steps = [
    document.getElementById('ls-1'),
    document.getElementById('ls-2'),
    document.getElementById('ls-3'),
    document.getElementById('ls-4'),
  ];
  const delays = [0, 3000, 8000, 18000];

  steps.forEach(s => s.classList.remove('active', 'done'));
  steps[0].classList.add('active');

  delays.forEach((delay, i) => {
    if (i === 0) return;
    setTimeout(() => {
      if (loadingState.classList.contains('hidden')) return;
      steps[i - 1].classList.remove('active');
      steps[i - 1].classList.add('done');
      steps[i].classList.add('active');
    }, delay);
  });
}

/* ── RETRY / START OVER ────────────────────────────────── */
document.getElementById('try-again').addEventListener('click', () => goToStep(2));
document.getElementById('start-over').addEventListener('click', () => {
  selectedFile = null;
  fileInput.value = '';
  jobUrlInput.value = '';
  jobTextInput.value = '';
  fileSelected.classList.add('hidden');
  uploadZone.classList.remove('hidden');
  generateBtn.disabled = true;
  goToStep(1);
});
