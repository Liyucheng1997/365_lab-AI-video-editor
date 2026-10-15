import { useState } from 'react'
import { api, assetUrl } from '../api'
import { useStore } from '../store'
import type { Brief, Line, Script, Section } from '../types'

const KIND: Record<string, string> = { intro: '开场', title: '主标题', section: '段落', ending: '片尾' }

export default function AIPanel() {
  const project = useStore(s => s.project)!
  const jobs = useStore(s => s.jobs)
  const cfg = useStore(s => s.config)
  const sc = project.script
  const [showBrief, setShowBrief] = useState(!sc)
  const [feedback, setFeedback] = useState('')
  const running = (k: string) => jobs.find(j => j.kind === k && j.status === 'running')
  const imported = project.assets.filter(a => a.origin === 'import' || !a.origin)
  const analyzed = imported.filter(a => a.analysis).length
  const busy = running('script') || running('build') || running('analyze')
  const b = project.brief
  const setB = (k: keyof Brief, v: any) => useStore.getState().patchProject({ brief: { ...b, [k]: v } })
  const setSc = (fn: (s: Script) => void) => {
    const n = structuredClone(sc!) as Script
    fn(n)
    if (n.status === 'built') n.status = 'draft'
    useStore.getState().patchProject({ script: n })
  }
  const gen = async (fb?: string) => {
    if (!imported.length) return useStore.getState().notify('先导入素材', 'error')
    try { useStore.getState().trackJob(await api.script(project.id, fb)); setShowBrief(false); setFeedback('') } catch (e: any) { useStore.getState().notify(e.message, 'error') }
  }
  const build = async () => {
    const has = project.timeline.tracks.some(t => t.clips.length)
    if (has && !confirm('执行剪辑会按脚本重新生成整条时间线，覆盖你在时间线上的手动修改（可以 Ctrl+Z 撤销）。继续？')) return
    await useStore.getState().save()
    try { useStore.getState().trackJob(await api.build(project.id)) } catch (e: any) { useStore.getState().notify(e.message, 'error') }
  }
  const restore = (i: number) => {
    const h = sc!.history![i]
    if (!confirm(`恢复到第 ${h.version} 版脚本？`)) return
    useStore.getState().patchProject({ script: { ...h, history: sc!.history!.slice(0, i), status: 'draft' } as Script })
  }
  const totalDur = sc?.sections.reduce((n, s) => n + (s.dur ?? s.shots.reduce((m, x) => m + x.duration, 0)), 0) || 0

  return (
    <div className="panel ai-panel">
      <ol className="steps">
        <li className={imported.length ? 'done' : 'cur'}>导入素材 <i>{imported.length}</i></li>
        <li className={analyzed && analyzed === imported.length ? 'done' : imported.length ? 'cur' : ''}>AI 分析 <i>{analyzed}/{imported.length}</i></li>
        <li className={sc ? 'done' : analyzed ? 'cur' : ''}>剪辑脚本</li>
        <li className={sc?.status === 'built' ? 'done' : sc ? 'cur' : ''}>执行剪辑</li>
      </ol>

      <div className="card">
        <div className="card-head" onClick={() => setShowBrief(!showBrief)}>
          <b>剪辑需求</b><span className="muted small">{b.purpose ? b.purpose.slice(0, 22) : '告诉 AI 这条片子要做什么'}</span><span className="grow" /><span>{showBrief ? '▾' : '▸'}</span>
        </div>
        {showBrief && <div className="brief">
          <label>用途 / 想表达什么<textarea rows={2} value={b.purpose} placeholder="例如：工厂对外宣传片，用来和品牌方谈合作" onChange={e => setB('purpose', e.target.value)} /></label>
          <label>受众<input value={b.audience} placeholder="例如：服装品牌采购" onChange={e => setB('audience', e.target.value)} /></label>
          <label>风格<input value={b.style} onChange={e => setB('style', e.target.value)} /></label>
          <div className="grid2">
            <label>目标时长（秒）<input type="number" value={b.duration} onChange={e => setB('duration', +e.target.value)} /></label>
            <label>字幕<select value={b.subtitleLang} onChange={e => setB('subtitleLang', e.target.value)}>
              <option value="zh+en">中英双语</option><option value="zh">仅中文</option><option value="en">仅英文</option></select></label>
          </div>
          <div className="grid2">
            <label>配音音色<select value={b.voice} onChange={e => setB('voice', e.target.value)}>
              {cfg?.voices.map((v: any) => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
            <label>语速<select value={b.voiceRate} onChange={e => setB('voiceRate', e.target.value)}>
              {['-15%', '-8%', '-4%', '+0%', '+6%', '+12%'].map(r => <option key={r} value={r}>{r === '+0%' ? '正常' : r}</option>)}</select></label>
          </div>
          <label>背景音乐<select value={b.musicAssetId || ''} onChange={e => setB('musicAssetId', e.target.value || null)}>
            <option value="">AI 合成（无版权，卡段落节奏）</option>
            {project.assets.filter(a => a.kind === 'audio' && a.origin === 'import').map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select></label>
          <label>补充说明<textarea rows={2} value={b.notes} placeholder="例如：工厂名叫 XX 服饰；结尾放联系方式；不要提产能数字" onChange={e => setB('notes', e.target.value)} /></label>
        </div>}
      </div>

      {!sc && <button className="primary block" disabled={!!busy || !imported.length} onClick={() => gen()}>
        {running('script') ? running('script')!.message : running('analyze') ? 'AI 正在分析素材…' : `✨ 用 ${cfg?.model || 'Claude'} 生成剪辑脚本`}</button>}

      {sc && <>
        <div className="card script-head">
          <input className="title-in" value={sc.title} onChange={e => setSc(s => { s.title = e.target.value })} />
          <p className="small">{sc.logline}</p>
          <div className="small muted">第 {sc.version || 1} 版 · {sc.sections.length} 段 · 约 {Math.round(totalDur)} 秒 · BGM {sc.musicBpm} BPM
            {sc.status === 'built' && <span className="ok"> · 已生成时间线</span>}</div>
          {sc.assumptions?.length > 0 && <div className="assume">
            <b>⚠ 以下说法是 AI 根据画面推断的，请确认：</b>
            <ul>{sc.assumptions.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </div>}
        </div>
        {sc.sections.map((s, i) => <SectionCard key={s.id + i} s={s} i={i} setSc={setSc} />)}

        <div className="card">
          <b>修改意见</b>
          <textarea rows={3} value={feedback} onChange={e => setFeedback(e.target.value)}
            placeholder="直接告诉 AI 怎么改，例如：开场再短一点；裁床那段换成更稳的镜头；旁白更口语化；加一段质检" />
          <div className="row-btns">
            <button className="ghost sm" disabled={!!busy || !feedback.trim()} onClick={() => gen(feedback)}>{running('script') ? running('script')!.message : '按意见修改脚本'}</button>
            <button className="ghost sm" disabled={!!busy} onClick={() => confirm('完全重新生成一版脚本？') && gen()}>重新生成</button>
            {!!sc.history?.length && <select className="sm" value="" onChange={e => e.target.value !== '' && restore(+e.target.value)}>
              <option value="">历史版本…</option>
              {sc.history.map((h, i) => <option key={i} value={i}>第 {h.version || i + 1} 版{h.feedback ? '：' + h.feedback.slice(0, 12) : ''}</option>)}
            </select>}
          </div>
        </div>
        <button className="primary block" disabled={!!busy} onClick={build}>
          {running('build') ? running('build')!.message : sc.status === 'built' ? '按脚本重新执行剪辑' : '✔ 脚本没问题，执行剪辑'}</button>
        <p className="muted small center">执行剪辑：生成配音 → 卡点排镜头 → 调色、防抖、转场 → 标题和字幕 → 背景音乐和音效</p>
      </>}
    </div>
  )
}

function SectionCard({ s, i, setSc }: { s: Section; i: number; setSc: (fn: (s: Script) => void) => void }) {
  const project = useStore(st => st.project)!
  const [open, setOpen] = useState(false)
  const set = (fn: (x: Section) => void) => setSc(sc => fn(sc.sections[i]))
  const est = s.dur ?? s.shots.reduce((m, x) => m + x.duration, 0)
  const jump = () => { if (s.start != null) useStore.getState().setTime(s.start + 0.01) }
  const lineRows = (k: 'lines' | 'words', rows: Line[]) => <>
    {rows.map((l, j) => (
      <div key={j} className="line-edit">
        <input value={l.zh} onChange={e => set(x => { (x as any)[k][j].zh = e.target.value })} placeholder="中文" />
        <input className="en" value={l.en} onChange={e => set(x => { (x as any)[k][j].en = e.target.value })} placeholder="English" />
        <button className="mini" onClick={() => set(x => { (x as any)[k].splice(j, 1) })}>✕</button>
      </div>))}
    <button className="link small" onClick={() => set(x => { (x as any)[k] = [...((x as any)[k] || []), { zh: '', en: '' }] })}>＋ 添加{k === 'words' ? '关键词' : '一句旁白'}</button>
  </>
  return (
    <div className={'card sec sec-' + s.kind}>
      <div className="card-head" onClick={() => setOpen(!open)}>
        <span className="kind">{KIND[s.kind]}</span>
        <b>{s.heading ? `${s.heading.num} ${s.heading.zh}` : s.card?.text || s.name}</b>
        <span className="grow" />
        <span className="muted small">{s.shots.length} 镜 · {est.toFixed(1)}s</span>
        {s.start != null && <button className="mini" title="跳到时间线上这一段" onClick={e => { e.stopPropagation(); jump() }}>⤓</button>}
        <span>{open ? '▾' : '▸'}</span>
      </div>
      {!open && <div className="sec-preview" onClick={() => setOpen(true)}>
        <div className="thumbs">{s.shots.slice(0, 5).map((x, j) => <img key={j} src={assetUrl(project.id, x.assetId, 'thumb')} />)}</div>
        <div className="small">{s.kind === 'intro' ? s.words?.map(w => w.zh).join(' / ') : s.lines.map(l => l.zh).join('　') || <i className="muted">（无旁白）</i>}</div>
      </div>}
      {open && <div className="sec-body">
        <input className="name-in" value={s.name} onChange={e => set(x => { x.name = e.target.value })} />
        {s.heading && <div className="grid3">
          <input value={s.heading.num} onChange={e => set(x => { x.heading!.num = e.target.value })} title="编号" />
          <input value={s.heading.zh} onChange={e => set(x => { x.heading!.zh = e.target.value })} title="段落标题" />
          <input value={s.heading.en} onChange={e => set(x => { x.heading!.en = e.target.value })} title="英文标题" />
        </div>}
        {s.card && <div className="cardf">
          <input value={s.card.kicker} onChange={e => set(x => { x.card!.kicker = e.target.value })} placeholder="顶部小字" />
          <input value={s.card.text} onChange={e => set(x => { x.card!.text = e.target.value })} placeholder="大标题" />
          <input value={s.card.sub} onChange={e => set(x => { x.card!.sub = e.target.value })} placeholder="英文" />
          <textarea rows={2} value={s.card.extra} onChange={e => set(x => { x.card!.extra = e.target.value })} placeholder="补充（可多行）" />
        </div>}
        {s.kind === 'intro' && <><h5>关键词大字</h5>{lineRows('words', s.words || [])}</>}
        {s.kind !== 'intro' && <><h5>旁白 / 字幕</h5>{lineRows('lines', s.lines)}</>}
        <h5>镜头</h5>
        {s.shots.map((x, j) => (
          <div key={j} className="shot">
            <img src={assetUrl(project.id, x.assetId, 'thumb')} />
            <div className="shot-f">
              <div className="shot-row">
                <select value={x.assetId} onChange={e => set(y => { y.shots[j].assetId = e.target.value })}>
                  {project.assets.filter(a => a.kind !== 'audio' && (a.origin === 'import' || !a.origin)).map(a => <option key={a.id} value={a.id}>{a.id} {a.analysis?.scene || a.name}</option>)}
                </select>
                <button className="mini" onClick={() => set(y => { y.shots.splice(j, 1) })}>✕</button>
              </div>
              <div className="shot-row small">
                素材 <input type="number" step={0.1} value={x.in} onChange={e => set(y => { y.shots[j].in = +e.target.value })} />–
                <input type="number" step={0.1} value={x.out} onChange={e => set(y => { y.shots[j].out = +e.target.value })} />s　时长
                <input type="number" step={0.1} value={x.duration} onChange={e => set(y => { y.shots[j].duration = +e.target.value })} />s
              </div>
              {x.note && <div className="small muted">{x.note}</div>}
            </div>
          </div>))}
        <button className="link small" onClick={() => set(y => { const last = y.shots[y.shots.length - 1]; y.shots.push({ assetId: last?.assetId || project.assets[0]?.id, in: 0, out: 3, duration: 3, note: '' }) })}>＋ 添加镜头</button>
        <div className="row-btns">
          <button className="ghost sm danger" onClick={() => confirm('删除这一段？') && setSc(sc => { sc.sections.splice(i, 1) })}>删除本段</button>
        </div>
      </div>}
    </div>
  )
}
