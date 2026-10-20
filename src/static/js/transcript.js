/* The open transcript: replies, speaker names, search, export, notes and the tab switch. */
import {state} from './state.js';
import {$, esc, fmtDT, api, getJson, copyText} from './util.js';

const PALETTE = ['var(--play)', 'var(--amber)', 'var(--teal)', 'var(--ink)'];
const speakerColor = index => PALETTE[Math.min(index, PALETTE.length - 1)];
const speakerOf = turn => state.names[turn.sp] || turn.sp;
const toSeconds = tc => tc.split(':').reduce((acc, v) => acc * 60 + +v, 0);

const openedListeners = [];
/* Other modules (the analysis tab) refresh themselves when a transcript is opened. */
export const onTranscriptOpened = listener => openedListeners.push(listener);

function parse(text) {
  return text.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean).map(block => {
    const m = block.match(/^\[(\d\d:\d\d:\d\d)\]\s+(.+?):\s([\s\S]*)$/);
    return m ? {tc: m[1], sp: m[2], text: m[3]} : {tc: '', sp: '', text: block};
  });
}

const fullText = () =>
  state.turns.map(t => t.sp ? `[${t.tc}] ${speakerOf(t)}: ${t.text}` : t.text).join('\n\n') + '\n';

function renderTurns() {
  const query = $('q').value.trim().toLowerCase();
  const speakers = [...new Set(state.turns.map(t => t.sp))];
  const labelled = speakers.some(s => s && s !== 'UNKNOWN');
  const highlight = query ? new RegExp('(' + query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi') : null;

  const rows = state.turns
    .filter(t => !query || (t.text + ' ' + speakerOf(t)).toLowerCase().includes(query))
    .map(t => {
      const body = highlight ? esc(t.text).replace(highlight, '<mark>$1</mark>') : esc(t.text);
      return `<li class="turn" data-tc="${t.tc || '0:00'}" style="--c:${speakerColor(speakers.indexOf(t.sp))}">` +
        `<div class="tc${t.tc ? ' pick' : ''}" title="Добавить заметку к этому месту">${t.tc}</div>` +
        `<div>${labelled ? `<div class="sp">${esc(speakerOf(t))}</div>` : ''}<p class="tx">${body}</p></div></li>`;
    }).join('');
  $('turns').innerHTML = rows || '<li class="empty">Ничего не нашлось. Попробуйте другое слово.</li>';
}

function renderSpeakerInputs(id, speakers) {
  $('who').classList.toggle('hidden', !speakers.length);
  if (!speakers.length) return;
  $('who').innerHTML = '<span class="who-title">Подпишите говорящих:</span>' + speakers.map((s, i) =>
    `<label style="--c:${speakerColor(i)}"><input data-s="${s}" placeholder="${s}" value="${esc(state.names[s] || '')}" aria-label="Имя для ${s}"></label>`).join('');
  let saveTimer;
  $('who').oninput = e => {
    state.names[e.target.dataset.s] = e.target.value.trim();
    renderTurns();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => api(`/api/transcripts/${id}/meta`, {speakers: state.names}), 500);
  };
}

export async function openTranscript(id) {
  state.jobId = id;
  const meta = state.meta = await getJson('/api/transcripts/' + id);
  state.turns = parse(meta.text);
  state.names = meta.speakers || {};

  $('intake').classList.add('hidden');
  $('result').classList.remove('hidden');
  $('rname').textContent = meta.name;
  $('rdate').textContent = 'Расшифровано ' + fmtDT(meta.created);
  const last = state.turns.length && state.turns[state.turns.length - 1].tc;
  $('rstat').textContent = `${state.turns.length} реплик` + (last ? ` · до ${last}` : '');
  renderSpeakerInputs(id, [...new Set(state.turns.map(t => t.sp).filter(s => s && s !== 'UNKNOWN'))]);
  $('dlTxt').href = `/api/jobs/${id}/transcript.txt?dl=1`;
  $('dlJson').href = `/api/jobs/${id}/raw_transcript.json?dl=1`;

  showTab(false);
  renderTurns();
  renderNotes();
  openedListeners.forEach(listener => listener());
  scrollTo({top: 0});
}

/* ---- tabs ---- */
function showTab(analysis) {
  $('tabTr').classList.toggle('hidden', analysis);
  $('tabAi').classList.toggle('hidden', !analysis);
  $('tabTrBtn').setAttribute('aria-selected', !analysis);
  $('tabAiBtn').setAttribute('aria-selected', analysis);
}
$('tabTrBtn').onclick = () => showTab(false);
$('tabAiBtn').onclick = () => showTab(true);

/* ---- tools: search, copy, download, rename ---- */
$('q').oninput = renderTurns;
$('copy').onclick = () => copyText(fullText(), $('copy').lastElementChild);
$('dlTxt').onclick = e => { // download with the speaker names the user entered
  if (!Object.values(state.names).some(Boolean)) return;
  e.preventDefault();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([fullText()], {type: 'text/plain'}));
  a.download = 'transcript.txt';
  a.click();
};
$('rename').onclick = async () => {
  const name = prompt('Название расшифровки', state.meta.name);
  if (!name || !name.trim()) return;
  state.meta = await (await api(`/api/transcripts/${state.jobId}/meta`, {name: name.trim()})).json();
  $('rname').textContent = state.meta.name;
};

/* ---- notes ---- */
function renderNotes() {
  $('notes').innerHTML = state.meta.notes.slice().reverse().map(n =>
    `<div class="note"><p>${esc(n.text)}</p><button class="x" data-del="${n.id}" aria-label="Удалить заметку" title="Удалить">×</button>` +
    `<small>${fmtDT(n.created)}${n.tc ? ` · <button class="chip" data-tc="${n.tc}">${n.tc}</button>` : ''}</small></div>`
  ).join('') || '<p class="muted">Заметок пока нет.</p>';
}

function scrollToTimecode(tc) {
  $('q').value = '';
  renderTurns();
  const want = toSeconds(tc), rows = [...document.querySelectorAll('.turn')];
  const hit = rows.find(r => toSeconds(r.dataset.tc) >= want) || rows[rows.length - 1];
  if (hit) hit.scrollIntoView({behavior: 'smooth', block: 'center'});
}

$('nadd').onclick = async () => {
  const text = $('ntext').value.trim();
  if (!text) return $('ntext').focus();
  const response = await api(`/api/transcripts/${state.jobId}/notes`, {text, tc: $('ntc').value});
  if (!response.ok) return;
  state.meta.notes.push(await response.json());
  $('ntext').value = '';
  $('ntc').value = '';
  renderNotes();
};

$('notes').onclick = async e => {
  const {del, tc} = e.target.dataset;
  if (del) {
    if (!confirm('Удалить заметку?')) return;
    await api(`/api/transcripts/${state.jobId}/notes/delete`, {id: del});
    state.meta.notes = state.meta.notes.filter(n => n.id !== del);
    renderNotes();
  }
  if (tc) scrollToTimecode(tc);
};

$('turns').onclick = e => {
  const stamp = e.target.closest('.tc.pick');
  if (!stamp) return;
  $('ntc').value = stamp.textContent;
  $('ntext').focus();
};
