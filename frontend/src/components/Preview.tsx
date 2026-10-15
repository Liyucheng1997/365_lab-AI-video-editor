import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { assetUrl, fmt, textPng } from '../api'
import { assetOf, speedOf, useStore } from '../store'
import type { Asset, AudioClip, Project, TextClip, Track, VideoClip } from '../types'

const ease = (x: number) => { x = Math.min(Math.max(x, 0), 1); return 1 - (1 - x) ** 3 }
const c01 = (x: number) => Math.min(Math.max(x, 0), 1)
const smooth = (x: number) => { x = c01(x); return x * x * (3 - 2 * x) }

const PRESETS: Record<string, any> = {
  none: { exposure: 1, contrast: 0, saturation: 1, temperature: 0, sharpen: 0 },
  cinematic: { exposure: 1.05, contrast: 0.28, saturation: 1.1, temperature: 0, sharpen: 0.45 },
  bright: { exposure: 1.12, contrast: 0.15, saturation: 1.08, temperature: 0.05, sharpen: 0.3 },
  warm: { exposure: 1.05, contrast: 0.22, saturation: 1.05, temperature: 0.35, sharpen: 0.35 },
  cool: { exposure: 1.03, contrast: 0.25, saturation: 1.0, temperature: -0.35, sharpen: 0.35 },
  bw: { exposure: 1.05, contrast: 0.35, saturation: 0, temperature: 0, sharpen: 0.4 },
}
export function filterOf(c: VideoClip) {
  const f = c.filter || { preset: 'cinematic' }
  const base = PRESETS[f.preset] || PRESETS.cinematic
  const o: any = { ...base }
  for (const k of Object.keys(f)) if (k !== 'preset' && (f as any)[k] != null) o[k] = (f as any)[k]
  o.blur ??= 0; o.brightness ??= 1
  return o
}

interface VInfo { c: VideoClip; a0: number; a1: number; tr: string; trd: number; xin: number }

export function videoInfos(tracks: Track[]): VInfo[] {
  const out: VInfo[] = []
  for (const t of tracks) {
    if (t.type !== 'video' || t.hidden) continue
    const cl = [...t.clips].sort((a, b) => a.start - b.start) as VideoClip[]
    cl.forEach((c, i) => {
      const n = cl[i + 1]
      const tr = c.transition?.type || 'none', trd = c.transition?.duration ?? 0.4
      const xin = tr === 'fade' ? trd / 2 : 0
      const touching = n && Math.abs(n.start - (c.start + c.duration)) < 0.05
      const xout = touching && n.transition?.type === 'fade' ? (n.transition.duration ?? 0.4) / 2 : 0
      out.push({ c, a0: c.start - xin, a1: c.start + c.duration + xout, tr, trd, xin })
    })
  }
  return out
}

