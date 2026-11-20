import ts from 'typescript';
export default {
  resolve: { preserveSymlinks: true },
  optimizeDeps: { noDiscovery: true, include: [] },
  esbuild: false,
  plugins: [{
    name: 'typescript-without-subprocess',
    transform(code, id) {
      if (!/\.tsx?$/.test(id)) return;
      return { code: ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX } }).outputText, map: null };
    },
  }],
  test: { pool: 'threads', maxWorkers: 1, minWorkers: 1, env: { VITE_DATA_MODE: 'mock' } },
};
