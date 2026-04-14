const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const agentRunnerBaseUrl = import.meta.env.VITE_AGENT_RUNNER_BASE_URL ?? 'http://localhost:8100';

function extractErrorMessage(body: string, status: number): string {
  if (!body) {
    return `Request failed with ${status}`;
  }

  try {
    const parsed = JSON.parse(body) as { detail?: string | Array<{ msg?: string }> };
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
      return parsed.detail;
    }
    if (Array.isArray(parsed.detail) && parsed.detail.length) {
      return parsed.detail.map((item) => item.msg).filter(Boolean).join('; ');
    }
  } catch {
    // Fall back to the raw response body when the server did not return JSON.
  }

  return body;
}

async function readJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(extractErrorMessage(body, response.status));
  }
  return response.json() as Promise<T>;
}

export function getApiBaseUrl(): string {
  return apiBaseUrl;
}

export function getAgentRunnerBaseUrl(): string {
  return agentRunnerBaseUrl;
}

export async function getApiHealth(): Promise<any> {
  return readJson(`${apiBaseUrl}/api/v1/health`);
}

export async function getAgentRunnerHealth(): Promise<any> {
  return readJson(`${agentRunnerBaseUrl}/healthz`);
}

export async function listSkills(): Promise<any[]> {
  return readJson(`${apiBaseUrl}/api/v1/skills`);
}

export async function createSkill(payload: { title?: string; skill_text: string }): Promise<any> {
  return readJson(`${apiBaseUrl}/api/v1/skills`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listBacktests(): Promise<any[]> {
  return readJson(`${apiBaseUrl}/api/v1/backtests`);
}

export async function listBacktestTraces(runId: string): Promise<any[]> {
  return readJson(`${apiBaseUrl}/api/v1/backtests/${runId}/traces`);
}

export async function createBacktest(payload: { skill_id: string; start_time_ms: number; end_time_ms: number; initial_capital: number }): Promise<any> {
  return readJson(`${apiBaseUrl}/api/v1/backtests`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listLiveTasks(): Promise<any[]> {
  return readJson(`${apiBaseUrl}/api/v1/live-tasks`);
}

export async function createLiveTask(payload: { skill_id: string }): Promise<any> {
  return readJson(`${apiBaseUrl}/api/v1/live-tasks`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function triggerLiveTask(taskId: string): Promise<any> {
  return readJson(`${apiBaseUrl}/api/v1/live-tasks/${taskId}/trigger`, {
    method: 'POST',
  });
}

export async function listSignals(): Promise<any[]> {
  return readJson(`${apiBaseUrl}/api/v1/live-signals`);
}

export async function getMarketOverview(): Promise<any> {
  return readJson(`${apiBaseUrl}/api/v1/market-data/overview`);
}
