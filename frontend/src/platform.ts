import { MAX_FILE_BYTES, validateFile } from './domain';
export const isDesktop = () => '__TAURI_INTERNALS__' in window;
export async function pickMaterial(): Promise<File | null> {
  if (!isDesktop()) throw new Error('浏览器模式请使用文件选择控件。');
  const { open } = await import('@tauri-apps/plugin-dialog');
  const path = await open({ multiple: false, directory: false, filters: [{ name: '评审材料', extensions: ['docx', 'pdf', 'pptx', 'txt', 'md'] }] });
  if (!path || typeof path !== 'string') return null;
  // The dialog dynamically grants only the selected path to the fs plugin.
  const { readFile, stat } = await import('@tauri-apps/plugin-fs');
  const metadata = await stat(path);
  if (metadata.size === 0 || metadata.size > MAX_FILE_BYTES) throw new Error('文件为空或超过 30 MB，请选择有效材料。');
  const bytes = await readFile(path);
  const file = new File([bytes], path.split(/[\\/]/).pop() || 'material.txt');
  validateFile(file); return file;
}
export type SaveTarget = { kind: 'desktop'; path: string } | { kind: 'browser'; handle: { createWritable(): Promise<{ write(data: Uint8Array): Promise<void>; close(): Promise<void> }> } };
export async function chooseSaveTarget(name: string, sourceName: string): Promise<SaveTarget | null> {
  if (isDesktop()) {
    const { save } = await import('@tauri-apps/plugin-dialog');
    const path = await save({ defaultPath: name, title: '选择导出位置 · 不会修改原始文件' });
    if (path && path.split(/[\\/]/).pop()?.toLowerCase() === sourceName.toLowerCase()) throw new Error('为保护原始文件，请使用与原始材料不同的文件名。');
    return path ? { kind: 'desktop', path } : null;
  }
  const picker = (window as unknown as { showSaveFilePicker?: (options: object) => Promise<Extract<SaveTarget, { kind: 'browser' }>['handle'] & { name: string }> }).showSaveFilePicker;
  if (!picker) throw new Error('当前浏览器不支持选择保存路径，请使用 Edge/Chrome 或 Tauri 桌面版。');
  try {
    const handle = await picker.call(window, { suggestedName: name });
    if (handle.name.toLowerCase() === sourceName.toLowerCase()) throw new Error('为保护原始文件，请使用与原始材料不同的文件名。');
    return { kind: 'browser', handle };
  }
  catch (error) { if (error instanceof DOMException && error.name === 'AbortError') return null; throw error; }
}
export async function writeTarget(target: SaveTarget, bytes: Uint8Array) {
  if (target.kind === 'desktop') { const { writeFile } = await import('@tauri-apps/plugin-fs'); await writeFile(target.path, bytes); }
  else { const writable = await target.handle.createWritable(); await writable.write(bytes); await writable.close(); }
}
