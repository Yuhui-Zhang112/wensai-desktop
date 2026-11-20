// Equivalent React production bundle without starting esbuild subprocesses.
// Useful in Windows environments that restrict child_process.spawn.
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { rollup } from 'rollup';
import commonjs from '@rollup/plugin-commonjs';
import { nodeResolve } from '@rollup/plugin-node-resolve';
import ts from 'typescript';
const tsPlugin = {
  name: 'typescript-in-process',
  async transform(code, id) {
    if (!/\.[cm]?[jt]sx?$/.test(id) || id.includes('node_modules')) return null;
    const result = ts.transpileModule(code.replaceAll('import.meta.env.VITE_AGENT_PREVIEW', JSON.stringify(process.env.VITE_AGENT_PREVIEW || '')).replaceAll('import.meta.env.VITE_DATA_MODE', JSON.stringify(process.env.VITE_DATA_MODE || 'real')).replaceAll('import.meta.env.VITE_API_BASE_URL', JSON.stringify(process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8765')), {
      fileName: id, compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX, sourceMap: false },
    });
    return { code: result.outputText, map: null };
  },
};
const cssPlugin = { name: 'external-styles', resolveId(id) { if (id.endsWith('.css')) return { id, external: true }; } };
const environmentPlugin = { name: 'production-react', transform(code, id) { if (id.includes('node_modules')) return { code: code.replaceAll('process.env.NODE_ENV', '"production"'), map: null }; } };
export function plugins() { return [cssPlugin, tsPlugin, nodeResolve({ browser: true, extensions: ['.js', '.jsx', '.ts', '.tsx', '.json'] }), environmentPlugin, commonjs()]; }
export async function build() {
  const bundle = await rollup({ input: 'src/main.tsx', plugins: plugins(), onwarn(warning, defaultHandler) { if (warning.code !== 'MODULE_LEVEL_DIRECTIVE') defaultHandler(warning); } });
  await mkdir('dist', { recursive: true });
  const output = await bundle.generate({ format: 'es', inlineDynamicImports: true });
  for (const chunk of output.output) if (chunk.type === 'chunk') await writeFile('dist/app.js', chunk.code.replace(/import ['"][^'"]*\.css['"];?/g, ''));
  await writeFile('dist/styles.css', (await readFile('src/styles.css', 'utf8')) + '\n' + (await readFile('src/integration.css', 'utf8')));
  await writeFile('dist/index.html', (await readFile('index.html', 'utf8')).replace('<script type="module" src="/src/main.tsx"></script>', '<link rel="stylesheet" href="./styles.css"/><script type="module" src="./app.js"></script>'));
  // Standalone is ONLY the explicit in-memory visual demonstration, never real APIs.
  if (process.env.VITE_DATA_MODE === 'mock') {
    const cssText = await readFile('dist/styles.css', 'utf8');
    const jsText = await readFile('dist/app.js', 'utf8');
    const standalone = (await readFile('index.html', 'utf8'))
      .replace('</head>', () => `<style>${cssText}</style></head>`)
      .replace('<script type="module" src="/src/main.tsx"></script>', () => `<script type="module">${jsText.replaceAll('</script', '<\\/script')}</script>`);
    await writeFile('智能体界面演示.html', standalone);
  }
  await bundle.close(); console.log('Portable production build: dist/');
}
if (process.argv[1]?.endsWith('portable-build.mjs')) await build();
