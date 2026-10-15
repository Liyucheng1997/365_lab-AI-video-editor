import type { Job, Project } from './types'

async function req<T>(method: string, url: string, body?: any): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch { /* */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return r.json()
}

export const api = {
  config: () => req<any>('GET', '/api/config'),
  projects: () => req<any[]>('GET', '/api/projects'),
  create: (name: string, width: number, height: number) => req<Project>('POST', '/api/projects', { name, width, height }),
  project: (pid: string) => req<Project>('GET', `/api/projects/${pid}`),
  patch: (pid: string, body: Partial<Project>) => req<any>('PATCH', `/api/projects/${pid}`, body),
  remove: (pid: string) => req<any>('DELETE', `/api/projects/${pid}`),
  importPaths: (pid: string, body: { paths?: string[]; folder?: string; recursive?: boolean }) =>
    req<{ assetIds: string[]; job: Job | null }>('POST', `/api/projects/${pid}/import`, body),
  browse: (path: string) => req<any>('GET', `/api/browse?path=${encodeURIComponent(path)}`),
  deleteAsset: (pid: string, aid: string) => req<any>('DELETE', `/api/projects/${pid}/assets/${aid}`),
  analyze: (pid: string, body: any = {}) => req<Job>('POST', `/api/projects/${pid}/analyze`, body),
  script: (pid: string, feedback?: string) => req<Job>('POST', `/api/projects/${pid}/script`, { feedback }),
  build: (pid: string) => req<Job>('POST', `/api/projects/${pid}/build`),
  exportVideo: (pid: string, quality: string) => req<Job>('POST', `/api/projects/${pid}/export`, { quality }),
  exports: (pid: string) => req<any[]>('GET', `/api/projects/${pid}/exports`),
  reveal: (pid: string, path: string) => req<any>('POST', `/api/projects/${pid}/reveal`, { path }),
  tts: (pid: string, lines: any[], name?: string, voice?: string) => req<any>('POST', `/api/projects/${pid}/tts`, { lines, name, voice }),
  music: (pid: string, body: any) => req<any>('POST', `/api/projects/${pid}/music`, body),
  job: (jid: string) => req<Job>('GET', `/api/jobs/${jid}`),
  jobs: (pid: string) => req<Job[]>('GET', `/api/projects/${pid}/jobs`),
  cancel: (jid: string) => req<Job>('POST', `/api/jobs/${jid}/cancel`),
}

export const assetUrl = (pid: string, aid: string, which: string, v?: number | string) =>
  `/api/projects/${pid}/assets/${aid}/${which}${v ? `?v=${v}` : ''}`
export const fileUrl = (pid: string, path: string, download = false) =>
  `/api/projects/${pid}/files/${path}${download ? '?download=1' : ''}`

export function upload(pid: string, files: File[], onProgress: (p: number) => void): Promise<{ assetIds: string[]; job: Job }> {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    const x = new XMLHttpRequest()
    x.open('POST', `/api/projects/${pid}/upload`)
    x.upload.onprogress = e => e.lengthComputable && onProgress(e.loaded / e.total)
    x.onload = () => (x.status < 300 ? resolve(JSON.parse(x.responseText)) : reject(new Error(x.responseText)))
    x.onerror = () => reject(new Error('上传失败'))
    x.send(fd)
  })
}

const textCache = new Map<string, string>()
const textPending = new Map<string, Promise<string>>()
/** 文字图层 PNG（后端用最终渲染同一套代码排版） */
export function textPng(clip: any, width: number, height: number): Promise<string> {
  const { id, start, duration, label, sectionId, ...style } = clip
  const key = JSON.stringify([style, width, height])
  const hit = textCache.get(key)
  if (hit) return Promise.resolve(hit)
  let p = textPending.get(key)
  if (!p) {
    p = fetch('/api/text/render', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clip: style, width, height }),
    }).then(r => r.blob()).then(b => {
      const u = URL.createObjectURL(b)
      textCache.set(key, u)
      textPending.delete(key)
      return u
    })
    textPending.set(key, p)
  }
  return p
}

const peakCache = new Map<string, Promise<{ rate: number; peaks: number[] }>>()
export function peaks(pid: string, aid: string) {
  const k = pid + aid
  if (!peakCache.has(k)) peakCache.set(k, fetch(assetUrl(pid, aid, 'peaks')).then(r => r.json()))
  return peakCache.get(k)!
}

export const fmt = (t: number, ms = true) => {
  if (!isFinite(t)) t = 0
  const m = Math.floor(t / 60), s = t - m * 60
  return `${String(m).padStart(2, '0')}:${ms ? s.toFixed(1).padStart(4, '0') : String(Math.floor(s)).padStart(2, '0')}`
}
