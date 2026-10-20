/* Minimal Markdown to HTML for the analysis report: headings, lists, tables, fenced code, links. */
import {esc} from './util.js';

const inline = text => esc(text)
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
  .replace(/\*(.+?)\*/g, '<i>$1</i>')
  .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
  .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');

const codeBlock = (lang, lines) =>
  `<div class="code"><div class="chead"><span>${esc(lang || 'code')}</span><button type="button" class="ccopy">Копировать</button></div>` +
  `<pre><code>${esc(lines.join('\n'))}</code></pre></div>`;

const tableCells = row => row.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));

const isTableHeader = (line, next) => /^\s*\|.*\|\s*$/.test(line) && /^\s*\|[\s:|-]+\|\s*$/.test(next || '');

export function markdown(src) {
  const out = [], lines = src.split('\n');
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const listItem = (kind, text) => {
    if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
    out.push(`<li>${inline(text)}</li>`);
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;
    if (m = line.match(/^\s*(`{3,}|~{3,})\s*([\w+#.-]*)/)) {
      closeList();
      const fence = m[1], body = [];
      while (++i < lines.length && !lines[i].trim().startsWith(fence)) body.push(lines[i]);
      out.push(codeBlock(m[2], body));
    } else if (isTableHeader(line, lines[i + 1])) {
      closeList();
      let html = '<table><thead><tr>' + tableCells(line).map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>';
      i++;
      while (i + 1 < lines.length && /^\s*\|/.test(lines[i + 1])) {
        i++;
        html += '<tr>' + tableCells(lines[i]).map(c => `<td>${c}</td>`).join('') + '</tr>';
      }
      out.push(html + '</tbody></table>');
    } else if (m = line.match(/^(#{1,4})\s+(.*)/)) {
      closeList();
      out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`);
    } else if (m = line.match(/^\s*[-*]\s+(.*)/)) listItem('ul', m[1]);
    else if (m = line.match(/^\s*\d+[.)]\s+(.*)/)) listItem('ol', m[1]);
    else if (/^\s*---+\s*$/.test(line)) { closeList(); out.push('<hr>'); }
    else if (!line.trim()) closeList();
    else { closeList(); out.push(`<p>${inline(line)}</p>`); }
  }
  closeList();
  return out.join('\n');
}
