/* List of earlier transcripts on the start page, with full-text search. */
import {$, esc, fmtDT, getJson} from './util.js';
import {openTranscript} from './transcript.js';

async function loadLibrary() {
  const query = $('lq').value.trim();
  let list = [];
  try { list = await getJson('/api/library?q=' + encodeURIComponent(query)); } catch {}
  $('lib').classList.toggle('hidden', !list.length && !query);
  $('items').innerHTML = list.map(i =>
    `<li class="item" data-id="${i.id}" tabindex="0" role="button"><div><b>${esc(i.name)}</b>${i.snippet ? `<small>…${esc(i.snippet)}…</small>` : ''}</div>` +
    `<div class="meta">${fmtDT(i.created)}<br>${i.length ? 'до ' + i.length + ' · ' : ''}${i.notes ? i.notes + ' зам. · ' : ''}${i.analyses ? i.analyses + ' анализ.' : ''}</div></li>`
  ).join('') || '<li class="empty">Ничего не нашлось.</li>';
}

$('items').onclick = e => {
  const item = e.target.closest('.item');
  if (item) openTranscript(item.dataset.id);
};
$('items').onkeydown = e => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const item = e.target.closest('.item');
  if (!item) return;
  e.preventDefault();
  openTranscript(item.dataset.id);
};

let searchTimer;
$('lq').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadLibrary, 250); };
loadLibrary();
