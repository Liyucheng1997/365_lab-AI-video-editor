import { useEffect, useState } from 'react'
import { api, assetUrl, fmt, upload } from '../api'
import { useStore } from '../store'
import type { Asset } from '../types'
import { addAssetClip } from './Timeline'

export default function MediaPanel() {
  const project = useStore(s => s.project)!
  const jobs = useStore(s => s.jobs)
  const [over, setOver] = useState(false)
  const [up, setUp] = useState<number | null>(null)
  const [browse, setBrowse] = useState(false)
  const [detail, setDetail] = useState<Asset | null>(null)
  const assets = project.assets.filter(a => a.origin === 'import' || !a.origin)
  const analyzing = jobs.some(j => j.kind === 'analyze' && j.status === 'running')
  const analyzed = assets.filter(a => a.analysis).length

  const onFiles = async (files: File[]) => {
    if (!files.length) return
    setUp(0)
    try {
      const r = await upload(project.id, files, setUp)
      useStore.getState().trackJob(r.job)
      await useStore.getState().reload(['assets'])
    } catch (e: any) { useStore.getState().notify('上传失败：' + e.message, 'error') }
    setUp(null)
  }
  const analyze = async (force = false) => {
    try { useStore.getState().trackJob(await api.analyze(project.id, { force })) } catch (e: any) { useStore.getState().notify(e.message, 'error') }
  }

  return (
    <div className="panel media-panel"
      onDragOver={e => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setOver(true) } }}
      onDragLeave={() => setOver(false)}
      onDrop={e => { if (e.dataTransfer.files.length) { e.preventDefault(); setOver(false); onFiles([...e.dataTransfer.files]) } }}>
      <div className="panel-actions">
        <label className="btn primary sm">上传文件<input type="file" multiple hidden accept="video/*,audio/*,image/*" onChange={e => onFiles([...(e.target.files || [])])} /></label>
        <button className="btn ghost sm" onClick={() => setBrowse(true)}>从素材库导入</button>
        <div className="grow" />
        {assets.length > 0 && <button className="btn ghost sm" disabled={analyzing} onClick={() => analyze(analyzed === assets.length)}
          title={analyzed === assets.length ? '重新分析全部素材' : '让 AI 看一遍素材'}>{analyzing ? 'AI 分析中…' : analyzed === assets.length ? '重新分析' : `AI 分析素材${analyzed ? `（${analyzed}/${assets.length}）` : ''}`}</button>}
      </div>
      {up != null && <div className="upbar"><div style={{ width: `${up * 100}%` }} /><span>上传中 {Math.round(up * 100)}%</span></div>}
      {over && <div className="dropmask">松开鼠标导入素材</div>}
      {!assets.length ? (
        <div className="empty-drop">
          <div className="big">⇪</div>
          <p>把视频、图片、音乐拖到这里</p>
          <p className="muted small">或点「从素材库导入」直接引用本机文件夹（不复制）</p>
        </div>
      ) : (
        <div className="asset-grid">
          {assets.map(a => <AssetCard key={a.id} a={a} onOpen={() => setDetail(a)} />)}
        </div>
      )}
      {browse && <FolderBrowser onClose={() => setBrowse(false)} />}
      {detail && <AssetDetail a={project.assets.find(x => x.id === detail.id) || detail} onClose={() => setDetail(null)} />}
    </div>
  )
}

function AssetCard({ a, onOpen }: { a: Asset; onOpen: () => void }) {
  const pid = useStore(s => s.project!.id)
  const used = useStore(s => s.project!.timeline.tracks.some(t => t.clips.some((c: any) => c.assetId === a.id)))
  const an = a.analysis
  return (
    <div className="asset-card" draggable={a.status === 'ready'} onDragStart={e => { e.dataTransfer.setData('application/x-asset', a.id); e.dataTransfer.effectAllowed = 'copy' }}
      onDoubleClick={onOpen} title={an ? `${an.summary}\n${an.usage}` : a.name}>
      <div className="thumb" onClick={onOpen}>
        {a.thumb ? <img src={assetUrl(pid, a.id, 'thumb')} loading="lazy" /> : <div className="ph">{a.kind === 'audio' ? '♪' : a.status === 'error' ? '!' : '…'}</div>}
        <span className="dur">{a.kind === 'image' ? '图片' : fmt(a.duration, false)}</span>
        <span className="aid">{a.id}</span>
        {an && <span className={'score s' + Math.round(an.quality.score / 3.4)}>{an.quality.score}</span>}
        {used && <span className="used" title="已在时间线上使用">✓</span>}
        {a.status === 'pending' && <div className="spin" />}
        <button className="add" title="添加到播放头位置" onClick={e => { e.stopPropagation(); addAssetClip(a.id) }}>＋</button>
      </div>
      <div className="meta">
        {a.status === 'error' ? <span className="err small">{a.error}</span>
          : an ? <><span className="tag">{an.scene}</span><span className="small">{an.summary}</span></>
            : <span className="small muted">{a.name}</span>}
      </div>
    </div>
  )
}

