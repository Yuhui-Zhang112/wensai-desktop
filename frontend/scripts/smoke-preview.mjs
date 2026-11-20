import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import assert from 'node:assert/strict';
const html = await readFile('演示预览.html', 'utf8');
const script = html.match(/<script type="module">([\s\S]*)<\/script>/)?.[1];
assert.ok(script, 'Standalone bundle must exist');
assert.ok(!/import\s+["']\.\/styles\.css/.test(script), 'Styles must be embedded');
const dom = new JSDOM(html, { url: 'http://localhost/', runScripts: 'outside-only', pretendToBeVisual: true });
try {
  dom.window.structuredClone = structuredClone;
  dom.window.eval(script);
  await new Promise(resolve => setTimeout(resolve, 1800));
  assert.ok(dom.window.document.querySelector('#root').textContent.includes('结论范围超出已有证据'), 'Production React bundle must load seeded review results: ' + dom.window.document.querySelector('#root').textContent);
  assert.ok(dom.window.document.querySelector('#block-b4'), 'Production preview must include locatable paragraphs');
  console.log('Standalone production bundle smoke check passed (DOM, not browser visual QA).');
} finally { dom.window.close(); }
