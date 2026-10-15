import type { Job, JobDetail, JobEventData, JobReport, JobStatus } from '../../api/types'

/** What the job panel shows. It is rebuilt from the job's events, which the server replays. */
export interface JobView {
  id: string
  kind: string
  params: Record<string, unknown>
  status: 'connecting' | JobStatus
  index: number
  total: number | null
  title: string
  done: number
  skipped: number
  failed: number
  warnings: string[]
  report: JobReport | null
  error: string | null
  cancelRequested: boolean
  /** The event stream broke before the job ended. */
  streamLost: boolean
}

export type JobAction =
  | { type: 'reset'; job: Job }
  | { type: 'progress'; data: JobEventData['progress'] }
  | { type: 'warning'; data: JobEventData['warning'] }
  | { type: 'done'; data: JobEventData['done'] }
  | { type: 'failed'; data: JobEventData['failed'] }
  | { type: 'cancelled'; data: JobEventData['cancelled'] }
  | { type: 'cancelRequested' }
  | { type: 'settled'; job: JobDetail }
  | { type: 'lost' }

export function initialJobView(job: Job): JobView {
  return {
    id: job.id,
    kind: job.kind,
    params: job.params,
    status: job.status === 'running' ? 'connecting' : job.status,
    index: job.progress?.index ?? 0,
    total: job.progress?.total ?? null,
    title: '',
    done: 0,
    skipped: 0,
    failed: 0,
    warnings: [],
    report: null,
    error: job.error,
    cancelRequested: job.cancel_requested,
    streamLost: false,
  }
}

export function isFinal(status: JobView['status']): boolean {
  return status === 'done' || status === 'failed' || status === 'cancelled'
}

export function jobReducer(view: JobView, action: JobAction): JobView {
  switch (action.type) {
    case 'reset':
      return initialJobView(action.job)
    case 'progress': {
      const { kind, index, total, title } = action.data
      return {
        ...view,
        status: isFinal(view.status) ? view.status : 'running',
        index,
        total,
        title: title || view.title,
        done: view.done + (kind === 'track_done' ? 1 : 0),
        skipped: view.skipped + (kind === 'track_skipped' ? 1 : 0),
        failed: view.failed + (kind === 'track_failed' ? 1 : 0),
      }
    }
    case 'warning':
      return { ...view, warnings: [...view.warnings, action.data.message] }
    case 'done':
      return { ...view, status: 'done', report: action.data.report, streamLost: false }
    case 'failed':
      return {
        ...view,
        status: 'failed',
        report: action.data.report,
        error: action.data.error,
        streamLost: false,
      }
    case 'cancelled':
      return { ...view, status: 'cancelled', report: action.data.report, streamLost: false }
    case 'cancelRequested':
      return { ...view, cancelRequested: true }
    case 'settled':
      return {
        ...view,
        status: action.job.status,
        report: action.job.report ?? view.report,
        error: action.job.error ?? view.error,
        cancelRequested: action.job.cancel_requested,
        streamLost: action.job.status === 'running',
      }
    case 'lost':
      return { ...view, streamLost: true }
  }
}
