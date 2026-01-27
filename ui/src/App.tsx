import React, { useEffect, useState } from 'react'
import { createRun, getBugs, getIssues, getRun, listRuns, bugsCsvUrl, eventsUrl, RunCreate, getWorkerStatus, WorkerStatus } from './api'
import SettingsPage from './Settings'

type Run = {
  id: string
  status: string
  created_at: string
  started_at?: string
  finished_at?: string
  repo_url: string
  branch: string
  app_dir: string
  ui_dir: string
  suite: string
  summary_json?: any
  error_message?: string
}

type Bug = {
  bug_id: string
  timestamp: string
  test_type: string
  workflow: string
  severity: string
  title: string
  expected: string
  actual: string
  repro_steps: string
  page_url: string
  github_issue_url?: string
  confidence: number
}

type Issue = { bug_id: string; issue_url: string }

function badge(status: string) {
  if (status === 'succeeded') return <span className="badge ok">succeeded</span>
  if (status === 'failed') return <span className="badge fail">failed</span>
  if (status === 'running') return <span className="badge run">running</span>
  return <span className="badge">{status}</span>
}

export default function App() {
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [bugs, setBugs] = useState<Bug[]>([])
  const [issues, setIssues] = useState<Issue[]>([])
  const [events, setEvents] = useState<any[]>([])
  const [err, setErr] = useState<string>('')
  const [showSettings, setShowSettings] = useState(false)
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus | null>(null)

  const [form, setForm] = useState<RunCreate>({
    repo_url: 'https://github.com/org/repo',
    branch: 'main',
    app_dir: 'apps/web',
    ui_dir: 'apps/web',
    suite: 'both',
    create_github_issues: true,
    commit_results: false,
  })

  async function refreshRuns() {
    try {
      setRuns(await listRuns())
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }

  useEffect(() => { refreshRuns() }, [])

  // Poll worker status
  useEffect(() => {
    async function fetchWorkerStatus() {
      try {
        const status = await getWorkerStatus()
        setWorkerStatus(status)
      } catch {
        // ignore
      }
    }
    fetchWorkerStatus()
    const interval = setInterval(fetchWorkerStatus, 5000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (!selectedRunId) return
    let alive = true
    ;(async () => {
      try {
        const r = await getRun(selectedRunId)
        if (!alive) return
        setSelectedRun(r)
        setBugs(await getBugs(selectedRunId))
        setIssues(await getIssues(selectedRunId))
      } catch (e: any) {
        setErr(String(e?.message || e))
      }
    })()
    return () => { alive = false }
  }, [selectedRunId])

  useEffect(() => {
    if (!selectedRunId) return
    setEvents([])
    const es = new EventSource(eventsUrl(selectedRunId))
    es.onmessage = (evt) => {
      try {
        const obj = JSON.parse(evt.data)
        setEvents(prev => [...prev, obj].slice(-300))
        // refresh run/bugs on terminal states
        if (obj.type === 'step' && obj.step === 'done') {
          refreshRuns()
          getRun(selectedRunId).then(setSelectedRun).catch(()=>{})
          getBugs(selectedRunId).then(setBugs).catch(()=>{})
          getIssues(selectedRunId).then(setIssues).catch(()=>{})
        }
      } catch {
        setEvents(prev => [...prev, { type: 'raw', data: evt.data }].slice(-300))
      }
    }
    es.onerror = () => {
      // keep quiet; backend may not have events yet
    }
    return () => es.close()
  }, [selectedRunId])

  async function onCreateRun() {
    setErr('')
    try {
      const r = await createRun(form)
      await refreshRuns()
      setSelectedRunId(r.id)
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }

  return (
    <div className="container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0 }}>UIQA MVP</h1>
          <small>Trigger agentic UI QA runs (ClaudeCode + Playwright + GitHub Issues).</small>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 12 }}>Worker:</span>
            {workerStatus?.running ? (
              <span className="badge ok">Running ({workerStatus.mode})</span>
            ) : (
              <span className="badge fail">Stopped</span>
            )}
          </div>
          <button onClick={() => setShowSettings(!showSettings)} style={{ padding: '8px 16px' }}>
            {showSettings ? 'Close Settings' : 'Settings'}
          </button>
        </div>
      </div>

      {showSettings && <SettingsPage onClose={() => setShowSettings(false)} />}

      {err && (
        <div className="card" style={{ marginTop: 12, borderColor: 'rgba(239,68,68,.5)' }}>
          <strong>Error</strong>
          <div className="mono" style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{err}</div>
        </div>
      )}

      <div className="row" style={{ marginTop: 16 }}>
        <div className="col card">
          <h2>Create run</h2>
          <div style={{ display: 'grid', gap: 10 }}>
            <label>
              <small>Repo URL</small>
              <input value={form.repo_url} onChange={e => setForm({ ...form, repo_url: e.target.value })} />
            </label>
            <div className="row">
              <label className="col">
                <small>Branch</small>
                <input value={form.branch} onChange={e => setForm({ ...form, branch: e.target.value })} />
              </label>
              <label className="col">
                <small>Suite</small>
                <select value={form.suite} onChange={e => setForm({ ...form, suite: e.target.value as any })}>
                  <option value="smoke">smoke</option>
                  <option value="regression">regression</option>
                  <option value="both">both</option>
                </select>
              </label>
            </div>
            <div className="row">
              <label className="col">
                <small>app_dir</small>
                <input value={form.app_dir} onChange={e => setForm({ ...form, app_dir: e.target.value })} />
              </label>
              <label className="col">
                <small>ui_dir</small>
                <input value={form.ui_dir} onChange={e => setForm({ ...form, ui_dir: e.target.value })} />
              </label>
            </div>
            <div className="row">
              <label className="col">
                <small>
                  <input type="checkbox" checked={form.create_github_issues}
                    onChange={e => setForm({ ...form, create_github_issues: e.target.checked })} />{' '}
                  Create GitHub issues
                </small>
              </label>
              <label className="col">
                <small>
                  <input type="checkbox" checked={form.commit_results}
                    onChange={e => setForm({ ...form, commit_results: e.target.checked })} />{' '}
                  Commit results (optional)
                </small>
              </label>
            </div>
            <button onClick={onCreateRun}>Run</button>
            <small className="mono">Backend: {((import.meta as any).env.VITE_API_BASE || 'http://localhost:8000')}</small>
          </div>
        </div>

        <div className="col card">
          <h2>Runs</h2>
          <small>Click a run to view details, bugs, and live events.</small>
          <div style={{ marginTop: 10 }}>
            {runs.length === 0 && <small>No runs yet.</small>}
            {runs.map(r => (
              <div key={r.id} style={{ padding: '10px 0', borderBottom: '1px solid #1f2a4a' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <div>
                    <div className="mono" style={{ fontSize: 13 }}>{r.id}</div>
                    <small>{r.repo_url} ({r.branch})</small>
                  </div>
                  <div>{badge(r.status)}</div>
                </div>
                <div style={{ marginTop: 8, display: 'flex', gap: 10 }}>
                  <button onClick={() => setSelectedRunId(r.id)}>Open</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {selectedRun && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Run details</h2>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <div><strong>ID:</strong> <span className="mono">{selectedRun.id}</span></div>
              <div><strong>Status:</strong> {badge(selectedRun.status)}</div>
              <div><strong>Repo:</strong> <span className="mono">{selectedRun.repo_url}</span></div>
              <div><strong>Dirs:</strong> <span className="mono">{selectedRun.app_dir}</span> / <span className="mono">{selectedRun.ui_dir}</span></div>
              <div><strong>Suite:</strong> <span className="mono">{selectedRun.suite}</span></div>
            </div>
            <div>
              <a href={bugsCsvUrl(selectedRun.id)} target="_blank" rel="noreferrer">Download bugs.csv</a>
              {selectedRun.error_message && (
                <div style={{ marginTop: 8 }}>
                  <strong>Error:</strong>
                  <div className="mono" style={{ whiteSpace: 'pre-wrap' }}>{selectedRun.error_message}</div>
                </div>
              )}
            </div>
          </div>

          <hr />

          <h3>Bugs</h3>
          {bugs.length === 0 ? (
            <small>No bugs recorded for this run (yet).</small>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Title</th>
                    <th>Type</th>
                    <th>Workflow</th>
                    <th>Issue</th>
                  </tr>
                </thead>
                <tbody>
                  {bugs.map(b => (
                    <tr key={b.bug_id}>
                      <td><span className="badge">{b.severity}</span></td>
                      <td>
                        <div><strong>{b.title}</strong></div>
                        <small className="mono">{b.bug_id}</small>
                        <div style={{ marginTop: 6 }}><small>{b.actual}</small></div>
                      </td>
                      <td><span className="badge">{b.test_type}</span></td>
                      <td><small>{b.workflow}</small></td>
                      <td>
                        {b.github_issue_url ? <a href={b.github_issue_url} target="_blank" rel="noreferrer">Issue</a> : <small>—</small>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <hr />

          <h3>Issues</h3>
          {issues.length === 0 ? <small>No issues created.</small> : (
            <ul>
              {issues.map(i => (
                <li key={i.bug_id} className="mono">
                  {i.bug_id}: <a href={i.issue_url} target="_blank" rel="noreferrer">{i.issue_url}</a>
                </li>
              ))}
            </ul>
          )}

          <hr />

          <h3>Live events</h3>
          <small>Backend streams events over SSE. Showing last {events.length}.</small>
          <div className="mono" style={{ marginTop: 10, maxHeight: 260, overflow: 'auto', background: '#0b1220', padding: 12, borderRadius: 10, border: '1px solid #1f2a4a' }}>
            {events.map((e, idx) => (
              <div key={idx} style={{ whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(e)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
