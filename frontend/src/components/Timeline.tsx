import { memo, useEffect, useRef, useState } from 'react'
import { assetUrl, fmt, peaks } from '../api'
import { assetOf, findClip, speedOf, uid, useStore } from '../store'
import type { Asset, AudioClip, Clip, Project, TextClip, Timeline as TL, Track, VideoClip } from '../types'

const LANE_H: Record<string, number> = { video: 62, text: 30, audio: 42 }
const HEAD_W = 112

export default function Timeline() {
  const project = useStore(s => s.project)!
  const zoom = useStore(s => s.zoom)
  const tl = project.timeline
  const scroll = useRef<HTMLDivElement>(null)
  const width = Math.max(tl.duration + 30, 60) * zoom

  // Ctrl+滚轮缩放
  useEffect(() => {
    const el = scroll.current!
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return
      e.preventDefault()
      const st = useStore.getState()
      const rect = el.getBoundingClientRect()
      const x = e.clientX - rect.left - HEAD_W + el.scrollLeft
      const tAt = x / st.zoom
      const nz = Math.min(400, Math.max(4, st.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)))
      st.setZoom(nz)
      requestAnimationFrame(() => { el.scrollLeft = tAt * nz - (e.clientX - rect.left - HEAD_W) })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // 播放时跟随播放头
  useEffect(() => useStore.subscribe((s, prev) => {
    if (!s.playing || s.time === prev.time) return
    const el = scroll.current
    if (!el) return
    const x = s.time * s.zoom
    const vis = el.clientWidth - HEAD_W
    if (x < el.scrollLeft || x > el.scrollLeft + vis - 40) el.scrollLeft = x - 60
  }), [])

  return (
    <div className="timeline">
      <Toolbar scroll={scroll} />
      <div className="tl-scroll" ref={scroll}>
        <div className="tl-content" style={{ width: width + HEAD_W }}>
          <div className="tl-row ruler-row">
            <div className="tl-head corner" />
            <Ruler width={width} zoom={zoom} />
          </div>
          {tl.tracks.map(tr => <Lane key={tr.id} track={tr} width={width} zoom={zoom} project={project} />)}
          <Playhead />
        </div>
      </div>
    </div>
  )
}

function Toolbar({ scroll }: { scroll: React.RefObject<HTMLDivElement> }) {
  const st = useStore()
  const sel = st.selected
  const fit = () => {
    const el = scroll.current
    if (!el) return
    st.setZoom((el.clientWidth - HEAD_W - 40) / Math.max(5, st.project!.timeline.duration))
    el.scrollLeft = 0
  }
  return (
    <div className="tl-toolbar">
      <button className="icon" title="撤销 (Ctrl+Z)" disabled={!st.past.length} onClick={st.undo}>↶</button>
      <button className="icon" title="重做 (Ctrl+Y)" disabled={!st.future.length} onClick={st.redo}>↷</button>
      <span className="sep" />
      <button className="tool" title="在播放头处分割 (S)" onClick={splitAtPlayhead}>✂ 分割</button>
      <button className="tool" title="删除 (Delete)，Shift+Delete 删除并让后面的片段前移" disabled={!sel.length} onClick={() => deleteSelected(false)}>🗑 删除</button>
      <button className="tool" title="复制一份放到后面 (Ctrl+D)" disabled={!sel.length} onClick={duplicateSelected}>⧉ 复制</button>
      <button className="tool" title="在播放头处添加文字" onClick={() => addText('caption')}>T 文字</button>
      <span className="sep" />
      <label className="chk" title="拖动时吸附到其他片段边缘和播放头"><input type="checkbox" checked={st.snap} onChange={e => useStore.setState({ snap: e.target.checked })} />吸附</label>
      <div className="grow" />
      <span className="muted small">{st.saving ? '保存中…' : st.dirty ? '未保存' : '已自动保存'}</span>
      <span className="sep" />
      <button className="icon" title="缩小" onClick={() => st.setZoom(st.zoom / 1.3)}>－</button>
      <input type="range" min={4} max={400} value={st.zoom} onChange={e => st.setZoom(+e.target.value)} className="zoom" />
      <button className="icon" title="放大" onClick={() => st.setZoom(st.zoom * 1.3)}>＋</button>
      <button className="tool" title="缩放到整个时间线" onClick={fit}>适配</button>
    </div>
  )
}

function Ruler({ width, zoom }: { width: number; zoom: number }) {
  const steps = [0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120]
  const step = steps.find(s => s * zoom >= 70) || 120
  const n = Math.ceil(width / zoom / step)
  const down = (e: React.PointerEvent) => {
    const el = e.currentTarget as HTMLDivElement
    const r = el.getBoundingClientRect()
    const seek = (x: number) => useStore.getState().setTime(Math.max(0, (x - r.left) / useStore.getState().zoom))
    useStore.getState().setPlaying(false)
    seek(e.clientX)
    const mv = (ev: PointerEvent) => seek(ev.clientX)
    const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', mv)
    window.addEventListener('pointerup', up)
  }
  return (
    <div className="ruler" style={{ width, backgroundSize: `${(step * zoom) / 5}px 100%` }} onPointerDown={down}>
      {Array.from({ length: n + 1 }, (_, i) => (
        <span key={i} style={{ left: i * step * zoom }}>{fmt(i * step, step < 1)}</span>
      ))}
    </div>
  )
}

function Playhead() {
  const time = useStore(s => s.time)
  const zoom = useStore(s => s.zoom)
  return <div className="playhead" style={{ left: HEAD_W + time * zoom }}><div className="knob" /></div>
}

const Lane = memo(function Lane({ track, width, zoom, project }: { track: Track; width: number; zoom: number; project: Project }) {
  const selected = useStore(s => s.selected)
  const h = LANE_H[track.type]
  const onDrop = (e: React.DragEvent) => {
    const aid = e.dataTransfer.getData('application/x-asset')
    if (!aid) return
    e.preventDefault()
    const r = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    addAssetClip(aid, Math.max(0, (e.clientX - r.left) / zoom), track.id)
  }
  const bgDown = (e: React.PointerEvent) => {
    if (e.target !== e.currentTarget) return
    const r = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    const st = useStore.getState()
    st.select(null)
    st.setPlaying(false)
    st.setTime((e.clientX - r.left) / zoom)
  }
  const toggle = (k: 'muted' | 'hidden') => useStore.getState().edit(tl => {
    const t = tl.tracks.find(x => x.id === track.id)!
    t[k] = !t[k]
  })
  return (
    <div className={`tl-row lane-${track.type}`} style={{ height: h }}>
      <div className="tl-head">
        <span className="tname">{track.name}</span>
        {track.type !== 'audio' && <button className={'mini' + (track.hidden ? ' off' : '')} title={track.hidden ? '显示轨道' : '隐藏轨道'} onClick={() => toggle('hidden')}>{track.hidden ? '◌' : '◉'}</button>}
        {track.type !== 'text' && <button className={'mini' + (track.muted ? ' off' : '')} title={track.muted ? '取消静音' : '静音'} onClick={() => toggle('muted')}>{track.muted ? '🔇' : '🔊'}</button>}
      </div>
      <div className="lane" data-track={track.id} data-type={track.type} style={{ width }}
        onPointerDown={bgDown} onDragOver={e => e.preventDefault()} onDrop={onDrop}>
        {track.clips.map(c => (
          <ClipView key={c.id} clip={c} track={track} zoom={zoom} project={project} sel={selected.includes(c.id)} />
        ))}
      </div>
    </div>
  )
})

const TEXT_LABEL: Record<string, string> = { subtitle: '字幕', heading: '段落标题', word: '大字', title: '标题卡', caption: '文字' }

const ClipView = memo(function ClipView({ clip, track, zoom, project, sel }: { clip: Clip; track: Track; zoom: number; project: Project; sel: boolean }) {
  const left = clip.start * zoom
  const w = Math.max(2, clip.duration * zoom)
  let body: React.ReactNode = null
  let cls = `clip clip-${track.type}`
  const style: React.CSSProperties = { left, width: w }
  if (track.type === 'video') {
    const c = clip as VideoClip
    const a = assetOf(project, c.assetId)
    const sp = speedOf(c)
    if (a?.strip) {
      if (c.freeze || a.kind === 'image') {
        style.backgroundImage = `url(${assetUrl(project.id, a.id, 'thumb')})`
        style.backgroundSize = 'auto 100%'
        style.backgroundRepeat = 'repeat-x'
      } else {
        style.backgroundImage = `url(${assetUrl(project.id, a.id, 'strip')})`
        style.backgroundSize = `${(a.duration * zoom) / sp}px 100%`
        style.backgroundPosition = `${(-c.in * zoom) / sp}px 0`
        style.backgroundRepeat = 'no-repeat'
      }
    }
    const tr = c.transition?.type
    body = <>
      {tr && tr !== 'none' && <span className="tr-badge" title={'转场：' + trName(tr)}>{trIcon(tr)}</span>}
      <span className="clabel">{c.label ? <b>{c.label}</b> : null}{a?.name.replace(/\.[^.]+$/, '').slice(-10)}</span>
      <span className="cbadges">{c.freeze ? '定格 ' : Math.abs(sp - 1) > 0.02 ? sp.toFixed(2) + 'x ' : ''}{(c.volume ?? 0) > 0 ? '' : '🔇'}</span>
    </>
  } else if (track.type === 'text') {
    const c = clip as TextClip
    cls += ` tp-${c.preset}`
    body = <span className="clabel">{TEXT_LABEL[c.preset]}｜{c.num ? c.num + ' ' : ''}{c.text || c.kicker}</span>
  } else {
    const c = clip as AudioClip
    const a = assetOf(project, c.assetId)
    cls += ` role-${track.role}`
    body = <>
      {a && <Wave pid={project.id} asset={a} inT={c.in} dur={c.duration} w={w} h={LANE_H.audio - 14} />}
      <span className="clabel">{a?.name}{c.volume !== 1 ? ` · ${Math.round(c.volume * 100)}%` : ''}</span>
    </>
  }
  return (
    <div className={cls + (sel ? ' sel' : '')} style={style} onPointerDown={e => startDrag(e, clip.id, 'move')}
      title={track.type === 'video' ? (clip as VideoClip).note || '' : ''}>
      {body}
      <div className="handle l" onPointerDown={e => startDrag(e, clip.id, 'l')} />
      <div className="handle r" onPointerDown={e => startDrag(e, clip.id, 'r')} />
    </div>
  )
})

const trName = (t: string) => ({ fade: '叠化', black: '黑场', white: '白场', flash: '闪白' } as any)[t] || t
const trIcon = (t: string) => ({ fade: '⧓', black: '◐', white: '◑', flash: '✦' } as any)[t] || ''

function Wave({ pid, asset, inT, dur, w, h }: { pid: string; asset: Asset; inT: number; dur: number; w: number; h: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [data, setData] = useState<{ rate: number; peaks: number[] } | null>(null)
  useEffect(() => { if (asset.peaks) peaks(pid, asset.id).then(setData).catch(() => {}) }, [pid, asset.id, asset.peaks])
  const cw = Math.min(4000, Math.max(1, Math.round(w)))
  useEffect(() => {
    const cv = ref.current
    if (!cv || !data) return
    const ctx = cv.getContext('2d')!
    ctx.clearRect(0, 0, cv.width, cv.height)
    ctx.fillStyle = 'rgba(255,255,255,0.55)'
    const n = data.peaks.length
    for (let x = 0; x < cw; x += 2) {
      const t0 = inT + (x / cw) * dur, t1 = inT + ((x + 2) / cw) * dur
      let m = 0
      for (let i = Math.floor(t0 * data.rate); i <= Math.min(n - 1, Math.floor(t1 * data.rate)); i++) m = Math.max(m, data.peaks[i] || 0)
      const bh = Math.max(1, m * h)
      ctx.fillRect(x, (h - bh) / 2, 1.4, bh)
    }
  }, [data, cw, h, inT, dur])
  return <canvas ref={ref} width={cw} height={h} className="wave" style={{ width: w, height: h }} />
}

// ---------------------------------------------------------------- 拖动 / 裁剪
function startDrag(e: React.PointerEvent, id: string, mode: 'move' | 'l' | 'r') {
  e.stopPropagation()
  if (e.button !== 0) return
  const st = useStore.getState()
  if (mode === 'move' && e.shiftKey) { st.select(id, true); return }
  if (!st.selected.includes(id) || mode !== 'move') st.select(id)
  st.setPlaying(false)
  const ids = mode === 'move' ? useStore.getState().selected : [id]
  const tl0 = structuredClone(st.project!.timeline)
  const p = st.project!
  const x0 = e.clientX
  let started = false
  const orig = new Map(ids.map(i => [i, structuredClone(findClip(tl0, i)!.clip)]))
  const edges: number[] = [st.time, 0]
  for (const t of tl0.tracks) for (const c of t.clips) if (!ids.includes(c.id)) edges.push(c.start, c.start + c.duration)
  const snapT = (t: number) => {
    if (!useStore.getState().snap) return null
    const z = useStore.getState().zoom
    let best: number | null = null, bd = 8 / z
    for (const e of edges) if (Math.abs(e - t) < bd) { bd = Math.abs(e - t); best = e }
    return best
  }
  const mv = (ev: PointerEvent) => {
    const z = useStore.getState().zoom
    if (!started) {
      if (Math.abs(ev.clientX - x0) < 3 && mode === 'move') return
      started = true
      useStore.getState().checkpoint()
    }
    let d = (ev.clientX - x0) / z
    const main = orig.get(id)!
    if (mode === 'move') {
      const minStart = Math.min(...[...orig.values()].map(c => c.start))
      d = Math.max(d, -minStart)
      const s1 = snapT(main.start + d), s2 = snapT(main.start + main.duration + d)
      if (s1 != null) d = s1 - main.start
      else if (s2 != null) d = s2 - main.start - main.duration
      // 跨轨道（同类型）
      const el = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.lane') as HTMLElement | null
      const target = el?.dataset.track
      useStore.getState().edit(tl => {
        for (const [cid, oc] of orig) {
          const f = findClip(tl, cid)!
          f.clip.start = Math.max(0, +(oc.start + d).toFixed(3))
          if (ids.length === 1 && target && target !== f.track.id) {
            const dst = tl.tracks.find(t => t.id === target)
            if (dst && dst.type === f.track.type) {
              f.track.clips = f.track.clips.filter(c => c.id !== cid)
              dst.clips.push(f.clip)
            }
          }
        }
      }, false)
    } else {
      const f = findClip(tl0, id)!
      const a = assetOf(p, (main as any).assetId)
      const type = f.track.type
      useStore.getState().edit(tl => {
        const c = findClip(tl, id)!.clip as any
        const o = main as any
        if (mode === 'l') {
          let dd = d
          const sn = snapT(o.start + dd)
          if (sn != null) dd = sn - o.start
          dd = Math.min(dd, o.duration - 0.1)
          dd = Math.max(dd, -o.start)
          if (type === 'video' && !o.freeze && a?.kind === 'video') dd = Math.max(dd, -o.in / Math.max(1e-3, speedOf(o)))
          if (type === 'audio') dd = Math.max(dd, -o.in)
          c.start = +(o.start + dd).toFixed(3)
          c.duration = +(o.duration - dd).toFixed(3)
          if (type === 'video' && !o.freeze) c.in = +(o.in + dd * speedOf(o)).toFixed(3)
          if (type === 'audio') c.in = +(o.in + dd).toFixed(3)
          if (type === 'video' && o.freeze) c.out = c.in + 0.1
        } else {
          let dd = d
          const sn = snapT(o.start + o.duration + dd)
          if (sn != null) dd = sn - o.start - o.duration
          let dur = Math.max(0.1, o.duration + dd)
          if (type === 'video' && !o.freeze && a?.kind === 'video') dur = Math.min(dur, (a.duration - o.in) / Math.max(1e-3, speedOf(o)))
          if (type === 'audio' && a) dur = Math.min(dur, a.duration - o.in)
          c.duration = +dur.toFixed(3)
          if (type === 'video' && !o.freeze && a?.kind === 'video') c.out = +(o.in + dur * speedOf(o)).toFixed(3)
        }
      }, false)
    }
  }
  const up = () => {
    window.removeEventListener('pointermove', mv)
    window.removeEventListener('pointerup', up)
  }
  window.addEventListener('pointermove', mv)
  window.addEventListener('pointerup', up)
}

// ---------------------------------------------------------------- 编辑操作
export function splitAtPlayhead() {
  const st = useStore.getState()
  const t = st.time
  const tl = st.project!.timeline
  let targets = st.selected.filter(id => { const f = findClip(tl, id); return f && f.clip.start < t - 0.05 && t < f.clip.start + f.clip.duration - 0.05 })
  if (!targets.length) {
    const v = tl.tracks.find(x => x.type === 'video')
    targets = (v?.clips || []).filter(c => c.start < t - 0.05 && t < c.start + c.duration - 0.05).map(c => c.id)
  }
  if (!targets.length) return st.notify('播放头下没有可分割的片段')
  const newIds: string[] = []
  st.edit(tl2 => {
    for (const id of targets) {
      const f = findClip(tl2, id)!
      const c = f.clip as any
      const d1 = t - c.start
      const b = structuredClone(c)
      b.id = uid(id.replace(/\d.*$/, '') || 'c')
      newIds.push(b.id)
      b.start = +t.toFixed(3)
      b.duration = +(c.duration - d1).toFixed(3)
      if (f.track.type === 'video' && !c.freeze) {
        const sp = speedOf(c)
        const mid = +(c.in + d1 * sp).toFixed(3)
        b.in = mid
        c.out = mid
        b.transition = { type: 'none', duration: 0.4 }
      }
      if (f.track.type === 'audio') b.in = +(c.in + d1).toFixed(3)
      c.duration = +d1.toFixed(3)
      f.track.clips.splice(f.track.clips.indexOf(c) + 1, 0, b)
    }
  })
  useStore.setState({ selected: newIds })
}

export function deleteSelected(ripple: boolean) {
  const st = useStore.getState()
  const ids = st.selected
  if (!ids.length) return
  st.edit(tl => {
    for (const tr of tl.tracks) {
      const gone = tr.clips.filter(c => ids.includes(c.id))
      tr.clips = tr.clips.filter(c => !ids.includes(c.id))
      if (ripple && tr.type === 'video') {
        for (const g of gone.sort((a, b) => b.start - a.start)) {
          for (const c of tr.clips) if (c.start >= g.start + g.duration - 0.01) c.start = +(c.start - g.duration).toFixed(3)
        }
      }
    }
  })
  useStore.setState({ selected: [] })
}

export function duplicateSelected() {
  const st = useStore.getState()
  const ids = st.selected
  const out: string[] = []
  st.edit(tl => {
    for (const id of ids) {
      const f = findClip(tl, id)
      if (!f) continue
      const b = structuredClone(f.clip)
      b.id = uid('d')
      const end = Math.max(...f.track.clips.map(c => c.start + c.duration))
      b.start = +(f.track.type === 'video' ? end : f.clip.start + f.clip.duration).toFixed(3)
      f.track.clips.push(b)
      out.push(b.id)
    }
  })
  useStore.setState({ selected: out })
}

export function addText(preset: TextClip['preset'], extra: Partial<TextClip> = {}) {
  const st = useStore.getState()
  const id = uid('t')
  const defaults: Record<string, Partial<TextClip>> = {
    caption: { text: '双击右侧修改文字', fontSize: 72, x: 0.5, y: 0.45, duration: 3 },
    subtitle: { text: '字幕', sub: 'Subtitle', duration: 2.5 },
    heading: { num: '01', text: '段落标题', sub: 'SECTION TITLE', duration: 4.4 },
    word: { text: '品质', sub: 'QUALITY', duration: 1.2 },
    title: { kicker: 'KICKER', text: '主标题', sub: 'MAIN TITLE', extra: '副标题', duration: 5, backdrop: true },
  }
  const trackId = preset === 'subtitle' ? 't2' : 't1'
  st.edit(tl => {
    let tr = tl.tracks.find(t => t.id === trackId) || tl.tracks.find(t => t.type === 'text')
    if (!tr) { tr = { id: trackId, type: 'text', name: '文字', clips: [] }; tl.tracks.push(tr) }
    tr.clips.push({ id, preset, start: +st.time.toFixed(3), duration: 3, text: '', ...defaults[preset], ...extra } as TextClip)
  })
  useStore.setState({ selected: [id] })
}

export function addAssetClip(aid: string, at?: number, trackId?: string, range?: { in: number; out: number }) {
  const st = useStore.getState()
  const p = st.project!
  const a = assetOf(p, aid)
  if (!a || a.status !== 'ready') return st.notify('素材还在处理中')
  const start = +(at ?? st.time).toFixed(3)
  const id = uid(a.kind === 'audio' ? 'au' : 'v')
  st.edit((tl: TL) => {
    let tr = trackId ? tl.tracks.find(t => t.id === trackId) : undefined
    if (a.kind === 'audio') {
      const role = a.origin === 'tts' ? 'voice' : a.origin === 'sfx' ? 'sfx' : 'music'
      if (!tr || tr.type !== 'audio') tr = tl.tracks.find(t => t.type === 'audio' && t.role === role) || tl.tracks.find(t => t.type === 'audio')
      tr!.clips.push({ id, assetId: aid, start, in: 0, duration: +a.duration.toFixed(3), volume: a.suggestedVolume ?? (role === 'music' ? 0.3 : 1), fadeIn: 0.02, fadeOut: role === 'music' ? 2 : 0.05, duck: role === 'music' } as AudioClip)
    } else {
      if (!tr || tr.type !== 'video') tr = tl.tracks.find(t => t.type === 'video')
      const i0 = range?.in ?? 0
      const i1 = range?.out ?? (a.kind === 'image' ? 0.1 : Math.min(a.duration, 5))
      const rms = a.audio?.rmsDb
      tr!.clips.push({
        id, assetId: aid, start, in: i0, out: i1, duration: a.kind === 'image' ? 3 : +(i1 - i0).toFixed(3), freeze: a.kind === 'image',
        filter: { preset: 'cinematic' }, transform: { zoom: 1.07, kenburns: 0.04 }, stabilize: true, smoothSlowmo: true, ambience: true,
        volume: a.hasAudio && rms != null ? Math.min(2, +Math.pow(10, (-36 - rms) / 20).toFixed(3)) : 0,
        transition: { type: 'none', duration: 0.4 },
      } as VideoClip)
    }
  })
  useStore.setState({ selected: [id] })
}

export function useTimelineKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (e.target as HTMLElement)?.isContentEditable) return
      const st = useStore.getState()
      if (!st.project) return
      const fps = st.project.settings.fps
      if (e.code === 'Space') { e.preventDefault(); st.setPlaying(!st.playing) }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? st.redo() : st.undo() }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); st.redo() }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicateSelected() }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); st.save() }
      else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected(e.shiftKey) }
      else if (e.key.toLowerCase() === 's' && !e.ctrlKey) splitAtPlayhead()
      else if (e.key === 'ArrowLeft') { e.preventDefault(); st.setTime(st.time - (e.shiftKey ? 1 : 1 / fps)) }
      else if (e.key === 'ArrowRight') { e.preventDefault(); st.setTime(st.time + (e.shiftKey ? 1 : 1 / fps)) }
      else if (e.key === 'Home') st.setTime(0)
      else if (e.key === 'End') st.setTime(st.project.timeline.duration)
      else if (e.key === 'Escape') st.select(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
