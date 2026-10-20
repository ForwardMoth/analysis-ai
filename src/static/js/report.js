/* Paged AI report: the markdown is split into pages by headings, with a sidebar of sections and a search over them. */
import {$, esc} from './util.js';
import {markdown} from './markdown.js';

const MIN_QUERY = 2;
const NUMBERED = /^(вопрос|задач[аи]|question|task)\s*№?\s*\d+/i;
const plain = text => text.replace(/[*`_]/g, '').trim();

// Pages start at every heading of level 1-3. A heading with no text of its own becomes a group label in the nav.
const MAX_LEVEL = 3;

function buildPages(src) {
  const pages = [], stack = [];
  let page = null, fence = null;
  const open = (title, level, chain) => { page = {title, level, chain, lines: []}; pages.push(page); };
  for (const line of src.split('\n')) {
    const f = line.match(/^\s*(`{3,}|~{3,})/);
    if (fence) { if (f && line.trim().startsWith(fence)) fence = null; }
    else if (f) fence = f[1];
    else {
      const h = line.match(/^(#{1,6})\s+(.*)/);
      if (h && h[1].length <= MAX_LEVEL) {
        const level = h[1].length, title = plain(h[2]);
        while (stack.length && stack[stack.length - 1].level >= level) stack.pop();
        open(title, level, stack.slice());
        stack.push(page);
      }
    }
    if (!page) open('Начало', 1, []);
    page.lines.push(line);
  }
  const hasBody = p => p.lines.slice(1).some(l => l.trim());
  for (const p of pages) {
    p.text = p.lines.join('\n');
    p.body = hasBody(p);
  }
  // Headings without a body are only labels, unless nothing else exists.
  const real = pages.filter(p => p.body);
  const list = real.length ? real : pages;
  const minLevel = Math.min(...list.map(p => p.level));
  return list.map(p => ({
    ...p, depth: p.level - minLevel,
    labels: p.chain.filter(c => !c.body),
    lower: p.text.toLowerCase(),
  }));
}

function highlight(root, query) {
  if (query.length < MIN_QUERY) return null;
  const needle = query.toLowerCase();
  const nodes = [], walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) if (walker.currentNode.nodeValue.toLowerCase().includes(needle)) nodes.push(walker.currentNode);
  let first = null;
  for (const node of nodes) {
    const text = node.nodeValue, lower = text.toLowerCase(), fragment = document.createDocumentFragment();
    let at = 0, i;
    while ((i = lower.indexOf(needle, at)) !== -1) {
      fragment.append(text.slice(at, i));
      const mark = document.createElement('mark');
      mark.textContent = text.slice(i, i + needle.length);
      fragment.append(mark);
      first = first || mark;
      at = i + needle.length;
    }
    fragment.append(text.slice(at));
    node.replaceWith(fragment);
  }
  return first;
}

const PRIORITY_HEAD = /приоритет|priority/i;
const LEVELS = [[/критич|critical|blocker/i, 'crit'], [/существен|высок|high|major/i, 'high'], [/средн|medium|важн/i, 'mid'], [/низк|минор|low|minor/i, 'low']];

// "1 — критичный" becomes a number plus a coloured level pill; the row gets an accent edge.
function markPriority(td) {
  const m = td?.textContent.trim().match(/^(\d+)?\s*[—–-]?\s*(.+)$/);
  if (!m) return;
  const level = (LEVELS.find(([re]) => re.test(m[2])) || [, 'mid'])[1];
  td.className = 'prio ' + level;
  td.innerHTML = '<div class="pw">' + (m[1] ? `<span class="pn">${m[1]}</span>` : '') + `<span class="pill">${esc(m[2])}</span></div>`;
  td.parentElement.classList.add('p-' + level);
}

// Wrap tables for scrolling and label each cell with its column so narrow screens can stack rows.
function tidyTables(root) {
  for (const table of root.querySelectorAll('table')) {
    const heads = [...table.querySelectorAll('th')].map(th => th.textContent.trim());
    table.querySelectorAll('tbody tr').forEach(tr => [...tr.children].forEach((td, i) => { if (heads[i]) td.dataset.label = heads[i]; }));
    const col = heads.findIndex(h => PRIORITY_HEAD.test(h));
    if (col >= 0) table.querySelectorAll('tbody tr').forEach(tr => markPriority(tr.children[col]));
    const wrap = document.createElement('div');
    wrap.className = 'twrap';
    table.replaceWith(wrap);
    wrap.append(table);
  }
}

const countMatches = (page, needle) => page.lower.split(needle).length - 1;

export function renderReport(src) {
  const pages = buildPages(src);
  let current = 0;
  const query = () => $('rq').value.trim().toLowerCase();
  const matching = () => {
    const q = query();
    return q.length < MIN_QUERY ? pages.map((p, i) => i) : pages.map((p, i) => i).filter(i => pages[i].lower.includes(q));
  };

  function renderNav() {
    const q = query(), visible = matching(), searching = q.length >= MIN_QUERY;
    let html = '', shown = new Set();
    for (const i of visible) {
      const p = pages[i];
      for (const l of p.labels) {
        if (shown.has(l)) continue;
        shown.add(l);
        html += `<div class="rgroup d${Math.min(l.level - 1, 2)}">${esc(l.title)}</div>`;
      }
      const count = searching ? `<span class="rcount">${countMatches(p, q)}</span>` : '';
      html += `<button type="button" class="rlink d${Math.min(p.level - 1, 2)}${i === current ? ' on' : ''}" data-i="${i}">${esc(p.title)}${count}</button>`;
    }
    $('rlist').innerHTML = html || '<div class="rempty">Ничего не найдено</div>';
    $('rlist').querySelector('.on')?.scrollIntoView({block: 'nearest'});
  }

  function renderPage(scroll) {
    const page = pages[current];
    $('amd').innerHTML = markdown(page.text);
    tidyTables($('amd'));
    $('rcur').textContent = page.title;
    $('rside').classList.remove('open');
    $('rtoggle').setAttribute('aria-expanded', 'false');
    const mark = highlight($('amd'), query());
    const order = matching(), at = order.indexOf(current);
    const prev = order[at - 1], next = order[at + 1];
    $('rpager').innerHTML =
      (prev !== undefined ? `<button type="button" class="btn" data-i="${prev}">← ${esc(pages[prev].title)}</button>` : '<span></span>') +
      (next !== undefined ? `<button type="button" class="btn" data-i="${next}">${esc(pages[next].title)} →</button>` : '<span></span>');
    renderNav();
    if (mark) mark.scrollIntoView({block: 'center'});
    else if (scroll) $('rtop').scrollIntoView({block: 'start'});
  }

  const go = (i, scroll = true) => { current = i; renderPage(scroll); };

  $('rpager').onclick = $('rlist').onclick = e => {
    const button = e.target.closest('[data-i]');
    if (button) go(+button.dataset.i);
  };
  $('rtoggle').onclick = () => {
    const open = $('rside').classList.toggle('open');
    $('rtoggle').setAttribute('aria-expanded', open);
  };
  $('rq').value = '';
  $('rq').oninput = () => {
    const visible = matching();
    if (visible.length && !visible.includes(current)) current = visible[0];
    renderPage(false);
  };
  $('rside').classList.toggle('hidden', pages.length <= 1);
  go(0, false);
}
