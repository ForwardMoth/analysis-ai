/* Upload dialog: choose a file, start the transcription job and follow its progress. */
import {state} from './state.js';
import {$, fmtTime, fmtSize, fmtElapsed} from './util.js';
import {openTranscript} from './transcript.js';

const dialog = $('dialog');
const radio = name => document.querySelector(`input[name=${name}]:checked`).value;

/* ---- choosing a file ---- */
function showPreview(file) {
  const isAudio = file.type.startsWith('audio'), url = URL.createObjectURL(file);
  const media = document.createElement(isAudio ? 'audio' : 'video');
  media.preload = 'metadata';
  media.muted = true;
  media.playsInline = true;
  media.src = url;
  media.onloadedmetadata = () => {
    if (isFinite(media.duration)) {
      state.duration = media.duration;
      $('fmeta').textContent = fmtSize(file.size) + ' · ' + fmtTime(state.duration);
      $('dur').textContent = fmtTime(state.duration);
      $('dur').classList.remove('hidden');
    }
    if (isAudio) return URL.revokeObjectURL(url);
    media.currentTime = Math.min(Math.max(1, state.duration * .05), Math.max(0, state.duration - .1) || 0); // grab a frame
  };
  media.onseeked = () => {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 400;
      canvas.height = Math.round(400 * (media.videoHeight || 9) / (media.videoWidth || 16));
      canvas.getContext('2d').drawImage(media, 0, 0, canvas.width, canvas.height);
      const img = new Image();
      img.alt = '';
      img.src = canvas.toDataURL('image/jpeg', .8);
      $('thumb').prepend(img);
      $('thumbIcon').style.display = 'none';
    } catch {}
    URL.revokeObjectURL(url);
  };
  media.onerror = () => URL.revokeObjectURL(url);
}

function setFile(file) {
  state.file = file;
  state.duration = 0;
  $('pick').classList.add('hidden');
  $('chosen').classList.remove('hidden');
  $('dtitle').textContent = 'Параметры расшифровки';
  $('fname').textContent = file.name;
  $('fmeta').textContent = fmtSize(file.size);
  $('dur').classList.add('hidden');
  $('thumb').querySelectorAll('img').forEach(img => img.remove());
  $('thumbIcon').style.display = '';
  showPreview(file);
}

$('choose').onclick = $('replace').onclick = () => $('file').click();
$('close').onclick = () => location.reload();
$('file').onchange = e => e.target.files[0] && setFile(e.target.files[0]);
['dragenter', 'dragover'].forEach(type => dialog.addEventListener(type, e => {
  e.preventDefault();
  if (!state.busy) dialog.classList.add('over');
}));
['dragleave', 'drop'].forEach(type => dialog.addEventListener(type, e => {
  e.preventDefault();
  dialog.classList.remove('over');
}));
dialog.addEventListener('drop', e => {
  if (!state.busy && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});
// a file dropped beside the dialog must not make the browser navigate to it
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => e.preventDefault());

/* ---- running the job ---- */
let startedAt = 0;

function setProgress(percent) {
  $('bar').style.width = percent + '%';
  $('pct').textContent = Math.round(percent) + '%';
}

$('go').onclick = () => {
  state.busy = true;
  startedAt = Date.now();
  ['settings', 'dfoot', 'replace'].forEach(id => $(id).classList.add('hidden'));
  $('prog').classList.remove('hidden');
  $('dtitle').textContent = 'Расшифровываю';
  $('st').textContent = 'Загружаю файл…';
  setProgress(0);

  const query = new URLSearchParams({
    name: state.file.name, language: radio('lang'), model: radio('model'),
    speakers: $('speakers').value, diarize: $('diarize').checked ? '1' : '0'});
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/jobs?' + query);
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    setProgress(e.loaded / e.total * 10); // the upload is the first 10% of the bar
    $('st').textContent = 'Загружаю файл…';
  };
  xhr.onload = () => {
    if (xhr.status !== 200) return fail(xhr.responseText);
    state.jobId = JSON.parse(xhr.responseText).id;
    poll();
  };
  xhr.onerror = () => fail('Не удалось передать файл серверу. Проверьте, что приложение запущено.');
  xhr.send(state.file);
};

const KNOWN_ERRORS = [
  [/HF_TOKEN is not set/, 'Для разделения по голосам нужен токен Hugging Face (переменная HF_TOKEN). Отключите «Разделять реплики» или задайте токен, см. README.'],
  [/Missing 'whisperx'|Missing 'ffmpeg'/, 'Не найден FFmpeg или WhisperX. Установка описана в README.'],
  [/moov atom|Invalid data/, 'Файл не открылся. Проверьте, что это видео или аудио.'],
];

function fail(message) {
  const status = $('st');
  status.className = 'state err';
  status.textContent = 'Не удалось расшифровать';
  if (message) $('log').textContent += message + '\n';
  $('logbox').classList.remove('hidden');
  $('logbox').open = true;
  $('rfoot').classList.remove('hidden');
  $('bar').style.background = 'var(--err)';
  const known = KNOWN_ERRORS.find(([pattern]) => pattern.test($('log').textContent));
  if (known) status.textContent = known[1];
}

function describeProgress(job) {
  const parts = [];
  if (job.detail) parts.push(job.detail);
  if (job.state === 'running') {
    parts.push('на этом шаге ' + fmtTime(job.phase_elapsed || 0));
    if (job.eta) parts.push('осталось примерно ' + fmtTime(job.eta));
    if ((job.idle || 0) > 120) parts.push(`вывода нет ${fmtTime(job.idle)} — это нормально для тяжёлых шагов, пока процессор занят`);
  }
  return parts.join(' · ');
}

function updateLog(text) {
  const log = $('log'), stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
  log.textContent = text;
  if (stick) log.scrollTop = 1e9;
  if (text) $('logbox').classList.remove('hidden');
}

async function poll() {
  let job;
  try { job = await (await fetch('/api/jobs/' + state.jobId)).json(); }
  catch { return fail('Связь с приложением потеряна.'); }

  $('st').textContent = (job.step && job.state === 'running' ? `Шаг ${job.step} из 3 · ` : '') + job.stage;
  setProgress(job.progress);
  $('pct').textContent = Math.round(job.progress) + '% · прошло ' + fmtElapsed(Date.now() - startedAt);
  $('det').textContent = describeProgress(job);
  $('det').classList.toggle('warn', (job.idle || 0) > 600);
  updateLog(job.log);

  if (job.state === 'error') return fail('');
  if (job.state === 'done') return openTranscript(state.jobId);
  setTimeout(poll, 1500);
}