function AssetDetail({ a, onClose }: { a: Asset; onClose: () => void }) {
  const pid = useStore(s => s.project!.id)
  const [ref, setRef] = useState<HTMLVideoElement | null>(null)
  const an = a.analysis
  const del = async () => {
    if (!confirm(`从项目中移除素材 ${a.name}？（不会删除原文件）`)) return
    try { await api.deleteAsset(pid, a.id); await useStore.getState().reload(['assets']); onClose() } catch (e: any) { useStore.getState().notify(e.message, 'error') }
  }
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal detail" onClick={e => e.stopPropagation()}>
        <div className="modal-head"><b>{a.id} · {a.name}</b><button className="icon" onClick={onClose}>✕</button></div>
        <div className="detail-body">
          <div className="detail-video">
            {a.kind === 'video' ? <video ref={setRef} src={assetUrl(pid, a.id, 'proxy')} controls /> : a.kind === 'image' ? <img src={assetUrl(pid, a.id, 'proxy')} /> : <audio src={assetUrl(pid, a.id, 'proxy')} controls />}
          </div>
          <div className="detail-info">
            <div className="kv"><span>规格</span><b>{a.width}×{a.height} · {fmt(a.duration)}{a.hdr ? ' · HDR→SDR' : ''}</b></div>
            {a.motion && <div className="kv"><span>手持抖动</span><b>{a.motion.jitter > 7 ? '较明显' : a.motion.jitter > 4 ? '轻微' : '稳定'}（{a.motion.jitter}px）</b></div>}
            {a.audio && <div className="kv"><span>原声响度</span><b>{a.audio.rmsDb} dB</b></div>}
            {an ? <>
              <h4>AI 分析 · {an.scene} · {an.quality.score} 分</h4>
              <p>{an.content}</p>
              {an.quality.issues.length > 0 && <p className="warn small">问题：{an.quality.issues.join('；')}</p>}
              <p className="small">建议用途：{an.usage}</p>
              <h4>推荐片段</h4>
              {an.segments.map((s, i) => (
                <div key={i} className="seg">
                  <button className="link" onClick={() => { if (ref) { ref.currentTime = s.start; ref.play() } }}>{s.start.toFixed(1)}–{s.end.toFixed(1)}s</button>
                  <span className="small">{s.desc}（{s.score}）</span>
                  <button className="mini" title="把这个片段加到播放头" onClick={() => { addAssetClip(a.id, undefined, undefined, { in: s.start, out: s.end }); onClose() }}>＋</button>
                </div>
              ))}
              <div className="tags">{an.tags.map(t => <span key={t} className="tag">{t}</span>)}</div>
            </> : <p className="muted">还没有 AI 分析。点「AI 分析素材」让 AI 看一遍。</p>}
            <div className="row-btns"><button className="ghost sm danger" onClick={del}>从项目移除</button></div>
          </div>
        </div>
      </div>
    </div>
  )
}

export function FolderBrowser({ onClose }: { onClose: () => void }) {
  const pid = useStore(s => s.project!.id)
  const [path, setPath] = useState(localStorage.getItem('aicut.lastFolder') || '')
  const [data, setData] = useState<any>(null)
  const [input, setInput] = useState(path)
  const [err, setErr] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  useEffect(() => {
    setErr('')
    api.browse(path).then(d => { setData(d); setInput(d.path); setPicked(new Set()) }).catch(e => { setErr(e.message); if (path) setPath('') })
  }, [path])
  const go = (p: string) => setPath(p)
  const doImport = async () => {
    try {
      const files = [...picked]
      const r = await api.importPaths(pid, files.length ? { paths: files.map(f => data.path + '/' + f) } : { folder: data.path })
      try { localStorage.setItem('aicut.lastFolder', data.path) } catch { /* */ }
      if (r.job) useStore.getState().trackJob(r.job)
      await useStore.getState().reload(['assets'])
      useStore.getState().notify(`导入 ${r.assetIds.length} 个素材`)
      onClose()
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal browser" onClick={e => e.stopPropagation()}>
        <div className="modal-head"><b>从本机素材库导入</b><button className="icon" onClick={onClose}>✕</button></div>
        <div className="path-row">
          <button className="icon" disabled={!data?.parent && !data?.path} onClick={() => go(data?.parent || '')}>↑</button>
          <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && go(input.trim().replace(/^"|"$/g, ''))} placeholder="粘贴文件夹路径后回车，例如 F:\我的视频分享\62_工厂宣传视频" />
          <button className="ghost sm" onClick={() => go(input.trim().replace(/^"|"$/g, ''))}>前往</button>
        </div>
        {err && <div className="err small">{err}</div>}
        <div className="fs-list">
          {data?.dirs.map((d: string) => <div key={d} className="fs-item dir" onDoubleClick={() => go(data.path ? data.path.replace(/\/$/, '') + '/' + d : d)} onClick={() => go(data.path ? data.path.replace(/\/$/, '') + '/' + d : d)}>📁 {d}</div>)}
          {data?.files.map((f: any) => (
            <label key={f.name} className="fs-item file">
              <input type="checkbox" checked={picked.has(f.name)} onChange={e => { const n = new Set(picked); e.target.checked ? n.add(f.name) : n.delete(f.name); setPicked(n) }} />
              {f.kind === 'video' ? '🎞' : f.kind === 'audio' ? '🎵' : '🖼'} {f.name}<span className="muted small">{(f.size / 1048576).toFixed(1)} MB</span>
            </label>
          ))}
          {data && !data.dirs.length && !data.files.length && <div className="muted small pad">这个文件夹里没有媒体文件</div>}
        </div>
        <div className="modal-foot">
          <span className="muted small">{data?.files.length ? `本文件夹 ${data.files.length} 个媒体文件，${picked.size ? `已选 ${picked.size} 个` : '未勾选则全部导入'}` : ''}</span>
          <div className="grow" />
          <button className="ghost" onClick={onClose}>取消</button>
          <button className="primary" disabled={!data?.files.length} onClick={doImport}>导入{picked.size ? `所选 ${picked.size} 个` : '全部'}</button>
        </div>
      </div>
    </div>
  )
}
