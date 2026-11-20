import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
// Never invent A's module name or launch a Python service in demo mode.
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill();
  process.exitCode = code;
}
function run(command, args) {
  const child = spawn(command, args, { stdio: 'inherit', shell: false, windowsHide: true });
  children.push(child);
  child.on('error', (error) => { console.error(error.message); stop(1); });
  child.on('exit', (code) => stop(code ?? 0));
}
if (process.env.REVIEW_FASTAPI_APP) {
  run(process.env.REVIEW_PYTHON || 'python', ['-m', 'uvicorn', process.env.REVIEW_FASTAPI_APP, '--host', '127.0.0.1', '--port', '8765']);
}
run(process.execPath, [fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))]);
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
