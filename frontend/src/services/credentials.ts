import { config } from '../config';

export interface CredentialStatus {
  provider: string;
  configured: boolean;
  storage?: string;
}

async function call<T>(method: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBase}/api/v1/desktop/settings/credential`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error('无法连接本地服务，请确认服务已启动。');
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error?.message || `保存失败（${response.status}）。`);
  }
  return response.json() as Promise<T>;
}

export const credentialStatus = () => call<CredentialStatus>('GET');
export const saveCredential = (apiKey: string) => call<CredentialStatus>('PUT', { apiKey });
export const clearCredential = () => call<CredentialStatus>('DELETE');
