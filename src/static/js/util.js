export const $ = id => document.getElementById(id);

export const esc = s => s.replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

const pad = n => String(n).padStart(2, '0');

export function fmtTime(s) {
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return h ? `${h}:${pad(m)}:${pad(x)}` : `${m}:${pad(x)}`;
}

export const fmtSize = b => b >= 1e9 ? (b / 1e9).toFixed(1) + ' ГБ' : Math.max(1, Math.round(b / 1e6)) + ' МБ';

export const fmtElapsed = ms => {
  const t = Math.floor(ms / 1000);
  return Math.floor(t / 60) + ':' + pad(t % 60);
};

export const fmtDT = iso => new Date(iso).toLocaleString('ru-RU',
  {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'});

/* GET without a body, POST with a JSON body. */
export const api = (url, body) => fetch(url, body === undefined ? {} : {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

export const getJson = async url => (await fetch(url)).json();

export function lsGet(key) {
  try { return localStorage.getItem(key) || ''; } catch { return ''; }
}

export function lsSet(key, value) {
  try { localStorage.setItem(key, value); } catch {}
}

/* Copies text and flashes "Скопировано" on `label` for a moment. */
export async function copyText(text, label) {
  await navigator.clipboard.writeText(text);
  const original = label.textContent;
  label.textContent = 'Скопировано';
  setTimeout(() => label.textContent = original, 1800);
}
