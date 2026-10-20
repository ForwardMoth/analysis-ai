/* AI analysis tab: provider and role pickers, run with progress, saved reports. */
import {state} from './state.js';
import {$, esc, fmtTime, fmtDT, api, getJson, lsGet, lsSet, copyText} from './util.js';
import {renderReport} from './report.js';
import {onTranscriptOpened} from './transcript.js';

const PROVIDER_NAMES = {claude: 'Claude', chatgpt: 'ChatGPT'};
const PROVIDERS = [['claude', 'Claude', 'Claude Code', 'bot'], ['chatgpt', 'ChatGPT', 'Codex', 'chat']];
const DEFAULT_ESTIMATE_SECONDS = 180;
const POLL_MS = 2000;

/* ---- provider and role pickers ---- */
fetch('/api/tools').then(r => r.json()).then(tools => {
  const preferred = tools.chatgpt || !tools.claude ? 'chatgpt' : 'claude';
  $('aprov').innerHTML = PROVIDERS.map(([value, name, cli, icon]) =>
    `<label class="pcard"><input type="radio" name="aprov" value="${value}"${value === preferred ? ' checked' : ''}${tools[value] ? '' : ' disabled'}>` +
    `<svg class="ico"><use href="#i-${icon}"/></svg><span><b>${name}</b><small>${tools[value] ? 'через ' + cli : cli + ' не найден'}</small></span></label>`
  ).join('');
  renderModels();
});
const MODELS = {
  claude: [['opus', 'Opus', 'Самая вдумчивая, но медленнее'], ['sonnet', 'Sonnet', 'Баланс скорости и качества'], ['haiku', 'Haiku', 'Быстро и дёшево, разбор проще']],
  chatgpt: [['gpt-5.6-sol', 'GPT-5.6 Sol', 'Модель Codex по умолчанию']],
};
const CUSTOM = '__custom__';
let modelChoice = '';
function renderModels() {
  const options = [['', 'По умолчанию', 'Как настроено в установленном CLI'], ...(MODELS[provider()] || []), [CUSTOM, 'Другая', 'Ввести название вручную']];
  $('mcards').innerHTML = options.map(([value, name, hint]) =>
    `<button type="button" class="mcard" role="radio" data-m="${esc(value)}" aria-checked="${value === modelChoice}"><b>${esc(name)}</b><small>${esc(hint)}</small></button>`).join('');
  $('amodel').classList.toggle('hidden', modelChoice !== CUSTOM);
}
$('mcards').onclick = e => {
  const card = e.target.closest('.mcard');
  if (!card) return;
  modelChoice = card.dataset.m;
  $('amodel').value = modelChoice === CUSTOM ? '' : modelChoice;
  renderModels();
  if (modelChoice === CUSTOM) $('amodel').focus();
};
$('aprov').onchange = () => { modelChoice = ''; $('amodel').value = ''; renderModels(); };
const provider = () => (document.querySelector('input[name=aprov]:checked') || {}).value || 'claude';

const KINDS = {
  technical: ['analyze-interview.md', 'Вопросы и ответы по технологиям, пробелы в знаниях, материалы для изучения.'],
  fit: ['analyze-fit.md', 'Поведенческие вопросы, опыт, мотивация, софт-скиллы; технические вопросы и задания тоже разбираются.'],
};
const kind = () => (document.querySelector('input[name=akind]:checked') || {}).value || 'technical';
function applyKind(value) {
  const radio = document.querySelector(`input[name=akind][value=${value}]`);
  if (!radio) return;
  radio.checked = true;
  $('aprompt').textContent = 'prompts/' + KINDS[value][0];
  $('akindhint').textContent = KINDS[value][1];
  lsSet('kind', value);
}
$('akind').onchange = () => applyKind(kind());
applyKind(lsGet('kind') || 'technical');

let roleList = [];
const AUTO_TEXT = 'Модель сама поймёт по записи, кого вы собеседовали, и назовёт роль в начале отчёта. Подходит, если роль заранее не известна.';
const ROLE_LABELS = {'Оценивай': 'На что смотрим', 'Практика': 'Практика'};
const roleField = (text, key) => ((text.match(new RegExp(`^${key}:\\s*(.+)$`, 'm')) || [])[1] || '').trim();

