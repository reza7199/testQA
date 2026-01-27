const API_BASE = (import.meta as any).env.VITE_API_BASE || 'http://localhost:8000'

export type RunCreate = {
  repo_url: string
  branch: string
  app_dir: string
  ui_dir: string
  suite: 'smoke' | 'regression' | 'both'
  create_github_issues: boolean
  commit_results: boolean
}

export async function createRun(payload: RunCreate) {
  const res = await fetch(`${API_BASE}/api/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function listRuns() {
  const res = await fetch(`${API_BASE}/api/runs`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getRun(runId: string) {
  const res = await fetch(`${API_BASE}/api/runs/${runId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getBugs(runId: string) {
  const res = await fetch(`${API_BASE}/api/runs/${runId}/bugs`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getIssues(runId: string) {
  const res = await fetch(`${API_BASE}/api/runs/${runId}/issues`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function bugsCsvUrl(runId: string) {
  return `${API_BASE}/api/runs/${runId}/bugs.csv`
}

export function eventsUrl(runId: string) {
  return `${API_BASE}/api/runs/${runId}/events`
}

// Worker management
export type WorkerStatus = {
  running: boolean
  mode: string
  pid?: number
  uptime_seconds?: number
  log_tail: string[]
}

export type WorkerStartRequest = {
  mode: 'local' | 'docker'
  api_key?: string
}

export async function getWorkerStatus(): Promise<WorkerStatus> {
  const res = await fetch(`${API_BASE}/api/worker/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function startWorker(req: WorkerStartRequest) {
  const res = await fetch(`${API_BASE}/api/worker/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function stopWorker() {
  const res = await fetch(`${API_BASE}/api/worker/stop`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getWorkerLogs(lines: number = 100) {
  const res = await fetch(`${API_BASE}/api/worker/logs?lines=${lines}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// Settings
export type Settings = {
  worker_mode: string
  anthropic_api_key?: string
  github_token?: string
}

export type SettingsUpdate = {
  worker_mode?: string
  anthropic_api_key?: string
  github_token?: string
}

export async function getSettings(): Promise<Settings> {
  const res = await fetch(`${API_BASE}/api/settings`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateSettings(updates: SettingsUpdate): Promise<Settings> {
  const res = await fetch(`${API_BASE}/api/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
