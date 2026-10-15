export type AssetKind = 'video' | 'audio' | 'image'

export interface Analysis {
  summary: string
  scene: string
  content: string
  tags: string[]
  quality: { score: number; issues: string[] }
  segments: { start: number; end: number; desc: string; score: number }[]
  usage: string
}

export interface Asset {
  id: string
  name: string
  path: string
  kind: AssetKind
  origin: 'import' | 'tts' | 'music' | 'sfx'
  status: 'pending' | 'ready' | 'error'
  error?: string
  duration: number
  width: number
  height: number
  hasAudio?: boolean
  hdr?: boolean
  proxy?: string
  thumb?: string
  strip?: string
  stripInfo?: { tileW: number; tileH: number; count: number; step: number }
  peaks?: string
  motion?: { jitter: number; pan: number }
  audio?: { rmsDb: number; peakDb: number }
  analysis?: Analysis
  lines?: Line[]
  spans?: [number, number][]
  voice?: string
  suggestedVolume?: number
}

export interface Line { zh: string; en: string }

export type TransitionType = 'none' | 'fade' | 'black' | 'white' | 'flash'

export interface Filter {
  preset: string
  exposure?: number
  contrast?: number
  saturation?: number
  temperature?: number
  sharpen?: number
  splitTone?: number
  blur?: number
  brightness?: number
}

export interface BaseClip {
  id: string
  start: number
  duration: number
  label?: string
  sectionId?: string
}

export interface VideoClip extends BaseClip {
  assetId: string
  in: number
  out: number
  freeze?: boolean
  volume?: number
  ambience?: boolean
  stabilize?: boolean
  smoothSlowmo?: boolean
  transition?: { type: TransitionType; duration: number }
  filter?: Filter
  transform?: { zoom?: number; kenburns?: number; x?: number; y?: number; rotate?: number }
  note?: string
}

export type TextPreset = 'subtitle' | 'heading' | 'word' | 'title' | 'caption'

export interface TextClip extends BaseClip {
  preset: TextPreset
  text: string
  sub?: string
  kicker?: string
  extra?: string
  num?: string
  color?: string
  accent?: string
  scale?: number
  dx?: number
  dy?: number
  x?: number
  y?: number
  fontSize?: number
  font?: string
  box?: boolean
  backdrop?: boolean
}

export interface AudioClip extends BaseClip {
  assetId: string
  in: number
  volume: number
  fadeIn?: number
  fadeOut?: number
  duck?: boolean
  duckAmount?: number
}

export type Clip = VideoClip | TextClip | AudioClip

export interface Track {
  id: string
  type: 'video' | 'text' | 'audio'
  role?: 'voice' | 'music' | 'sfx'
  name: string
  clips: Clip[]
  muted?: boolean
  hidden?: boolean
}

export interface Timeline { duration: number; tracks: Track[] }

export interface Section {
  id: string
  kind: 'intro' | 'title' | 'section' | 'ending'
  name: string
  heading?: { num: string; zh: string; en: string }
  card?: { kicker: string; text: string; sub: string; extra: string }
  words?: Line[]
  lines: Line[]
  shots: { assetId: string; in: number; out: number; duration: number; note: string }[]
  start?: number
  dur?: number
}

export interface Script {
  title: string
  logline: string
  musicMood: string
  musicBpm: number
  assumptions: string[]
  sections: Section[]
  status: 'draft' | 'approved' | 'built'
  version?: number
  feedback?: string
  history?: Omit<Script, 'history'>[]
}

export interface Brief {
  purpose: string
  audience: string
  style: string
  duration: number
  subtitleLang: 'zh+en' | 'zh' | 'en'
  voice: string
  voiceRate: string
  notes: string
  musicAssetId?: string | null
}

export interface Project {
  id: string
  name: string
  settings: { width: number; height: number; fps: number; look: { vignette: boolean; gradients: boolean; fadeInOut: boolean } }
  brief: Brief
  assets: Asset[]
  script: Script | null
  timeline: Timeline
  updatedAt: number
}

export interface Job {
  id: string
  kind: 'ingest' | 'analyze' | 'script' | 'build' | 'export'
  projectId: string
  status: 'running' | 'done' | 'error' | 'cancelled'
  progress: number
  message: string
  error: string | null
  log: string[]
  result: any
}

export const isVideo = (c: Clip, t: Track): c is VideoClip => t.type === 'video'
export const isText = (c: Clip, t: Track): c is TextClip => t.type === 'text'
export const isAudio = (c: Clip, t: Track): c is AudioClip => t.type === 'audio'
