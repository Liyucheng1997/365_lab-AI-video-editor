import { useEffect, useState } from 'react'
import { api, fmt } from '../api'

const RATIOS = [
  { name: '竖屏 9:16', w: 1080, h: 1920, hint: '抖音 / 视频号 / 手机' },
  { name: '横屏 16:9', w: 1920, h: 1080, hint: '电脑 / 电视 / B 站' },
  { name: '方形 1:1', w: 1080, h: 1080, hint: '朋友圈 / 小红书' },
  { name: '竖屏 3:4', w: 1080, h: 1440, hint: '小红书' },
]

export default function Home() {
  const [list, setList] = useState<any[] | null>(null)
  const [name, setName] = useState('')
  const [ratio, setRatio] = useState(0)
  const [err, setErr] = useState('')
  const load = () => api.projects().then(setList).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])
  const create = async () => {
    const r = RATIOS[ratio]
    try {
      const p = await api.create(name.trim() || '未命名项目', r.w, r.h)
      location.hash = `#/p/${p.id}`
    } catch (e: any) { setErr(e.message) }
  }
  const del = async (p: any) => {
    if (!confirm(`删除项目「${p.name}」？（会移到 projects/_trash，素材原文件不受影响）`)) return
    await api.remove(p.id)
    load()
  }
  return (
    <div className="home-page">
      <header className="home-head">
        <div className="logo"><span>▶</span>AI 剪辑</div>
        <span className="muted small">AI 分析素材 → 生成剪辑脚本 → 自动剪辑 → 手动精修 → 导出</span>
      </header>
      <div className="home-body">
        <div className="new-card">
          <h2>新建项目</h2>
          <input value={name} placeholder="项目名称，例如：工厂宣传片" onChange={e => setName(e.target.value)} onKeyDown={e => e.key === 'Enter' && create()} />
          <div className="ratios">
            {RATIOS.map((r, i) => (
              <button key={i} className={'ratio' + (i === ratio ? ' on' : '')} onClick={() => setRatio(i)}>
                <span className="shape" style={{ width: r.w / r.h > 1 ? 44 : 44 * r.w / r.h, height: r.w / r.h > 1 ? 44 * r.h / r.w : 44 }} />
                <b>{r.name}</b><span className="muted small">{r.hint}</span>
              </button>
            ))}
          </div>
          <button className="primary block" onClick={create}>开始创作</button>
          {err && <div className="err small">{err}</div>}
        </div>
        <h3>我的项目</h3>
        {list === null ? <div className="muted">加载中…</div> : !list.length ? <div className="muted">还没有项目</div> : (
          <div className="proj-grid">
            {list.map(p => (
              <a key={p.id} className="proj-card" href={`#/p/${p.id}`}>
                <div className="pthumb">
                  {p.thumb ? <img src={`/api/projects/${p.id}/files/${p.thumb}`} /> : <span>▶</span>}
                  {p.duration > 0 && <span className="dur">{fmt(p.duration, false)}</span>}
                </div>
                <b>{p.name}</b>
                <span className="muted small">{p.settings?.width}×{p.settings?.height} · {p.assetCount} 个素材 · {new Date(p.updatedAt * 1000).toLocaleString()}</span>
                <button className="del" title="删除项目" onClick={e => { e.preventDefault(); del(p) }}>✕</button>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
