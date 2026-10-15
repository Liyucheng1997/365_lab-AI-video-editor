import { useState } from 'react'
import { api, assetUrl, fmt } from '../api'
import { assetOf, findClip, speedOf, uid, useStore } from '../store'
import type { AudioClip, Clip, TextClip, Track, VideoClip } from '../types'

const FILTER_NAMES: Record<string, string> = { none: '原片', cinematic: '电影感', bright: '明亮', warm: '暖调', cool: '冷调', bw: '黑白' }

export default function Inspector() {
  const project = useStore(s => s.project)!
  const selected = useStore(s => s.selected)
  const f = selected.length === 1 ? findClip(project.timeline, selected[0]) : null
  if (selected.length > 1) return <div className="inspector"><h3>已选 {selected.length} 个片段</h3><BatchPanel ids={selected} /></div>
  if (!f) return <div className="inspector"><ProjectPanel /></div>
  return (
    <div className="inspector" key={f.clip.id}>
      {f.track.type === 'video' && <VideoPanel c={f.clip as VideoClip} />}
      {f.track.type === 'text' && <TextPanel c={f.clip as TextClip} />}
      {f.track.type === 'audio' && <AudioPanel c={f.clip as AudioClip} track={f.track} />}
    </div>
  )
}

// ---------------------------------------------------------------- 通用控件
function upd<T extends Clip>(id: string, fn: (c: T) => void, record = true) {
  useStore.getState().edit(tl => { const f = findClip(tl, id); if (f) fn(f.clip as T) }, record)
}

/** 拖动滑块时只在开始记录一次撤销点 */
function Slider({ label, value, min, max, step = 0.01, onChange, fmtv }: {
  label: string; value: number; min: number; max: number; step?: number; onChange: (v: number, rec: boolean) => void; fmtv?: (v: number) => string
}) {
  const [drag, setDrag] = useState(false)
  return (
    <div className="field slider">
      <label>{label}</label>
      <input type="range" min={min} max={max} step={step} value={value}
        onPointerDown={() => { setDrag(true); useStore.getState().checkpoint() }}
        onPointerUp={() => setDrag(false)}
        onChange={e => onChange(+e.target.value, !drag)} />
      <input className="num" type="number" step={step} value={+value.toFixed(3)} onChange={e => onChange(+e.target.value, true)} />
      {fmtv && <span className="unit">{fmtv(value)}</span>}
    </div>
  )
}

function Num({ label, value, onChange, step = 0.1, min, suffix }: { label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; suffix?: string }) {
  const [v, setV] = useState<string | null>(null)
  return (
    <div className="field">
      <label>{label}</label>
      <input className="num wide" type="number" step={step} min={min} value={v ?? +value.toFixed(3)}
        onChange={e => setV(e.target.value)}
        onBlur={() => { if (v != null && v !== '' && isFinite(+v)) onChange(+v); setV(null) }}
        onKeyDown={e => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} />
      {suffix && <span className="unit">{suffix}</span>}
    </div>
  )
}

function Txt({ label, value, onChange, area }: { label: string; value: string; onChange: (v: string) => void; area?: boolean }) {
  const [v, setV] = useState<string | null>(null)
  const commit = () => { if (v != null && v !== value) onChange(v); setV(null) }
  return (
    <div className="field col">
      <label>{label}</label>
      {area
        ? <textarea rows={2} value={v ?? value} onChange={e => setV(e.target.value)} onBlur={commit} />
        : <input value={v ?? value} onChange={e => setV(e.target.value)} onBlur={commit} onKeyDown={e => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} />}
    </div>
  )
}

function Check({ label, value, onChange, hint }: { label: string; value: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return <label className="chk field" title={hint}><input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} />{label}</label>
}

function Timing({ c }: { c: Clip }) {
  return (
    <div className="grid2">
      <Num label="开始" value={c.start} suffix="秒" onChange={v => upd(c.id, x => { x.start = Math.max(0, v) })} />
      <Num label="时长" value={c.duration} suffix="秒" onChange={v => upd(c.id, (x: any) => {
        x.duration = Math.max(0.1, v)
        if ('out' in x && !x.freeze) x.out = +(x.in + x.duration * speedOf({ ...c, duration: c.duration } as any)).toFixed(3)
      })} />
    </div>
  )
}

