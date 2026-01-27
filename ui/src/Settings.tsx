import React, { useEffect, useState } from 'react'
import {
  getWorkerStatus,
  startWorker,
  stopWorker,
  getSettings,
  updateSettings,
  WorkerStatus,
  Settings,
} from './api'

function formatUptime(seconds?: number): string {
  if (!seconds) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export default function SettingsPage({ onClose }: { onClose: () => void }) {
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Form state
  const [selectedMode, setSelectedMode] = useState<'local' | 'docker'>('local')
  const [apiKey, setApiKey] = useState('')
  const [githubToken, setGithubToken] = useState('')
  const [initialized, setInitialized] = useState(false)

  async function refresh(isInitial = false) {
    try {
      const [ws, s] = await Promise.all([getWorkerStatus(), getSettings()])
      setWorkerStatus(ws)
      setSettings(s)
      // Only set selectedMode on initial load, not on every refresh
      if (isInitial) {
        setSelectedMode(s.worker_mode as 'local' | 'docker')
        setInitialized(true)
      }
    } catch (e: any) {
      setError(String(e?.message || e))
    }
  }

  useEffect(() => {
    refresh(true)  // Initial load
    const interval = setInterval(() => refresh(false), 3000)  // Subsequent refreshes
    return () => clearInterval(interval)
  }, [])

  async function handleStart() {
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await startWorker({
        mode: selectedMode,
        api_key: selectedMode === 'docker' ? apiKey || undefined : undefined,
      })
      if (result.success) {
        setSuccess('Worker started successfully')
        await refresh()
      } else {
        setError(result.error || 'Failed to start worker')
      }
    } catch (e: any) {
      setError(String(e?.message || e))
    }
    setLoading(false)
  }

  async function handleStop() {
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await stopWorker()
      if (result.success) {
        setSuccess('Worker stopped')
        await refresh()
      } else {
        setError(result.error || 'Failed to stop worker')
      }
    } catch (e: any) {
      setError(String(e?.message || e))
    }
    setLoading(false)
  }

  async function handleSaveSettings() {
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const updates: any = { worker_mode: selectedMode }
      if (apiKey) updates.anthropic_api_key = apiKey
      if (githubToken) updates.github_token = githubToken

      await updateSettings(updates)
      setSuccess('Settings saved')
      setApiKey('')
      setGithubToken('')
      await refresh()
    } catch (e: any) {
      setError(String(e?.message || e))
    }
    setLoading(false)
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Settings</h2>
        <button onClick={onClose} style={{ padding: '6px 12px' }}>Close</button>
      </div>

      {error && (
        <div style={{ padding: '10px', background: 'rgba(239,68,68,0.15)', borderRadius: 6, marginTop: 12 }}>
          <strong>Error:</strong> {error}
        </div>
      )}
      {success && (
        <div style={{ padding: '10px', background: 'rgba(34,197,94,0.15)', borderRadius: 6, marginTop: 12 }}>
          {success}
        </div>
      )}

      <hr style={{ margin: '16px 0' }} />

      {/* Worker Status */}
      <h3>Worker Status</h3>
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}>
        <div>
          <strong>Status:</strong>{' '}
          {workerStatus?.running ? (
            <span className="badge ok">Running</span>
          ) : (
            <span className="badge fail">Stopped</span>
          )}
        </div>
        {workerStatus?.running && (
          <>
            <div><strong>Mode:</strong> <span className="mono">{workerStatus.mode}</span></div>
            <div><strong>PID:</strong> <span className="mono">{workerStatus.pid}</span></div>
            <div><strong>Uptime:</strong> <span className="mono">{formatUptime(workerStatus.uptime_seconds)}</span></div>
          </>
        )}
      </div>

      <hr style={{ margin: '16px 0' }} />

      {/* Worker Mode Selection */}
      <h3>Worker Configuration</h3>
      <div style={{ marginTop: 12 }}>
        <label>
          <small>Worker Mode</small>
          <select
            value={selectedMode}
            onChange={(e) => setSelectedMode(e.target.value as 'local' | 'docker')}
            style={{ width: '100%', marginTop: 4 }}
          >
            <option value="local">Local</option>
            <option value="docker">Docker (API Key)</option>
          </select>
        </label>
        <small style={{ display: 'block', marginTop: 4, opacity: 0.7 }}>
          {selectedMode === 'local'
            ? 'Uses Claude Max subscription via macOS Keychain'
            : 'Uses Anthropic API key for Claude Code'}
        </small>
      </div>

      {selectedMode === 'docker' && (
        <div style={{ marginTop: 12 }}>
          <label>
            <small>Anthropic API Key {settings?.anthropic_api_key && `(current: ${settings.anthropic_api_key})`}</small>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-ant-api03-..."
              style={{ width: '100%', marginTop: 4 }}
            />
          </label>
          <small style={{ display: 'block', marginTop: 4, opacity: 0.7 }}>
            Leave empty to keep existing key. Get key from console.anthropic.com
          </small>
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        <label>
          <small>GitHub Token (optional) {settings?.github_token && `(current: ${settings.github_token})`}</small>
          <input
            type="password"
            value={githubToken}
            onChange={(e) => setGithubToken(e.target.value)}
            placeholder="ghp_..."
            style={{ width: '100%', marginTop: 4 }}
          />
        </label>
        <small style={{ display: 'block', marginTop: 4, opacity: 0.7 }}>
          For creating GitHub issues on private repos
        </small>
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
        <button onClick={handleSaveSettings} disabled={loading}>
          Save Settings
        </button>
      </div>

      <hr style={{ margin: '16px 0' }} />

      {/* Worker Controls */}
      <h3>Worker Controls</h3>
      <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
        {!workerStatus?.running ? (
          <button onClick={handleStart} disabled={loading} style={{ background: '#22c55e' }}>
            {loading ? 'Starting...' : 'Start Worker'}
          </button>
        ) : (
          <button onClick={handleStop} disabled={loading} style={{ background: '#ef4444' }}>
            {loading ? 'Stopping...' : 'Stop Worker'}
          </button>
        )}
      </div>

      {/* Worker Logs */}
      {workerStatus && workerStatus.log_tail.length > 0 && (
        <>
          <h4 style={{ marginTop: 16 }}>Recent Logs</h4>
          <div
            className="mono"
            style={{
              marginTop: 8,
              maxHeight: 200,
              overflow: 'auto',
              background: '#0b1220',
              padding: 12,
              borderRadius: 10,
              border: '1px solid #1f2a4a',
              fontSize: 11,
            }}
          >
            {workerStatus.log_tail.map((line, idx) => (
              <div key={idx}>{line}</div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
