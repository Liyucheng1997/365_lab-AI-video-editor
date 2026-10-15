import { create } from 'zustand'
import { api } from './api'
import type { Asset, Clip, Job, Project, Timeline, Track } from './types'

type Tab = 'media' | 'ai' | 'text' | 'audio'

interface State {
  project: Project | null
  config: any
  tab: Tab
  // 时间线编辑
  past: Timeline[]
  future: Timeline[]
  selected: string[]
  time: number
  playing: boolean
  zoom: number
  snap: boolean
  dirty: boolean
  saving: boolean
  jobs: Job[]
  toast: { msg: string; kind: 'info' | 'error' } | null
  exactFrame: string | null

  load: (pid: string) => Promise<void>
  reload: (parts: ('assets' | 'script' | 'timeline' | 'all')[]) => Promise<void>
  setTab: (t: Tab) => void
  /** 修改时间线：fn 可以直接改传入的副本；record=false 用于拖拽过程中（开头已记录过） */
  edit: (fn: (tl: Timeline) => void, record?: boolean) => void
  checkpoint: () => void
  undo: () => void
  redo: () => void
  select: (id: string | null, add?: boolean) => void
  setTime: (t: number) => void
  setPlaying: (p: boolean) => void
  setZoom: (z: number) => void
  patchProject: (part: Partial<Project>) => void
  save: () => Promise<void>
  trackJob: (j: Job | null) => void
  notify: (msg: string, kind?: 'info' | 'error') => void
  setExactFrame: (u: string | null) => void
}

let saveTimer: any = null
let metaTimer: any = null
const clone = <T,>(x: T): T => structuredClone(x)

export const useStore = create<State>((set, get) => ({
  project: null, config: null, tab: 'media',
  past: [], future: [], selected: [], time: 0, playing: false, zoom: 40, snap: true,
  dirty: false, saving: false, jobs: [], toast: null, exactFrame: null,

  async load(pid) {
    const [p, cfg] = await Promise.all([api.project(pid), get().config ? Promise.resolve(get().config) : api.config()])
    set({ project: p, config: cfg, past: [], future: [], selected: [], time: 0, playing: false, dirty: false })
    const js = await api.jobs(pid)
    js.filter(j => j.status === 'running').forEach(j => get().trackJob(j))
    if (!p.timeline.tracks.some(t => t.clips.length) && !p.assets.length) set({ tab: 'media' })
    else if (!p.timeline.tracks.some(t => t.clips.length)) set({ tab: 'ai' })
  },

  async reload(parts) {
    const p0 = get().project
    if (!p0) return
    if (get().dirty) await get().save()
    const p = await api.project(p0.id)
    const cur = get().project!
    const all = parts.includes('all')
    set({
      project: {
        ...cur,
        assets: all || parts.includes('assets') ? p.assets : cur.assets,
        script: all || parts.includes('script') ? p.script : cur.script,
        timeline: all || parts.includes('timeline') ? p.timeline : cur.timeline,
        brief: all ? p.brief : cur.brief,
      },
      ...(all || parts.includes('timeline') ? { past: [...get().past, cur.timeline].slice(-100), future: [] } : {}),
    })
  },

  setTab: tab => set({ tab }),

  edit(fn, record = true) {
    const p = get().project
    if (!p) return
    const tl = clone(p.timeline)
    fn(tl)
    tl.duration = Math.max(0, ...tl.tracks.flatMap(t => t.clips.map(c => c.start + c.duration)))
    set({
      project: { ...p, timeline: tl },
      ...(record ? { past: [...get().past, p.timeline].slice(-100), future: [] } : {}),
      dirty: true, exactFrame: null,
    })
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => get().save(), 800)
  },

  checkpoint() {
    const p = get().project
    if (p) set({ past: [...get().past, clone(p.timeline)].slice(-100), future: [] })
  },

  undo() {
    const { past, project, future } = get()
    if (!past.length || !project) return
    set({ project: { ...project, timeline: past[past.length - 1] }, past: past.slice(0, -1), future: [project.timeline, ...future], dirty: true })
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => get().save(), 800)
  },

  redo() {
    const { past, project, future } = get()
    if (!future.length || !project) return
    set({ project: { ...project, timeline: future[0] }, future: future.slice(1), past: [...past, project.timeline], dirty: true })
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => get().save(), 800)
  },

  select(id, add) {
    if (id === null) return set({ selected: [] })
    const s = get().selected
    set({ selected: add ? (s.includes(id) ? s.filter(x => x !== id) : [...s, id]) : [id] })
  },

  setTime: t => set({ time: Math.max(0, t), exactFrame: null }),
  setPlaying: playing => set({ playing, exactFrame: null }),
  setZoom: z => set({ zoom: Math.min(400, Math.max(4, z)) }),

  patchProject(part) {
    const p = get().project
    if (!p) return
    set({ project: { ...p, ...part } })
    clearTimeout(metaTimer)
    const keys = Object.keys(part)
    metaTimer = setTimeout(() => {
      const cur = get().project!
      const body: any = {}
      keys.forEach(k => (body[k] = (cur as any)[k]))
      api.patch(cur.id, body).catch(e => get().notify('保存失败：' + e.message, 'error'))
    }, 600)
  },

  async save() {
    const p = get().project
    if (!p || !get().dirty) return
    set({ saving: true, dirty: false })
    try { await api.patch(p.id, { timeline: p.timeline }) } catch (e: any) {
      set({ dirty: true })
      get().notify('保存失败：' + e.message, 'error')
    }
    set({ saving: false })
  },

  trackJob(j) {
    if (!j) return
    set({ jobs: [...get().jobs.filter(x => x.id !== j.id), j] })
    const poll = async () => {
      let cur: Job
      try { cur = await api.job(j.id) } catch { return }
      set({ jobs: get().jobs.map(x => (x.id === j.id ? cur : x)) })
      if (cur.status === 'running') return setTimeout(poll, 800)
      const parts: any = { ingest: ['assets'], analyze: ['assets'], script: ['script', 'assets'], build: ['all'], export: [] }[cur.kind]
      if (cur.status === 'done' && parts.length) await get().reload(parts)
      if (cur.status === 'error') get().notify(`${jobName(cur.kind)}失败：${cur.error}`, 'error')
      else if (cur.status === 'done') get().notify(`${jobName(cur.kind)}完成`)
      setTimeout(() => set({ jobs: get().jobs.filter(x => x.id !== j.id) }), cur.kind === 'export' ? 600000 : 4000)
    }
    setTimeout(poll, 500)
  },

  notify(msg, kind = 'info') {
    set({ toast: { msg, kind } })
    setTimeout(() => get().toast?.msg === msg && set({ toast: null }), kind === 'error' ? 8000 : 3000)
  },
  setExactFrame: u => set({ exactFrame: u }),
}))

export const jobName = (k: string) => ({ ingest: '素材处理', analyze: 'AI 素材分析', script: 'AI 剪辑脚本', build: '执行剪辑', export: '导出视频' } as any)[k] || k

// ---------------------------------------------------------------- 工具
export function findClip(tl: Timeline, id: string): { clip: Clip; track: Track } | null {
  for (const track of tl.tracks) {
    const clip = track.clips.find(c => c.id === id)
    if (clip) return { clip, track }
  }
  return null
}

export function assetOf(p: Project | null, id?: string): Asset | undefined {
  return p?.assets.find(a => a.id === id)
}

export const uid = (p: string) => p + Math.random().toString(36).slice(2, 8)

export const speedOf = (c: any) => (c.freeze ? 0 : (c.out - c.in) / Math.max(1e-3, c.duration))
