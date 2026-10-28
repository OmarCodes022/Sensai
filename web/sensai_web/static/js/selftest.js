// Self test page: XSS payloads against the Markdown renderer plus the DOM-free suites. Shows pass/fail.
import { renderMarkdown } from './markdown.js';
import { PURE_TESTS } from './selftest-pure.js';
import { VIEW_TESTS } from './selftest-views.js';

const ALLOWED = new Set(['P', 'BR', 'STRONG', 'EM', 'CODE', 'PRE', 'FIGURE', 'DIV', 'SPAN', 'BUTTON', 'H3', 'H4', 'H5', 'UL', 'OL', 'LI', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD', 'A', 'HR', 'BLOCKQUOTE', 'SUP', 'SVG', 'PATH', 'RECT', 'CIRCLE']);
const BAD_TAGS = new Set(['SCRIPT', 'IFRAME', 'IMG', 'OBJECT', 'EMBED', 'STYLE', 'LINK', 'META', 'FORM', 'INPUT', 'VIDEO', 'AUDIO']);

const PAYLOADS = [
  ['script tag', '<script>window.__xss = 1</script>'],
  ['script tag in a sentence', 'Hello <script>alert(1)</script> world'],
  ['javascript: link', '[click](javascript:alert(1))'],
  ['javascript: link with control characters', '[click](java\tscript:alert(1))'],
  ['mixed-case javascript: link', '[click](JaVaScRiPt:alert(1))'],
  ['data: link', '[click](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)'],
  ['vbscript: link', '[x](vbscript:msgbox(1))'],
  ['data: image', '![x](data:image/svg+xml;base64,PHN2Zz48c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9zdmc+)'],
  ['onerror attribute', '<img src=x onerror=alert(1)>'],
  ['onerror in image alt', '![x" onerror="alert(1)](http://example.com/a.png)'],
  ['onclick in HTML', '<a href="#" onclick="alert(1)">x</a>'],
  ['svg payload', '<svg onload=alert(1)><script>alert(2)</script></svg>'],
  ['svg in code-like text', '<svg/onload=alert(1)>'],
  ['nested entities', '&lt;script&gt;alert(1)&lt;/script&gt; &amp;lt;script&amp;gt; &#60;script&#62;'],
  ['iframe srcdoc', '<iframe srcdoc="<script>alert(1)</script>"></iframe>'],
  ['style injection', '<style>body{display:none}</style>'],
  ['link title breakout', '[a](http://example.com "x" onmouseover="alert(1)")'],
  ['autolink breakout', 'http://example.com/"onmouseover="alert(1)'],
  ['bidi override in prose', 'Total: ‮gnirts desrever‬ and ⁦isolate⁩'],
  ['bidi override in link text', '[‮evil](https://example.com)'],
  ['unterminated fence streaming', '```js\n<script>alert(1)</script>'],
  ['table with html cells', '| a | b |\n|---|---|\n| <img src=x onerror=alert(1)> | <script>1</script> |'],
  ['blockquote with html', '> <script>alert(1)</script>'],
];

function audit(root) {
  const problems = [];
  for (const el of root.querySelectorAll('*')) {
    const tag = el.tagName.toUpperCase();
    if (BAD_TAGS.has(tag) || !ALLOWED.has(tag)) problems.push(`element <${tag.toLowerCase()}>`);
    for (const a of el.attributes) {
      if (/^on/i.test(a.name)) problems.push(`attribute ${a.name}`);
      if (a.name === 'style' && /url\(|expression|javascript/i.test(a.value)) problems.push('style attribute with url');
      if (['href', 'src', 'xlink:href', 'action'].includes(a.name) && !/^(https?:|mailto:|#)/i.test(a.value.trim())) problems.push(`${a.name}=${a.value}`);
    }
  }
  if (/[‪-‮⁦-⁩]/.test([...root.querySelectorAll('p, li, a, td, th, strong, em, h3, h4, h5')].map((e) => e.textContent).join(''))) problems.push('bidi control in prose');
  return problems;
}

const DOM_TESTS = [
  ...PAYLOADS.map(([name, src]) => [`xss: ${name}`, () => {
    const box = document.createElement('div');
    for (const streaming of [false, true]) {
      box.replaceChildren(renderMarkdown(src, { streaming }));
      const p = audit(box);
      if (p.length) throw new Error(`${streaming ? 'streaming: ' : ''}${[...new Set(p)].join(', ')}`);
    }
    if (window.__xss) throw new Error('script executed');
  }]),
  ['xss: raw HTML is shown as literal text', () => {
    const box = document.createElement('div');
    box.append(renderMarkdown('a <b>bold</b> b'));
    if (!box.textContent.includes('<b>bold</b>')) throw new Error(`text was ${box.textContent}`);
  }],
  ['xss: entities are not decoded', () => {
    const box = document.createElement('div');
    box.append(renderMarkdown('&lt;script&gt;'));
    if (!box.textContent.includes('&lt;script&gt;')) throw new Error(`text was ${box.textContent}`);
  }],
  ['xss: http links carry rel noopener and a confirm hook', () => {
    const box = document.createElement('div');
    box.append(renderMarkdown('[ok](https://example.com)'));
    const a = box.querySelector('a');
    if (!a || a.rel !== 'noopener noreferrer' || !a.dataset.url) throw new Error('link attributes missing');
  }],
  ['xss: images stay literal with a note', () => {
    const box = document.createElement('div');
    box.append(renderMarkdown('![cat](http://example.com/cat.png)'));
    if (box.querySelector('img') || !box.textContent.includes('![cat]')) throw new Error('image was rendered');
  }],
  ['markdown: unfinished fence closes virtually while streaming', () => {
    const box = document.createElement('div');
    box.append(renderMarkdown('```python\nprint(1)', { streaming: true }));
    if (!box.querySelector('pre')) throw new Error('no code block');
  }],
];

async function main() {
  const rows = document.getElementById('rows');
  let pass = 0, fail = 0;
  for (const [name, fn] of [...PURE_TESTS, ...VIEW_TESTS, ...DOM_TESTS]) {
    let err = null;
    try { await fn(); } catch (e) { err = e; }
    err ? fail++ : pass++;
    const tr = document.createElement('tr');
    tr.className = err ? 'fail' : 'pass';
    for (const text of [err ? 'FAIL' : 'PASS', name, err ? err.message : '']) { const td = document.createElement('td'); td.textContent = text; tr.append(td); }
    rows.append(tr);
  }
  const s = document.getElementById('summary');
  s.textContent = `${pass} passed, ${fail} failed, ${pass + fail} total`;
  s.dataset.fail = String(fail);
  document.title = `${fail ? 'FAIL' : 'PASS'} - Sensai self test`;
}
main();