export default function Preview() {
  const project = useStore(s => s.project)!
  const time = useStore(s => s.time)
  const playing = useStore(s => s.playing)
  const exactFrame = useStore(s => s.exactFrame)
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 300, h: 530 })
  const { width: W, height: H } = project.settings
  const total = project.timeline.duration

  useLayoutEffect(() => {
    const el = box.current!
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect()
      const s = Math.min(r.width / W, r.height / H)
      setSize({ w: Math.floor(W * s), h: Math.floor(H * s) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [W, H])

  // 播放时钟
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const t0 = useStore.getState().time >= total - 0.05 ? 0 : useStore.getState().time
    const s0 = performance.now()
    const tick = () => {
      const t = t0 + (performance.now() - s0) / 1000
      if (t >= total) { useStore.getState().setTime(total); useStore.getState().setPlaying(false); return }
      useStore.getState().setTime(t)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, total])

  const infos = useMemo(() => videoInfos(project.timeline.tracks), [project.timeline])
  const k = size.w / W
  const t = time

  const active = infos.filter(v => v.a0 <= t && t < v.a1)
  const mounted = infos.filter(v => v.a0 - 2 <= t && t < v.a1 + 0.3)
  const op = new Map<string, number>()
  if (active.length >= 2) {
    const [a, b] = active.slice(-2)
    if (b.tr === 'fade' && b.xin > 0) { op.set(a.c.id, 1); op.set(b.c.id, smooth((t - b.a0) / Math.max(1e-3, a.a1 - b.a0))) }
    else op.set(b.c.id, 1)
  } else if (active.length) op.set(active[0].c.id, 1)
  // 黑/白场
  let dip = 0, dipCol = 'black'
  for (const v of infos) {
    if (v.tr !== 'black' && v.tr !== 'white') continue
    const h = v.trd / 2
    if (t >= v.c.start - h && t < v.c.start + h) {
      dip = Math.max(dip, 1 - smooth(Math.abs(t - v.c.start) / h)); dipCol = v.tr
    }
  }
  const look = project.settings.look
  let fade = 0
  if (look.fadeInOut && total > 0) {
    if (t < 0.3) fade = 1 - t / 0.3
    if (t > total - 1.4) fade = Math.max(fade, 1 - c01((total - t) / 1.4))
  }
  const textTracks = project.timeline.tracks.filter(tr => tr.type === 'text' && !tr.hidden)
  const audioTracks = project.timeline.tracks.filter(tr => tr.type === 'audio')
  const voiceOn = audioTracks.some(tr => tr.role === 'voice' && !tr.muted && tr.clips.some(c => c.start <= t && t < c.start + c.duration))

  return (
    <div className="preview">
      <div className="stage-wrap" ref={box}>
        <div className="stage" style={{ width: size.w, height: size.h }}>
          {mounted.map(v => (
            <VideoLayer key={v.c.id} v={v} project={project} t={t} playing={playing} k={k} size={size}
              opacity={op.get(v.c.id) ?? 0} muted={project.timeline.tracks.find(x => x.clips.includes(v.c))?.muted} />
          ))}
          {(look.vignette || look.gradients) && <div className="look" style={{
            background: [look.gradients && 'linear-gradient(to top, rgba(0,0,0,.55) 0%, rgba(0,0,0,0) 33%)',
              look.gradients && 'linear-gradient(to bottom, rgba(0,0,0,.28) 0%, rgba(0,0,0,0) 29%)',
              look.vignette && 'radial-gradient(ellipse 75% 70% at 50% 47%, rgba(0,0,0,0) 55%, rgba(0,0,0,.32) 100%)'].filter(Boolean).join(','),
          }} />}
          {textTracks.flatMap(tr => (tr.clips as TextClip[]).filter(c => c.start - 1 <= t && t < c.start + c.duration).map(c => (
            <TextLayer key={c.id} c={c} t={t} k={k} W={W} H={H} total={total} />
          )))}
          {dip > 0 && <div className="cover" style={{ background: dipCol, opacity: dip }} />}
          {fade > 0 && <div className="cover" style={{ background: 'black', opacity: fade }} />}
          {exactFrame && <img className="cover" src={exactFrame} />}
          {!infos.length && !textTracks.some(x => x.clips.length) && <div className="stage-empty">导入素材，用 AI 生成剪辑，<br />或把素材拖到下方时间线</div>}
        </div>
      </div>
      {audioTracks.flatMap(tr => (tr.clips as AudioClip[]).filter(c => c.start - 1.5 <= t && t < c.start + c.duration + 0.2).map(c => (
        <AudioLayer key={c.id} c={c} t={t} playing={playing} project={project}
          gain={tr.muted ? 0 : tr.role === 'music' && c.duck !== false && voiceOn ? 1 - (c.duckAmount ?? 0.55) : 1} />
      )))}
    </div>
  )
}

function VideoLayer({ v, project, t, playing, k, size, opacity, muted }: {
  v: VInfo; project: Project; t: number; playing: boolean; k: number; size: { w: number; h: number }; opacity: number; muted?: boolean
}) {
  const ref = useRef<HTMLVideoElement>(null)
  const c = v.c
  const a = assetOf(project, c.assetId) as Asset | undefined
  const speed = speedOf(c)
  const activeNow = v.a0 <= t && t < v.a1
  const desired = Math.max(0, Math.min((a?.duration ?? 1e9) - 0.04, c.freeze ? c.in : c.in + (t - c.start) * speed))

  useEffect(() => {
    const el = ref.current
    if (!el || a?.kind !== 'video') return
    const vol = Math.min(1, Math.max(0, c.volume ?? 0))
    el.muted = !!muted || vol <= 0 || !playing
    el.volume = vol
    if (!activeNow) {
      if (!el.paused) el.pause()
      const pre = Math.max(0, c.in - Math.max(0, c.start - v.a0) * speed)
      if (Math.abs(el.currentTime - pre) > 0.1 && el.readyState >= 1) el.currentTime = pre
      return
    }
    if (playing && !c.freeze) {
      el.playbackRate = Math.min(16, Math.max(0.0625, speed))
      if (el.paused) el.play().catch(() => {})
      if (Math.abs(el.currentTime - desired) > 0.3) el.currentTime = desired
    } else {
      if (!el.paused) el.pause()
      if (Math.abs(el.currentTime - desired) > 0.02) el.currentTime = desired
    }
  })

  if (!a) return null
  const f = filterOf(c)
  const tf = c.transform || {}
  const u = c01((t - v.a0) / Math.max(1e-3, v.a1 - v.a0))
  const kb = tf.kenburns ?? 0.045
  const z = (tf.zoom ?? 1.07) * (1 + (kb > 0 ? kb * u : -kb * (1 - u)))
  let flash = 1
  if (c.transition?.type === 'flash') {
    const d = Math.max(0.05, c.transition.duration)
    if (t >= c.start && t < c.start + d) flash = 1 + 0.35 * (1 - (t - c.start) / d)
  }
  const temp = f.temperature || 0
  const filter = [
    `brightness(${(f.exposure * f.brightness * flash).toFixed(3)})`,
    `contrast(${(1 + f.contrast * 0.45).toFixed(3)})`,
    `saturate(${f.saturation.toFixed(3)})`,
    temp > 0 ? `sepia(${(temp * 0.35).toFixed(3)})` : temp < 0 ? `hue-rotate(${(temp * 14).toFixed(1)}deg)` : '',
    f.blur > 0.2 ? `blur(${(f.blur * k).toFixed(1)}px)` : '',
  ].join(' ')
  const rot = ((tf.rotate || 0) % 360 + 360) % 360
  const side = rot === 90 || rot === 270
  const style: React.CSSProperties = {
    opacity, filter,
    width: side ? size.h : size.w, height: side ? size.w : size.h,
    left: side ? (size.w - size.h) / 2 : 0, top: side ? (size.h - size.w) / 2 : 0,
    transform: `translate(${(tf.x || 0) * k * (1080 / project.settings.width)}px, ${(tf.y || 0) * k * (1080 / project.settings.width)}px) scale(${z}) rotate(${rot}deg)`,
  }
  if (a.kind === 'image') return <img className="vlayer" src={assetUrl(project.id, a.id, 'proxy')} style={style} />
  return <video ref={ref} className="vlayer" src={assetUrl(project.id, a.id, 'proxy')} preload="auto" playsInline style={style} />
}

function TextLayer({ c, t, k, W, H, total }: { c: TextClip; t: number; k: number; W: number; H: number; total: number }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => { let ok = true; textPng(c, W, H).then(u => ok && setUrl(u)); return () => { ok = false } },
    [c.preset, c.text, c.sub, c.kicker, c.extra, c.num, c.color, c.accent, c.scale, c.dx, c.dy, c.x, c.y, c.fontSize, c.font, c.box, W, H])
  if (t < c.start) return null
  const u = t - c.start, tail = c.start + c.duration - t
  let al = 1, ty = 0, sc = 1, clip = '', back: React.ReactNode = null
  const kk = k * (W / 1080)
  const bd = c.backdrop !== false
  if (c.preset === 'subtitle') { al = c01(u / 0.12) * c01(tail / 0.12); ty = 8 * (1 - ease(u / 0.25)) }
  else if (c.preset === 'heading') {
    const inn = ease(u / 0.7); al = inn * c01(tail / 0.45); ty = -18 * (1 - inn)
    const wipe = ease(u / 0.9) * 1.05
    clip = `inset(0 ${Math.max(0, 100 - ((72 + wipe * 760) / 1080) * 100)}% 0 0)`
    if (bd) back = <div className="cover" style={{ opacity: al * 0.5, background: 'radial-gradient(ellipse 110% 34% at 0% 0%, black 30%, transparent 100%)' }} />
  } else if (c.preset === 'word') {
    al = ease(u / 0.18) * c01(tail / 0.15); sc = 1.1 - 0.1 * ease(u / 0.5) + 0.02 * u
    if (bd) back = <div className="cover" style={{ background: 'black', opacity: 0.28 * al }} />
  } else if (c.preset === 'title') {
    const out = c.start + c.duration < total - 0.05 ? c01(tail / 0.6) : 1
    al = ease(u / 0.9) * out; ty = 22 * (1 - ease(u / 1.0))
    if (bd) {
      const yc = (833 + (c.dy || 0) - 43) * kk
      back = <div className="band" style={{ top: yc - 330 * kk, height: 660 * kk, opacity: ease(u / 0.8) * out, backdropFilter: `blur(${7 * k}px) brightness(0.5)` }} />
    }
  } else { al = c01(u / 0.3) * c01(tail / 0.3); ty = 12 * (1 - ease(u / 0.4)) }
  const origin = c.preset === 'word' ? `50% ${((940 + (c.dy || 0)) / 1920) * 100}%` : '50% 50%'
  return <>
    {back}
    {url && <img className="cover tlayer" src={url} style={{ opacity: al, transform: `translateY(${ty * kk}px) scale(${sc})`, transformOrigin: origin, clipPath: clip || undefined }} />}
  </>
}

