export function normalizeApiBase(value: string): string {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.username || url.password || url.search || url.hash) {
    throw new Error('本地版 API 必须使用无账号信息的 http://127.0.0.1、localhost 或 [::1] 地址。');
  }
  return url.toString().replace(/\/$/, '');
}
export const config = {
  agentPreview: import.meta.env.VITE_AGENT_PREVIEW === '1',
  mode: import.meta.env.VITE_DATA_MODE === 'mock' ? 'mock' as const : 'real' as const,
  apiBase: normalizeApiBase(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8765'),
};
