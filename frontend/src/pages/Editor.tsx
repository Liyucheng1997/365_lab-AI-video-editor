import { useEffect, useState } from 'react'
import AIPanel from '../components/AIPanel'
import Inspector from '../components/Inspector'
import { AudioLibrary, ExportDialog, TextLibrary } from '../components/Libraries'
import MediaPanel from '../components/MediaPanel'
import Preview, { PlayerBar } from '../components/Preview'
import Timeline, { useTimelineKeys } from '../components/Timeline'
import { jobName, useStore } from '../store'

const TABS = [
  { k: 'media', name: '素材', icon: '▣' },
  { k: 'ai', name: 'AI 剪辑', icon: '✦' },
  { k: 'text', name: '文字', icon: 'T' },
  { k: 'audio', name: '音频', icon: '♪' },
] as const

export default function Editor({ pid }: { pid: string }) {
  const project = useStore(s => s.project)
  const tab = useStore(s => s.tab)
  const jobs = useStore(s => s.jobs)
  const [exp, setExp] = useState(false)
  const [err, setErr] = useState('')
  useTimelineKeys()
  useEffect(() => { useStore.getState().load(pid).catch(e => setErr(e.message)) }, [pid])
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (useStore.getState().dirty) { useStore.getState().save(); e.preventDefault() } }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [])
  if (err) return <div className="center-msg">打开项目失败：{err} <a href="#/">返回</a></div>
  if (!project || project.id !== pid) return <div className="center-msg">加载中…</div>
  const active = jobs.filter(j => j.status === 'running')
  return (
    <div className="editor">
      <header className="topbar">
        <a href="#/" className="home" onClick={() => useStore.getState().save()}>◀ 项目</a>
        <input className="pname" value={project.name} onChange={e => useStore.getState().patchProject({ name: e.target.value })} />
        <div className="grow" />
        {active.map(j => (
          <div key={j.id} className="jobpill" title={j.log.slice(-6).join('\n')}>
            <span className="spin sm" />{jobName(j.kind)}：{j.message}
            <div className="mini-bar"><div style={{ width: `${j.progress * 100}%` }} /></div>
          </div>
        ))}
        <button className="primary" onClick={() => setExp(true)}>导出</button>
      </header>
      <div className="main">
        <aside className="left">
          <nav className="tabs">
            {TABS.map(t => <button key={t.k} className={tab === t.k ? 'on' : ''} onClick={() => useStore.getState().setTab(t.k)}><i>{t.icon}</i>{t.name}</button>)}
          </nav>
          <div className="left-body">
            {tab === 'media' && <MediaPanel />}
            {tab === 'ai' && <AIPanel />}
            {tab === 'text' && <TextLibrary />}
            {tab === 'audio' && <AudioLibrary />}
          </div>
        </aside>
        <section className="center">
          <Preview />
          <PlayerBar />
        </section>
        <aside className="right"><Inspector /></aside>
      </div>
      <Timeline />
      {exp && <ExportDialog onClose={() => setExp(false)} />}
      <Toast />
    </div>
  )
}

function Toast() {
  const t = useStore(s => s.toast)
  if (!t) return null
  return <div className={'toast ' + t.kind} onClick={() => useStore.setState({ toast: null })}>{t.msg}</div>
}
