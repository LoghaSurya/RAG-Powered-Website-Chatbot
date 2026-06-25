import { useState, useEffect, useRef } from 'react'
import './App.css'

const API = 'http://localhost:8000'

// ── Icons (inline SVG) ──────────────────────────
const SendIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
  </svg>
)
const BotIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/>
  </svg>
)
const ResetIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.5"/>
  </svg>
)
const LinkIcon = () => (
  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
  </svg>
)

// ── Typing Indicator ────────────────────────────
const TypingIndicator = () => (
  <div className="message bot">
    <div className="bubble">
      <div className="typing">
        <span/><span/><span/>
      </div>
    </div>
  </div>
)

// ── Main App ────────────────────────────────────
export default function App() {
  const [url, setUrl]           = useState('')
  const [maxPages, setMaxPages] = useState(15)
  const [maxDepth, setMaxDepth] = useState(2)
  const [crawlState, setCrawlState] = useState({ status: 'idle', pages_found: 0, chunks: 0, pages: [], error: null, url: null })
  const [messages, setMessages] = useState([])
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const [polling, setPolling]   = useState(false)
  const messagesEndRef           = useRef(null)
  const inputRef                 = useRef(null)
  const pollRef                  = useRef(null)

  // Auto-scroll chat to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Poll crawl status while active
  useEffect(() => {
    if (polling) {
      pollRef.current = setInterval(async () => {
        try {
          const res = await fetch(`${API}/api/status`)
          const data = await res.json()
          setCrawlState(data)
          if (data.status === 'ready' || data.status === 'error' || data.status === 'idle') {
            setPolling(false)
            clearInterval(pollRef.current)
          }
        } catch {
          setPolling(false)
          clearInterval(pollRef.current)
        }
      }, 1500)
    }
    return () => clearInterval(pollRef.current)
  }, [polling])

  // Fetch status on mount
  useEffect(() => {
    fetch(`${API}/api/status`)
      .then(r => r.json())
      .then(d => setCrawlState(d))
      .catch(() => {})
  }, [])

  const startCrawl = async () => {
    if (!url.trim()) return
    try {
      await fetch(`${API}/api/crawl`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim(), max_pages: Number(maxPages), max_depth: Number(maxDepth) })
      })
      setCrawlState(s => ({ ...s, status: 'crawling' }))
      setMessages([])
      setPolling(true)
    } catch (e) {
      alert('Could not reach the backend. Make sure the server is running on http://localhost:8000')
    }
  }

  const handleReset = async () => {
    await fetch(`${API}/api/reset`, { method: 'POST' }).catch(() => {})
    setCrawlState({ status: 'idle', pages_found: 0, chunks: 0, pages: [], error: null, url: null })
    setMessages([])
    setUrl('')
    setPolling(false)
    clearInterval(pollRef.current)
  }

  const sendMessage = async () => {
    const q = input.trim()
    if (!q || loading) return

    setMessages(m => [...m, { role: 'user', text: q, time: now() }])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(`${API}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q })
      })
      const data = await res.json()
      if (!res.ok) {
        setMessages(m => [...m, { role: 'bot', text: data.detail || 'Something went wrong.', sources: [], time: now(), error: true }])
      } else {
        setMessages(m => [...m, { role: 'bot', text: data.answer, sources: data.sources || [], time: now() }])
      }
    } catch {
      setMessages(m => [...m, { role: 'bot', text: 'Could not reach the backend. Make sure the server is running.', sources: [], time: now(), error: true }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const now = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  const isReady    = crawlState.status === 'ready'
  const isCrawling = crawlState.status === 'crawling' || crawlState.status === 'indexing'

  const statusLabel = {
    idle:     'Idle',
    crawling: 'Crawling…',
    indexing: 'Indexing…',
    ready:    'Ready',
    error:    'Error',
  }[crawlState.status] || 'Idle'

  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="header">
        <div className="header-brand">
          <div className="header-logo">🤖</div>
          <div>
            <div className="header-title">RAG Website Chatbot</div>
            <div className="header-subtitle">Powered by Google Gemini · ChromaDB</div>
          </div>
        </div>
        <div className="status-pill">
          <div className={`status-dot ${crawlState.status === 'ready' ? 'ready' : isCrawling ? 'active' : crawlState.status === 'error' ? 'error' : 'idle'}`}/>
          {statusLabel}
          {crawlState.url && <span style={{ color: 'var(--text-muted)', fontSize: '0.68rem' }}>· {new URL(crawlState.url).hostname}</span>}
        </div>
      </header>

      {/* ── Sidebar ── */}
      <aside className="sidebar">

        {/* URL Input Card */}
        <div className="card">
          <div className="card-title">🌐 Website to Ingest</div>
          <div className="url-input-wrap">
            <input
              className="url-input"
              type="url"
              placeholder="https://example.com"
              value={url}
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && startCrawl()}
              disabled={isCrawling}
              id="url-input"
            />
            <div className="url-input-row">
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 5 }}>Max Pages</div>
                <input className="input-sm" type="number" min="1" max="100" value={maxPages}
                  onChange={e => setMaxPages(e.target.value)} disabled={isCrawling}/>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 5 }}>Depth</div>
                <input className="input-sm" type="number" min="1" max="5" value={maxDepth}
                  onChange={e => setMaxDepth(e.target.value)} disabled={isCrawling}/>
              </div>
            </div>
            <button className="btn btn-primary btn-full" onClick={startCrawl} disabled={isCrawling || !url.trim()} id="crawl-btn">
              {isCrawling ? '⏳ Crawling…' : '🚀 Start Crawling'}
            </button>
          </div>
        </div>

        {/* Progress / Stats */}
        {(isCrawling || isReady || crawlState.status === 'error') && (
          <div className="card">
            <div className="card-title">📊 Crawl Status</div>

            {isCrawling && (
              <div className="progress-wrap" style={{ marginBottom: 12 }}>
                <div className="progress-label">
                  <span>{crawlState.status === 'indexing' ? 'Indexing into ChromaDB…' : 'Crawling pages…'}</span>
                  <span>{crawlState.pages_found} pages</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-fill indeterminate"/>
                </div>
              </div>
            )}

            {crawlState.status === 'error' && (
              <div className="alert alert-error" style={{ marginBottom: 10 }}>
                ⚠ {crawlState.error}
              </div>
            )}

            <div className="stats-row">
              <div className="stat-box">
                <div className="stat-val">{crawlState.pages_found}</div>
                <div className="stat-lbl">Pages</div>
              </div>
              <div className="stat-box">
                <div className="stat-val">{crawlState.chunks}</div>
                <div className="stat-lbl">Chunks</div>
              </div>
            </div>
          </div>
        )}

        {/* Crawled Pages */}
        {crawlState.pages?.length > 0 && (
          <div className="card">
            <div className="card-title">📄 Crawled Pages</div>
            <div className="pages-list">
              {crawlState.pages.map((p, i) => (
                <div key={i} className="page-item">
                  <div className="page-dot"/>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.url.replace(/^https?:\/\//, '')}
                  </span>
                  <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>{p.word_count.toLocaleString()}w</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Reset */}
        {crawlState.status !== 'idle' && (
          <button className="btn btn-danger btn-full" onClick={handleReset} disabled={isCrawling} id="reset-btn">
            <ResetIcon/> Reset & Clear Data
          </button>
        )}
      </aside>

      {/* ── Chat Area ── */}
      <main className="chat-area">
        <div className="chat-messages">
          {messages.length === 0 && !loading ? (
            <div className="empty-state">
              <div className="empty-icon">💬</div>
              <div className="empty-title">RAG-Powered Website Chatbot</div>
              <div className="empty-desc">
                Enter any website URL on the left, click <strong>Start Crawling</strong>, then ask questions about the content below.
              </div>
              <div className="how-it-works">
                <div className="step">
                  <div className="step-num">1</div>
                  <div className="step-text"><strong>Enter a URL</strong>Paste any website address in the sidebar input field.</div>
                </div>
                <div className="step">
                  <div className="step-num">2</div>
                  <div className="step-text"><strong>Start Crawling</strong>We'll recursively scrape linked pages and index all content.</div>
                </div>
                <div className="step">
                  <div className="step-num">3</div>
                  <div className="step-text"><strong>Ask Questions</strong>Type any question. Gemini will answer using only the scraped content with source citations.</div>
                </div>
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg, i) => (
                <div key={i} className={`message ${msg.role}`}>
                  {msg.role === 'bot' && (
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 5 }}>
                      <BotIcon/> Gemini · {msg.time}
                    </div>
                  )}
                  <div className={`bubble ${msg.error ? 'alert-error' : ''}`}>{msg.text}</div>
                  {msg.sources?.length > 0 && (
                    <div className="sources-wrap">
                      {msg.sources.map((s, si) => (
                        <a key={si} href={s} target="_blank" rel="noopener noreferrer" className="source-tag">
                          <LinkIcon/> {s.replace(/^https?:\/\//, '')}
                        </a>
                      ))}
                    </div>
                  )}
                  {msg.role === 'user' && (
                    <div className="message-meta">{msg.time}</div>
                  )}
                </div>
              ))}
              {loading && <TypingIndicator/>}
            </>
          )}
          <div ref={messagesEndRef}/>
        </div>

        {/* Input */}
        <div className="chat-input-area">
          <div className="chat-input-wrap">
            <textarea
              ref={inputRef}
              className="chat-input"
              rows={1}
              placeholder={isReady ? 'Ask anything about the website…' : 'Crawl a website first to start chatting…'}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              disabled={!isReady || loading}
              id="chat-input"
            />
            <button className="send-btn" onClick={sendMessage} disabled={!isReady || loading || !input.trim()} id="send-btn">
              <SendIcon/>
            </button>
          </div>
          <div className="chat-hint">
            {isReady
              ? `✅ ${crawlState.pages_found} pages · ${crawlState.chunks} chunks indexed · Press Enter to send`
              : '⬅ Enter a URL and click Start Crawling to begin'}
          </div>
        </div>
      </main>
    </div>
  )
}