// ---------------------------------------------------------------- 视频
function VideoPanel({ c }: { c: VideoClip }) {
  const project = useStore(s => s.project)!
  const a = assetOf(project, c.assetId)
  const f = c.filter || { preset: 'cinematic' }
  const presets = useStore(s => s.config?.filters) || {}
  const base = presets[f.preset] || {}
  const val = (k: keyof typeof f, d = 0) => ((f as any)[k] ?? base[k] ?? d) as number
  const setF = (k: string, v: any, rec = true) => upd<VideoClip>(c.id, x => { x.filter = { ...(x.filter || { preset: 'cinematic' }), [k]: v } }, rec)
  const tf = c.transform || {}
  const setT = (k: string, v: any, rec = true) => upd<VideoClip>(c.id, x => { x.transform = { ...(x.transform || {}), [k]: v } }, rec)
  const sp = speedOf(c)
  return <>
    <h3>视频片段</h3>
    <div className="asset-line">
      {a?.thumb && <img src={assetUrl(project.id, a.id, 'thumb')} />}
      <div><b>{a?.name}</b><div className="muted small">{a ? `${a.width}×${a.height} · ${fmt(a.duration)}${a.hdr ? ' · HDR' : ''}` : '素材丢失'}</div>
        {c.note && <div className="small note">🎬 {c.note}</div>}</div>
    </div>
    <section>
      <h4>时间与变速</h4>
      <Timing c={c} />
      {!c.freeze && <div className="grid2">
        <Num label="素材入点" value={c.in} suffix="秒" onChange={v => upd<VideoClip>(c.id, x => { const d = x.out - x.in; x.in = Math.max(0, v); x.out = Math.min(a?.duration ?? 1e9, x.in + d) })} />
        <Num label="素材出点" value={c.out} suffix="秒" onChange={v => upd<VideoClip>(c.id, x => { x.out = Math.min(a?.duration ?? 1e9, Math.max(x.in + 0.1, v)) })} />
      </div>}
      {!c.freeze && <Slider label="速度" value={sp} min={0.25} max={3} step={0.05} fmtv={v => v.toFixed(2) + 'x'}
        onChange={(v, rec) => upd<VideoClip>(c.id, x => { x.duration = +((x.out - x.in) / Math.max(0.05, v)).toFixed(3) }, rec)} />}
      <Check label="定格画面（使用入点那一帧）" value={!!c.freeze} onChange={v => upd<VideoClip>(c.id, x => { x.freeze = v; if (!v && x.out - x.in < 0.3) x.out = Math.min(a?.duration ?? 1e9, x.in + x.duration) })} />
      {sp < 0.97 && !c.freeze && <Check label="慢放补帧（光流插帧，更顺滑）" value={c.smoothSlowmo !== false} onChange={v => upd<VideoClip>(c.id, x => { x.smoothSlowmo = v })} />}
    </section>
    <section>
      <h4>转场（进入本片段）</h4>
      <div className="chips">
        {(['none', 'fade', 'flash', 'black', 'white'] as const).map(t => (
          <button key={t} className={'chip' + ((c.transition?.type || 'none') === t ? ' on' : '')}
            onClick={() => upd<VideoClip>(c.id, x => { x.transition = { type: t, duration: t === 'flash' ? 0.2 : x.transition?.duration && x.transition.type !== 'flash' ? x.transition.duration : 0.4 } })}>
            {({ none: '无', fade: '叠化', flash: '闪白', black: '黑场', white: '白场' } as any)[t]}
          </button>))}
      </div>
      {c.transition && c.transition.type !== 'none' && <Slider label="转场时长" value={c.transition.duration} min={0.1} max={2} step={0.05} fmtv={v => v.toFixed(2) + 's'}
        onChange={(v, rec) => upd<VideoClip>(c.id, x => { x.transition = { ...x.transition!, duration: v } }, rec)} />}
    </section>
    <section>
      <h4>调色滤镜</h4>
      <div className="chips">
        {Object.keys(FILTER_NAMES).map(k => (
          <button key={k} className={'chip' + (f.preset === k ? ' on' : '')} onClick={() => upd<VideoClip>(c.id, x => {
            const keep = x.filter ? { blur: x.filter.blur, brightness: x.filter.brightness } : {}
            x.filter = { preset: k, ...keep }
          })}>{FILTER_NAMES[k]}</button>))}
      </div>
      <Slider label="曝光" value={val('exposure', 1)} min={0.5} max={1.6} onChange={(v, r) => setF('exposure', v, r)} />
      <Slider label="对比" value={val('contrast')} min={0} max={0.8} onChange={(v, r) => setF('contrast', v, r)} />
      <Slider label="饱和度" value={val('saturation', 1)} min={0} max={2} onChange={(v, r) => setF('saturation', v, r)} />
      <Slider label="色温" value={val('temperature')} min={-1} max={1} onChange={(v, r) => setF('temperature', v, r)} />
      <Slider label="锐化" value={val('sharpen')} min={0} max={1.5} onChange={(v, r) => setF('sharpen', v, r)} />
      <Slider label="亮度" value={val('brightness', 1)} min={0} max={1.5} onChange={(v, r) => setF('brightness', v, r)} />
      <Slider label="模糊" value={val('blur')} min={0} max={40} step={0.5} onChange={(v, r) => setF('blur', v, r)} />
    </section>
    <section>
      <h4>画面</h4>
      <Slider label="放大" value={tf.zoom ?? 1.07} min={1} max={2} onChange={(v, r) => setT('zoom', v, r)} />
      <Slider label="推拉运镜" value={tf.kenburns ?? 0.045} min={-0.2} max={0.2} step={0.005} fmtv={v => v > 0 ? '推近' : v < 0 ? '拉远' : '静止'} onChange={(v, r) => setT('kenburns', v, r)} />
      <Slider label="水平位置" value={tf.x ?? 0} min={-300} max={300} step={1} onChange={(v, r) => setT('x', v, r)} />
      <Slider label="垂直位置" value={tf.y ?? 0} min={-500} max={500} step={1} onChange={(v, r) => setT('y', v, r)} />
      <div className="field"><label>旋转</label>
        <select value={tf.rotate || 0} onChange={e => setT('rotate', +e.target.value)}>
          <option value={0}>0°</option><option value={90}>顺时针 90°</option><option value={270}>逆时针 90°</option><option value={180}>180°</option>
        </select></div>
      <Check label="防抖（导出时生效）" hint="平滑手持抖动，保留运镜；编辑器预览里看不到，可点「成片效果预览」查看" value={c.stabilize !== false} onChange={v => upd<VideoClip>(c.id, x => { x.stabilize = v })} />
    </section>
    <section>
      <h4>原声</h4>
      <Slider label="音量" value={c.volume ?? 0} min={0} max={2} onChange={(v, r) => upd<VideoClip>(c.id, x => { x.volume = v }, r)} fmtv={v => Math.round(v * 100) + '%'} />
      <Check label="只保留环境声（滤掉低频轰鸣和高频噪声）" value={!!c.ambience} onChange={v => upd<VideoClip>(c.id, x => { x.ambience = v })} />
    </section>
    <ApplyAll c={c} />
  </>
}

