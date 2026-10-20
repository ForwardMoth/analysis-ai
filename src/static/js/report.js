/* Paged AI report: the markdown is split into pages by headings, with a sidebar of sections and a search over them. */
import {$, esc} from './util.js';
import {markdown} from './markdown.js';

const MIN_QUERY = 2;
const plain = text => text.replace(/[*`_]/g, '').trim();

// Pages start at every heading of `groupLevel` (a section) and `groupLevel + 1` (a subsection inside it).
function splitPages(src, groupLevel) {
  const pages = [];
  let group = null, page = null, fence = null;
  const open = (title, level) => { page = {group, title, level, lines: []}; pages.push(page); };
  for (const line of src.split('\n')) {
    const f = line.match(/^\s*(`{3,}|~{3,})/);
    if (fence) { if (f && line.trim().startsWith(fence)) fence = null; }
    else if (f) fence = f[1];
    else {
      const h = line.match(/^(#{1,6})\s+(.*)/);
      if (h && h[1].length === groupLevel) { group = plain(h[2]); open(group, 0); }
      else if (h && h[1].length === groupLevel + 1 && group) open(plain(h[2]), 1);
    }
    if (!page) open('Начало', 0);
    page.lines.push(line);
  }
  return pages.map(p => ({...p, text: p.lines.join('\n')}));
}

function buildPages(src) {
  let pages = splitPages(src, 2);
  if (pages.length <= 1) pages = splitPages(src, 1);
  // A section whose heading is directly followed by subsections has no body of its own.
  const hasBody = p => p.lines.slice(1).some(l => l.trim());
  const sizes = {};
  pages.forEach(p => { sizes[p.group] = (sizes[p.group] || 0) + 1; });
  return pages
    .filter(p => p.level === 1 || hasBody(p) || sizes[p.group] === 1)
    .map(p => ({...p, lower: p.text.toLowerCase(), intro: p.level === 0 && sizes[p.group] > 1}));
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
    let html = '', lastGroup = null;
    for (const i of visible) {
      const p = pages[i], flat = p.level === 0 && !p.intro;
      if (!flat && p.group !== lastGroup) {
        lastGroup = p.group;
        if (!p.intro) html += `<div class="rgroup">${esc(p.group)}</div>`;
      }
      if (flat) lastGroup = null;
      const label = p.intro ? p.group : p.title;
      const count = searching ? `<span class="rcount">${countMatches(p, q)}</span>` : '';
      html += `<button type="button" class="rlink${p.level === 1 ? ' sub' : ''}${i === current ? ' on' : ''}" data-i="${i}">${esc(label)}${count}</button>`;
    }
    $('rlist').innerHTML = html || '<div class="rempty">Ничего не найдено</div>';
    $('rlist').querySelector('.on')?.scrollIntoView({block: 'nearest'});
  }

  function renderPage(scroll) {
    const page = pages[current];
    $('amd').innerHTML = markdown(page.text);
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
  $('rq').value = '';
  $('rq').oninput = () => {
    const visible = matching();
    if (visible.length && !visible.includes(current)) current = visible[0];
    renderPage(false);
  };
  $('rside').classList.toggle('hidden', pages.length <= 1);
  go(0, false);
}