function AudioLayer({ c, t, playing, project, gain }: { c: AudioClip; t: number; playing: boolean; project: Project; gain: number }) {
  const ref = useRef<HTMLAudioElement>(null)
  const a = assetOf(project, c.assetId)
  const active = t >= c.start && t < c.start + c.duration
  const desired = c.in + (t - c.start)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const u = t - c.start, tail = c.start + c.duration - t
    let f = 1
    if (c.fadeIn) f *= c01(u / c.fadeIn)
    if (c.fadeOut) f *= c01(tail / c.fadeOut)
    el.volume = Math.min(1, Math.max(0, c.volume * gain * f))
    if (!active || !playing) {
      if (!el.paused) el.pause()
      const want = active ? desired : c.in
      if (Math.abs(el.currentTime - want) > 0.05 && el.readyState >= 1) el.currentTime = want
      return
    }
    if (el.paused) { el.currentTime = desired; el.play().catch(() => {}) }
    else if (Math.abs(el.currentTime - desired) > 0.25) el.currentTime = desired
  })
  if (!a) return null
  return <audio ref={ref} src={assetUrl(project.id, a.id, 'proxy')} preload="auto" />
}

export function PlayerBar() {
  const time = useStore(s => s.time)
  const playing = useStore(s => s.playing)
  const total = useStore(s => s.project?.timeline.duration || 0)
  const exact = useStore(s => s.exactFrame)
  const [busy, setBusy] = useState(false)
  const grab = async () => {
    const st = useStore.getState()
    const p = st.project!
    setBusy(true)
    try {
      const r = await fetch(`/api/projects/${p.id}/frame`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ t: st.time, timeline: p.timeline, quality: 'high' }),
      })
      if (!r.ok) throw new Error(await r.text())
      st.setPlaying(false)
      st.setExactFrame(URL.createObjectURL(await r.blob()))
    } catch (e: any) { st.notify('渲染失败：' + e.message, 'error') }
    setBusy(false)
  }
  return (
    <div className="playerbar">
      <span className="tc">{fmt(time)} <i>/ {fmt(total)}</i></span>
      <div className="pb-mid">
        <button className="icon" title="回到开头 (Home)" onClick={() => useStore.getState().setTime(0)}>⏮</button>
        <button className="icon play" title="播放/暂停 (空格)" onClick={() => useStore.getState().setPlaying(!playing)}>{playing ? '⏸' : '▶'}</button>
        <button className="icon" title="到结尾 (End)" onClick={() => useStore.getState().setTime(total)}>⏭</button>
      </div>
      <button className={'ghost sm' + (exact ? ' on' : '')} disabled={busy} onClick={grab}
        title="用导出时同一套渲染管线（含防抖、调色、慢放补帧）渲染当前帧">{busy ? '渲染中…' : exact ? '✓ 成片效果' : '成片效果预览'}</button>
    </div>
  )
}