function ApplyAll({ c }: { c: VideoClip }) {
  const apply = (what: 'filter' | 'transition') => {
    useStore.getState().edit(tl => {
      for (const t of tl.tracks) if (t.type === 'video') for (const x of t.clips as VideoClip[]) {
        if (x.id === c.id || x.freeze) continue
        if (what === 'filter') x.filter = structuredClone(c.filter)
        else if ((x.transition?.type || 'none') !== 'none') x.transition = structuredClone(c.transition)
      }
    })
    useStore.getState().notify('已应用到其他视频片段')
  }
  return <section className="row-btns">
    <button className="ghost sm" onClick={() => apply('filter')}>调色应用到全部</button>
    <button className="ghost sm" onClick={() => apply('transition')}>转场应用到全部</button>
  </section>
}

// ---------------------------------------------------------------- 文字
const PRESET_NAMES: Record<string, string> = { subtitle: '字幕', heading: '段落标题', word: '关键词大字', title: '标题卡', caption: '自由文字' }

function TextPanel({ c }: { c: TextClip }) {
  const set = (k: keyof TextClip, v: any, rec = true) => upd<TextClip>(c.id, x => { (x as any)[k] = v }, rec)
  return <>
    <h3>{PRESET_NAMES[c.preset]}</h3>
    <section>
      <div className="field"><label>样式</label>
        <select value={c.preset} onChange={e => set('preset', e.target.value)}>
          {Object.entries(PRESET_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select></div>
      {c.preset === 'title' && <Txt label="顶部小字" value={c.kicker || ''} onChange={v => set('kicker', v)} />}
      {c.preset === 'heading' && <Txt label="编号" value={c.num || ''} onChange={v => set('num', v)} />}
      <Txt label={c.preset === 'caption' ? '文字（可换行）' : '主文字'} value={c.text || ''} area={c.preset === 'caption'} onChange={v => set('text', v)} />
      {c.preset !== 'caption' && <Txt label={c.preset === 'subtitle' ? '第二行（英文）' : '副文字（英文）'} value={c.sub || ''} onChange={v => set('sub', v)} />}
      {c.preset === 'title' && <Txt label="补充说明（可多行）" area value={c.extra || ''} onChange={v => set('extra', v)} />}
    </section>
    <section>
      <h4>时间</h4>
      <Timing c={c} />
    </section>
    <section>
      <h4>外观</h4>
      <div className="grid2">
        <div className="field"><label>文字色</label><input type="color" value={c.color || '#ffffff'} onChange={e => set('color', e.target.value)} /></div>
        <div className="field"><label>点缀色</label><input type="color" value={c.accent || (c.preset === 'subtitle' ? '#ece4d4' : '#d4b47a')} onChange={e => set('accent', e.target.value)} /></div>
      </div>
      <Slider label="大小" value={c.scale ?? 1} min={0.4} max={2} onChange={(v, r) => set('scale', v, r)} />
      {c.preset === 'caption' ? <>
        <Slider label="字号" value={c.fontSize ?? 72} min={20} max={240} step={1} onChange={(v, r) => set('fontSize', v, r)} />
        <Slider label="水平位置" value={c.x ?? 0.5} min={0} max={1} onChange={(v, r) => set('x', v, r)} />
        <Slider label="垂直位置" value={c.y ?? 0.5} min={0} max={1} onChange={(v, r) => set('y', v, r)} />
        <div className="field"><label>字体</label>
          <select value={c.font || 'zh_bold'} onChange={e => set('font', e.target.value)}>
            <option value="zh_bold">黑体·粗</option><option value="zh_medium">黑体·中</option><option value="serif">宋体·特粗</option>
          </select></div>
        <Check label="背景框" value={!!c.box} onChange={v => set('box', v)} />
      </> : <>
        <Slider label="水平偏移" value={c.dx ?? 0} min={-500} max={500} step={1} onChange={(v, r) => set('dx', v, r)} />
        <Slider label="垂直偏移" value={c.dy ?? 0} min={-900} max={900} step={1} onChange={(v, r) => set('dy', v, r)} />
      </>}
      {['heading', 'word', 'title'].includes(c.preset) && <Check label="衬底（压暗/虚化背景，让文字更清楚）" value={c.backdrop !== false} onChange={v => set('backdrop', v)} />}
    </section>
    {c.preset === 'subtitle' && <SubtitleAll c={c} />}
  </>
}

function SubtitleAll({ c }: { c: TextClip }) {
  const apply = () => {
    useStore.getState().edit(tl => {
      for (const t of tl.tracks) for (const x of t.clips as TextClip[]) if (x.preset === 'subtitle' && x.id !== c.id) {
        x.color = c.color; x.accent = c.accent; x.scale = c.scale; x.dx = c.dx; x.dy = c.dy
      }
    })
    useStore.getState().notify('已应用到全部字幕')
  }
  const clearEn = () => useStore.getState().edit(tl => {
    for (const t of tl.tracks) for (const x of t.clips as TextClip[]) if (x.preset === 'subtitle') x.sub = ''
  })
  return <section className="row-btns">
    <button className="ghost sm" onClick={apply}>样式应用到全部字幕</button>
    <button className="ghost sm" onClick={clearEn}>去掉全部英文行</button>
  </section>
}

// ---------------------------------------------------------------- 音频
function AudioPanel({ c, track }: { c: AudioClip; track: Track }) {
  const project = useStore(s => s.project)!
  const a = assetOf(project, c.assetId)
  const [busy, setBusy] = useState(false)
  const [lines, setLines] = useState(a?.lines ? structuredClone(a.lines) : null)
  const set = (k: keyof AudioClip, v: any, rec = true) => upd<AudioClip>(c.id, x => { (x as any)[k] = v }, rec)

  const revoice = async () => {
    if (!lines) return
    setBusy(true)
    try {
      const na = await api.tts(project.id, lines, a?.name)
      const st = useStore.getState()
      st.project && useStore.setState({ project: { ...st.project, assets: [...st.project.assets, na] } })
      // 替换配音并按新的逐句时间重排这一段的字幕
      st.edit(tl => {
        const f = findClip(tl, c.id)!
        const ac = f.clip as AudioClip
        ac.assetId = na.id; ac.in = 0; ac.duration = +na.duration.toFixed(3)
        if (na.suggestedVolume) ac.volume = na.suggestedVolume
        const subTrack = tl.tracks.find(t => t.clips.some(x => (x as TextClip).preset === 'subtitle' && x.sectionId && x.sectionId === c.sectionId))
        if (subTrack && c.sectionId) {
          const old = subTrack.clips.filter(x => x.sectionId === c.sectionId) as TextClip[]
          const style = old[0] || {}
          subTrack.clips = subTrack.clips.filter(x => x.sectionId !== c.sectionId)
          const lang = st.project!.brief.subtitleLang
          const sp: [number, number][] = na.spans
          lines.forEach((l, k) => {
            const t0 = ac.start + sp[k][0] - 0.08
            const t1 = ac.start + (k + 1 < sp.length ? sp[k + 1][0] - 0.1 : sp[k][1] + 0.45)
            subTrack.clips.push({ ...style, id: uid('s'), preset: 'subtitle', start: +t0.toFixed(3), duration: +(t1 - t0).toFixed(3),
              text: lang === 'en' ? l.en : l.zh, sub: lang === 'zh+en' ? l.en : '', sectionId: c.sectionId } as TextClip)
          })
        }
      })
      st.notify('已重新配音，并同步更新了这一段的字幕')
    } catch (e: any) { useStore.getState().notify('配音失败：' + e.message, 'error') }
    setBusy(false)
  }

  return <>
    <h3>{({ voice: '配音', music: '背景音乐', sfx: '音效' } as any)[track.role || 'sfx']}</h3>
    <div className="muted small">{a?.name} · 素材 {fmt(a?.duration || 0)}</div>
    <section>
      <Slider label="音量" value={c.volume} min={0} max={3} onChange={(v, r) => set('volume', v, r)} fmtv={v => Math.round(v * 100) + '%'} />
      <Slider label="淡入" value={c.fadeIn ?? 0} min={0} max={5} step={0.05} onChange={(v, r) => set('fadeIn', v, r)} fmtv={v => v.toFixed(1) + 's'} />
      <Slider label="淡出" value={c.fadeOut ?? 0} min={0} max={5} step={0.05} onChange={(v, r) => set('fadeOut', v, r)} fmtv={v => v.toFixed(1) + 's'} />
      {track.role === 'music' && <>
        <Check label="有配音时自动压低（闪避）" value={c.duck !== false} onChange={v => set('duck', v)} />
        {c.duck !== false && <Slider label="压低幅度" value={c.duckAmount ?? 0.55} min={0} max={0.95} onChange={(v, r) => set('duckAmount', v, r)} fmtv={v => Math.round(v * 100) + '%'} />}
      </>}
    </section>
    <section>
      <h4>时间</h4>
      <Timing c={c} />
      <Num label="素材起点" value={c.in} suffix="秒" onChange={v => set('in', Math.max(0, v))} />
    </section>
    {lines && <section>
      <h4>台词（改完点重新配音，字幕会一起更新）</h4>
      {lines.map((l, i) => (
        <div key={i} className="line-edit">
          <input value={l.zh} onChange={e => { const n = [...lines]; n[i] = { ...l, zh: e.target.value }; setLines(n) }} />
          <input className="en" value={l.en} onChange={e => { const n = [...lines]; n[i] = { ...l, en: e.target.value }; setLines(n) }} />
          <button className="mini" title="删除这句" onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <div className="row-btns">
        <button className="ghost sm" onClick={() => setLines([...lines, { zh: '', en: '' }])}>＋ 加一句</button>
        <button className="primary sm" disabled={busy} onClick={revoice}>{busy ? '配音中…' : '重新配音'}</button>
      </div>
    </section>}
  </>
}

// ---------------------------------------------------------------- 多选 / 项目
function BatchPanel({ ids }: { ids: string[] }) {
  const shift = (d: number) => useStore.getState().edit(tl => { for (const id of ids) { const f = findClip(tl, id); if (f) f.clip.start = Math.max(0, +(f.clip.start + d).toFixed(3)) } })
  return <section>
    <p className="muted small">Shift+点击可多选。拖动任意一个会一起移动。</p>
    <div className="row-btns">
      <button className="ghost sm" onClick={() => shift(-0.1)}>← 前移 0.1s</button>
      <button className="ghost sm" onClick={() => shift(0.1)}>后移 0.1s →</button>
    </div>
  </section>
}

function ProjectPanel() {
  const project = useStore(s => s.project)!
  const tl = project.timeline
  const look = project.settings.look
  const setLook = (k: keyof typeof look, v: boolean) => useStore.getState().patchProject({ settings: { ...project.settings, look: { ...look, [k]: v } } })
  const count = (type: string) => tl.tracks.filter(t => t.type === type).reduce((n, t) => n + t.clips.length, 0)
  return <>
    <h3>项目</h3>
    <section>
      <Txt label="项目名称" value={project.name} onChange={v => useStore.getState().patchProject({ name: v })} />
      <div className="kv"><span>画幅</span><b>{project.settings.width}×{project.settings.height} · {project.settings.fps}fps</b></div>
      <div className="kv"><span>总时长</span><b>{fmt(tl.duration)}</b></div>
      <div className="kv"><span>镜头 / 文字 / 音频</span><b>{count('video')} / {count('text')} / {count('audio')}</b></div>
    </section>
    <section>
      <h4>整体风格</h4>
      <Check label="暗角" value={look.vignette} onChange={v => setLook('vignette', v)} />
      <Check label="上下渐变压暗（衬托标题和字幕）" value={look.gradients} onChange={v => setLook('gradients', v)} />
      <Check label="片头片尾淡入淡出" value={look.fadeInOut} onChange={v => setLook('fadeInOut', v)} />
    </section>
    <section className="tips">
      <h4>操作提示</h4>
      <ul>
        <li>点选片段后在这里调整属性</li>
        <li><kbd>空格</kbd> 播放/暂停　<kbd>S</kbd> 分割　<kbd>Del</kbd> 删除</li>
        <li><kbd>Shift+Del</kbd> 删除并让后面的镜头前移</li>
        <li><kbd>Ctrl+Z</kbd>/<kbd>Ctrl+Y</kbd> 撤销/重做　<kbd>Ctrl+D</kbd> 复制</li>
        <li><kbd>←</kbd>/<kbd>→</kbd> 逐帧，加 Shift 一次 1 秒</li>
        <li><kbd>Ctrl+滚轮</kbd> 缩放时间线；拖片段两端可裁剪</li>
        <li>防抖、慢放补帧在导出时生效，可点「成片效果预览」查看</li>
      </ul>
    </section>
  </>
}