function renderRoleView(role) {
  const picked = roleList.find(r => r.id === role);
  if (!picked) {
    $('rview').innerHTML = `<h4><svg class="ico"><use href="#i-wand"/></svg>Определить по интервью</h4><p>${esc(AUTO_TEXT)}</p>`;
    return;
  }
  const rows = picked.text.split('\n').map(l => l.trim()).filter(Boolean).map(line => {
    const m = line.match(/^([^:]{2,24}):\s*(.+)$/);
    return m && m[1] !== 'Позиция' ? `<dt>${esc(ROLE_LABELS[m[1]] || m[1])}</dt><dd>${esc(m[2])}</dd>` : m ? '' : `<dd class="wide">${esc(line)}</dd>`;
  }).join('');
  $('rview').innerHTML = `<h4><svg class="ico"><use href="#i-user"/></svg>${esc(picked.title)}</h4><dl>${rows}</dl>` +
    `<p class="muted">Описание добавится к запросу как исходная роль. Файл: <code>prompts/roles/${esc(picked.id)}.md</code></p>`;
}
function pickRole(role) {
  $('arole').value = role;
  document.querySelectorAll('#rcards .ritem').forEach(item => item.setAttribute('aria-checked', item.dataset.r === role));
  renderRoleView(role);
  lsSet('role', role);
}
function renderRoles() {
  const q = $('rsearch').value.trim().toLowerCase();
  const item = (value, title, sub, icon, cls = '') =>
    `<button type="button" class="ritem ${cls}" role="radio" data-r="${esc(value)}" aria-checked="false"><svg class="ico"><use href="#i-${icon}"/></svg><span><b>${esc(title)}</b><small>${esc(sub)}</small></span></button>`;
  const shown = roleList.filter(r => !q || `${r.id} ${r.title} ${r.text}`.toLowerCase().includes(q));
  $('rcards').innerHTML = (q ? '' : item('', 'Определить по интервью', 'Роль не нужна, модель решит сама', 'wand', 'auto')) +
    shown.map(r => item(r.id, r.title, roleField(r.text, 'Стек'), 'user')).join('') +
    (q && !shown.length ? '<p class="muted rempty">Ничего не найдено. Свою роль можно добавить файлом в <code>prompts/roles/</code>.</p>' : '');
  pickRole($('arole').value);
}
fetch('/api/roles').then(r => r.json()).then(roles => {
  roleList = roles;
  const last = lsGet('role');
  $('arole').value = roles.some(r => r.id === last) ? last : '';
  renderRoles();
});
$('rsearch').oninput = renderRoles;
$('rcards').onclick = e => {
  const item = e.target.closest('.ritem');
  if (item) pickRole(item.dataset.r);
};

/* ---- saved reports ---- */
function renderHistory() {
  const analyses = state.meta.analyses;
  $('hist').classList.toggle('hidden', !analyses.length);
  $('abadge').textContent = analyses.length;
  $('abadge').classList.toggle('hidden', !analyses.length);
  $('ahist').innerHTML = analyses.slice().reverse().map(a =>
    `<button class="chip" data-a="${a.id}" data-p="${a.provider}">${fmtDT(a.created)} · ${PROVIDER_NAMES[a.provider]}` +
    `${a.model ? ' ' + esc(a.model) : ''}${a.kind === 'fit' ? ' · фит' : ''}${a.role ? ' · ' + esc(a.role) : ''}${(a.tasks || []).length ? ' · заданий: ' + a.tasks.length : ''}</button>`
  ).join('');
}

function showAnalysis(text, providerName) {
  $('aout').classList.remove('hidden');
  renderReport(text);
  $('amd').onclick = async e => {
    const button = e.target.closest('.ccopy');
    if (button) await copyText(button.closest('.code').querySelector('code').textContent, button);
  };
  $('aout').classList.remove('hidden');
  $('astat').textContent = '';
  $('adl').href = URL.createObjectURL(new Blob([text], {type: 'text/markdown'}));
  $('adl').download = `analysis-${state.meta.name}-${providerName}.md`;
  $('acopy').onclick = () => copyText(text, $('acopy').lastElementChild);
}

$('ahist').onclick = async e => {
  const id = e.target.dataset.a;
  if (!id) return;
  const analysis = await getJson(`/api/transcripts/${state.jobId}/analyses/${id}`);
  showAnalysis(analysis.text, e.target.dataset.p);
};

onTranscriptOpened(() => {
  renderHistory();
  $('astat').textContent = '';
  $('aout').classList.add('hidden');
});

/* ---- running an analysis ---- */
// The CLI gives no real progress: estimate from past runs (or 3 min) and ease toward 95%.
function estimatePercent(seconds) {
  const past = state.meta.analyses.map(a => a.seconds).filter(Boolean);
  const expected = past.length ? past.reduce((a, b) => a + b) / past.length : DEFAULT_ESTIMATE_SECONDS;
  return 95 * (1 - Math.exp(-seconds / expected * 1.5));
}

function setRunning(running) {
  $('arun').disabled = running;
  $('aprog').classList.toggle('hidden', !running);
}

function showError(message) {
  setRunning(false);
  $('apct').textContent = '';
  $('astat').className = 'err';
  $('astat').textContent = message;
}

$('arun').onclick = async () => {
  const providerName = provider(), transcriptId = state.jobId;
  $('aprog').firstChild.style.width = '0';
  $('apct').textContent = '';
  setRunning(true);
  $('aout').classList.add('hidden');
  $('astat').className = 'muted';
  $('astat').textContent = 'Отправляю…';

  const response = await api(`/api/transcripts/${transcriptId}/analyze`,
    {provider: providerName, model: $('amodel').value.trim(), role: $('arole').value, kind: kind()});
  if (!response.ok) return showError(await response.text());
  const {id} = await response.json();

  const tick = async () => {
    if (transcriptId !== state.jobId) return; // the user opened another transcript
    let run;
    try { run = await getJson(`/api/transcripts/${transcriptId}/analyses/${id}`); }
    catch { return showError('Связь с приложением потеряна.'); }

    if (run.state === 'running') {
      const percent = estimatePercent(run.elapsed);
      $('aprog').firstChild.style.width = percent + '%';
      $('apct').textContent = Math.round(percent) + '% (оценка) · прошло ' + fmtTime(run.elapsed);
      $('astat').textContent = (run.stage || 'Анализирую…') + ' Можно оставить вкладку открытой, результат сохранится.';
      return setTimeout(tick, POLL_MS);
    }
    $('aprog').firstChild.style.width = '100%';
    $('apct').textContent = '';
    setRunning(false);
    if (run.state === 'error') return showError('Ошибка: ' + run.error);
    state.meta = await getJson('/api/transcripts/' + transcriptId);
    renderHistory();
    showAnalysis(run.text, providerName);
  };
  tick();
};
