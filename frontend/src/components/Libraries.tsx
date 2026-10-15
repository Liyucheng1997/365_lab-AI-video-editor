import { useEffect, useState } from 'react'
import { api, assetUrl, fileUrl, fmt } from '../api'
import { useStore } from '../store'
import type { Asset } from '../types'
import { addAssetClip, addText } from './Timeline'

const TEXTS = [
  { preset: 'caption', name: '自由文字', demo: '文字', desc: '任意位置、字号、可加背景框' },
  { preset: 'subtitle', name: '字幕', demo: '中英双语字幕', desc: '底部居中，中文 + 英文' },
  { preset: 'heading', name: '段落标题', demo: '01 | 数字化制版', desc: '左上角编号 + 标题，擦除入场' },
  { preset: 'word', name: '关键词大字', demo: '品质', desc: '居中宋体大字，适合开场快剪' },
  { preset: 'title', name: '标题卡', demo: '一站式服装制造', desc: '主标题 / 片尾，带背景虚化' },
] as const

export function TextLibrary() {
  return (
    <div className="panel">
      <p className="muted small pad">点击添加到播放头位置，然后在右侧修改文字和样式。</p>
      <div className="text-grid">
        {TEXTS.map(t => (
          <button key={t.preset} className={'text-card tp-' + t.preset} onClick={() => addText(t.preset)}>
            <span className="demo">{t.demo}</span>
            <b>{t.name}</b>
            <span className="small muted">{t.desc}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export function AudioLibrary() {
  const project = useStore(s => s.project)!
  const [busy, setBusy] = useState(false)
  const [mood, setMood] = useState('inspiring')
  const [bpm, setBpm] = useState(100)
  const groups: [string, Asset[]][] = [
    ['配音', project.assets.filter(a => a.origin === 'tts')],
    ['背景音乐', project.assets.filter(a => a.origin === 'music' || (a.origin === 'import' && a.kind === 'audio'))],
    ['音效', project.assets.filter(a => a.origin === 'sfx')],
  ]
  const genMusic = async () => {
    setBusy(true)
    try {
      const a = await api.music(project.id, { mood, bpm, duration: project.timeline.duration || 60 })
      await useStore.getState().reload(['assets'])
      useStore.getState().notify(`已生成 ${fmt(a.duration)} 的背景音乐，拖到 BGM 轨道使用`)
    } catch (e: any) { useStore.getState().notify(e.message, 'error') }
    setBusy(false)
  }
  return (
    <div className="panel">
      <div className="card">
        <b>AI 合成背景音乐</b>
        <p className="muted small">程序生成，无版权问题，长度等于当前时间线。</p>
        <div className="grid2">
          <select value={mood} onChange={e => setMood(e.target.value)}>
            <option value="inspiring">激昂·企业宣传</option><option value="upbeat">轻快</option><option value="calm">舒缓·无鼓点</option>
          </select>
          <select value={bpm} onChange={e => setBpm(+e.target.value)}>
            {[80, 90, 100, 110, 120].map(b => <option key={b} value={b}>{b} BPM</option>)}
          </select>
        </div>
        <button className="ghost sm block" disabled={busy} onClick={genMusic}>{busy ? '生成中…' : '生成 BGM'}</button>
        <p className="muted small">也可以在「素材」里上传自己的正版音乐。</p>
      </div>
      {groups.map(([name, list]) => list.length > 0 && (
        <div key={name}>
          <h4 className="pad">{name}</h4>
          {list.map(a => <AudioRow key={a.id} a={a} />)}
        </div>
      ))}
    </div>
  )
}

function AudioRow({ a }: { a: Asset }) {
  const pid = useStore(s => s.project!.id)
  const [el] = useState(() => new Audio())
  const [playing, setPlaying] = useState(false)
  useEffect(() => () => { el.pause() }, [el])
  const toggle = () => {
    if (playing) { el.pause(); setPlaying(false); return }
    el.src = assetUrl(pid, a.id, 'proxy'); el.play(); setPlaying(true); el.onended = () => setPlaying(false)
  }
  return (
    <div className="audio-row" draggable onDragStart={e => e.dataTransfer.setData('application/x-asset', a.id)}>
      <button className="mini" onClick={toggle}>{playing ? '⏸' : '▶'}</button>
      <div className="grow"><div className="small">{a.name}</div><div className="muted small">{fmt(a.duration)}{a.lines ? ' · ' + a.lines.map(l => l.zh).join('').slice(0, 16) : ''}</div></div>
      <button className="mini" title="添加到播放头" onClick={() => addAssetClip(a.id)}>＋</button>
    </div>
  )
}

export function ExportDialog({ onClose }: { onClose: () => void }) {
  const project = useStore(s => s.project)!
  const jobs = useStore(s => s.jobs)
  const job = jobs.find(j => j.kind === 'export')
  const [list, setList] = useState<any[]>([])
  const [quality, setQuality] = useState('high')
  const refresh = () => api.exports(project.id).then(setList)
  useEffect(() => { refresh() }, [job?.status])
  const start = async () => {
    await useStore.getState().save()
    try { useStore.getState().trackJob(await api.exportVideo(project.id, quality)) } catch (e: any) { useStore.getState().notify(e.message, 'error') }
  }
  const running = job?.status === 'running'
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal export" onClick={e => e.stopPropagation()}>
        <div className="modal-head"><b>导出视频</b><button className="icon" onClick={onClose}>✕</button></div>
        <div className="pad">
          <div className="kv"><span>画幅</span><b>{project.settings.width}×{project.settings.height} · {project.settings.fps}fps · H.264</b></div>
          <div className="kv"><span>时长</span><b>{fmt(project.timeline.duration)}</b></div>
          <div className="kv"><span>音频</span><b>AAC 256k · 响度统一到 -14 LUFS（网络平台标准）</b></div>
          <div className="radio-row">
            <label><input type="radio" checked={quality === 'high'} onChange={() => setQuality('high')} />高质量（防抖 + 慢放光流补帧，母版画质）</label>
            <label><input type="radio" checked={quality === 'fast'} onChange={() => setQuality('fast')} />快速（不补帧，文件更小，适合先看效果）</label>
          </div>
          {running ? <div className="job-box">
            <div className="bar"><div style={{ width: `${job!.progress * 100}%` }} /></div>
            <div className="small">{job!.message}</div>
            <button className="ghost sm" onClick={() => api.cancel(job!.id)}>取消</button>
          </div> : <button className="primary block" onClick={start}>开始导出</button>}
          {job?.status === 'error' && <div className="err small">导出失败：{job.error}</div>}
          {list.length > 0 && <>
            <h4>已导出</h4>
            {list.map(f => (
              <div key={f.name} className="export-row">
                <div className="grow"><div className="small">{f.name}</div><div className="muted small">{(f.size / 1048576).toFixed(1)} MB · {new Date(f.time * 1000).toLocaleString()}</div></div>
                <a className="btn ghost sm" href={fileUrl(project.id, f.file)} target="_blank">播放</a>
                <a className="btn ghost sm" href={fileUrl(project.id, f.file, true)}>下载</a>
                {f.srt && <a className="btn ghost sm" href={fileUrl(project.id, f.srt, true)}>字幕</a>}
                <button className="ghost sm" onClick={() => api.reveal(project.id, f.file)}>打开文件夹</button>
              </div>
            ))}
          </>}
        </div>
      </div>
    </div>
  )
}
