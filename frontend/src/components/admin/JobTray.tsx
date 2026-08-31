import { useEffect, useState } from 'react'

import { getAclJob, retryAclJob, type AclJob } from '../../api/admin'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'

type Props = {
  jobIds: string[]
  onJobsChange?: (jobs: AclJob[]) => void
  onNotice?: (msg: string) => void
  onError?: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function SyncStatusBadge({ job }: { job: AclJob | null | undefined }) {
  if (!job) return <span className="text-slate-600">—</span>
  const color =
    job.status === 'succeeded'
      ? 'text-emerald-400'
      : job.status === 'failed'
        ? 'text-rose-400'
        : 'text-amber-300'
  return <span className={`text-xs font-medium ${color}`}>{job.status}</span>
}

export function JobTray({ jobIds, onJobsChange, onNotice, onError }: Props) {
  const [jobs, setJobs] = useState<AclJob[]>([])
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    if (jobIds.length === 0) {
      setJobs([])
      onJobsChange?.([])
      return
    }
    let cancelled = false
    let timer: number | undefined

    const poll = async () => {
      try {
        const next = await Promise.all(jobIds.map((id) => getAclJob(id)))
        if (cancelled) return
        setJobs(next)
        onJobsChange?.(next)
        const stillActive = next.some((j) => j.status === 'queued' || j.status === 'running')
        if (stillActive && timer === undefined) {
          timer = window.setInterval(() => {
            void poll()
          }, 1000)
        }
        if (!stillActive && timer !== undefined) {
          window.clearInterval(timer)
          timer = undefined
        }
      } catch (err) {
        if (!cancelled) onError?.(errMessage(err))
      }
    }

    void poll()
    timer = window.setInterval(() => {
      void poll()
    }, 1000)

    return () => {
      cancelled = true
      if (timer !== undefined) window.clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobIds.join(',')])

  if (jobIds.length === 0) return null

  async function onRetry(job: AclJob) {
    setBusyId(job.id)
    try {
      const next = await retryAclJob(job.id)
      setJobs((prev) => prev.map((j) => (j.id === job.id ? next : j)))
      onNotice?.('Retry queued')
    } catch (err) {
      onError?.(errMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-slate-700 bg-slate-900/60 px-3 py-2">
      <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">Sync jobs</h3>
      <ul className="space-y-2 text-sm text-slate-300">
        {jobs.map((job) => (
          <li key={job.id} className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <SyncStatusBadge job={job} />
              <span className="ml-2 font-mono text-xs text-slate-500">{job.id.slice(0, 8)}…</span>
              {job.total_chunks != null ? (
                <span className="ml-2 text-xs text-slate-500">
                  {job.updated_chunks ?? 0}/{job.total_chunks} chunks
                </span>
              ) : null}
              {job.error ? <p className="mt-0.5 text-xs text-rose-400">{job.error}</p> : null}
            </div>
            {job.status === 'failed' ? (
              <Button
                type="button"
                disabled={busyId === job.id}
                onClick={() => void onRetry(job)}
              >
                {busyId === job.id ? 'Retrying…' : 'Retry'}
              </Button>
            ) : null}
          </li>
        ))}
        {jobs.length === 0 ? <li className="text-slate-500">Loading jobs…</li> : null}
      </ul>
    </div>
  )
}
