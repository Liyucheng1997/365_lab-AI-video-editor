import { useEffect, useState } from 'react'
import Editor from './pages/Editor'
import Home from './pages/Home'

export default function App() {
  const [hash, setHash] = useState(location.hash)
  useEffect(() => {
    const h = () => setHash(location.hash)
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])
  const m = hash.match(/^#\/p\/([\w-]+)/)
  return m ? <Editor pid={m[1]} /> : <Home />
}
