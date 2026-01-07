'use client'

import { useMemo, useState } from 'react'

const API_BASE = 'http://127.0.0.1:8000'

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-semibold text-white">
      {children}
    </span>
  )
}

export default function Home() {
  const [fileName, setFileName] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')
  const [qaQuestion, setQaQuestion] = useState('')
  const [qaLoading, setQaLoading] = useState(false)
  const [qaResult, setQaResult] = useState<any>(null)
  const [qaError, setQaError] = useState('')

  async function analyzeFile(file: File) {
    setError('')
    setResult(null)
    setQaResult(null)
    setFileName(file.name)
    setLoading(true)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }

      const data = await res.json()
      setResult(data)
    } catch (err: any) {
      setError(err?.message || 'Upload failed')
    } finally {
      setLoading(false)
    }
  }

  async function askQuestion() {
    if (!qaQuestion.trim() || !result?.document_id) return
    
    setQaLoading(true)
    setQaError('')
    
    try {
      const res = await fetch(`${API_BASE}/ask`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          document_id: result.document_id,
          question: qaQuestion.trim()
        })
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }

      const data = await res.json()
      setQaResult(data)
    } catch (err: any) {
      setQaError(err?.message || 'Failed to get answer')
    } finally {
      setQaLoading(false)
    }
  }

  async function downloadText() {
    if (!result?.document_id) return
    
    try {
      // Create a blob and download
      const fullText = result.doc_text || "No text available"
      const blob = new Blob([fullText], { type: 'text/plain' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `document_${result.document_id}_extracted.txt`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      console.error('Download failed:', err)
    }
  }

  function onFileChange(e: any) {
    const f = e?.target?.files?.[0]
    if (f) analyzeFile(f)
  }

  function onDrop(e: any) {
    e.preventDefault()
    const f = e?.dataTransfer?.files?.[0]
    if (f) analyzeFile(f)
  }

  const risk = result?.risk?.color || '-'
  const riskTone =
    risk === 'Green'
      ? 'from-emerald-500/15 to-emerald-500/5 border-emerald-500/30 text-emerald-200'
      : risk === 'Orange'
      ? 'from-orange-500/15 to-orange-500/5 border-orange-500/30 text-orange-200'
      : risk === 'Red'
      ? 'from-rose-500/15 to-rose-500/5 border-rose-500/30 text-rose-200'
      : 'from-slate-500/10 to-slate-500/5 border-white/10 text-slate-200'

  const audioUrl = useMemo(() => {
    const p = result?.audio?.tamil_summary_mp3_url
    return p ? `${API_BASE}${p}` : ''
  }, [result])

  const mainAmount = result?.facts?.amounts?.[0] || '-'
  const survey = result?.facts?.property?.survey_no || '-'
  const patta = result?.facts?.property?.patta_no || '-'

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      {/* Top bar */}
      <div className="border-b border-white/10 bg-slate-950/60 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <img
              src="/legalease.png"
              alt="LegalEase AI logo"
              className="h-10 w-10 rounded-xl"
            />
            <div>
              <div className="text-lg font-bold leading-tight">LegalEase AI</div>
              <div className="text-xs text-slate-400">Dialect-aware summaries • Risk dashboard • Tamil audio • Document Q&A</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge>Prototype</Badge>
            <Badge>FastAPI + Next.js</Badge>
            <Badge>RAG Q&A</Badge>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="mx-auto max-w-6xl px-6 py-8 space-y-6">
        {/* Hero */}
        <div className="rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900 to-slate-950 p-7">
          <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-3xl font-extrabold tracking-tight">Upload a legal PDF. Get a Tamil/English explanation.</h1>
              <p className="mt-1 text-slate-300">
                Extracts parties, dates, amounts, land identifiers (Survey/Patta) and generates Tamil audio with a risk indicator.
              </p>
            </div>
            <div className="text-sm text-slate-400">
              Backend: <span className="text-slate-200">127.0.0.1:8000</span> • UI: <span className="text-slate-200">localhost:3001</span>
            </div>
          </div>

          {/* Upload card */}
          <div
            className="mt-6 rounded-2xl border border-white/10 bg-slate-950/40 p-6"
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
          >
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="text-sm font-semibold">Upload</div>
                <div className="text-sm text-slate-400">Drag & drop a PDF here, or select a file.</div>
                {fileName ? <div className="mt-2 text-sm text-slate-200">Selected: {fileName}</div> : null}
                {loading ? <div className="mt-2 text-sm font-semibold text-cyan-300">Analyzing…</div> : null}
                {error ? <div className="mt-2 text-sm font-semibold text-rose-300">{error}</div> : null}
              </div>

              <label className="inline-flex cursor-pointer items-center justify-center rounded-xl bg-white px-4 py-2 text-sm font-bold text-slate-900 hover:bg-slate-200">
                Choose PDF
                <input type="file" accept="application/pdf" onChange={onFileChange} className="hidden" />
              </label>
            </div>
          </div>
        </div>

        {/* KPI cards */}
        <div className="grid gap-4 md:grid-cols-3">
          <div className={`rounded-2xl border bg-gradient-to-b p-5 ${riskTone}`}>
            <div className="text-xs font-semibold text-slate-300">Risk status</div>
            <div className="mt-2 text-2xl font-extrabold">{risk}</div>
            <div className="mt-1 text-sm text-slate-300">
              {result?.risk?.missing_fields?.length
                ? `Missing: ${result.risk.missing_fields.join(', ')}`
                : 'Core fields present (parties, date, amount).'}
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-5">
            <div className="text-xs font-semibold text-slate-400">Main amount</div>
            <div className="mt-2 text-2xl font-extrabold text-white">{mainAmount}</div>
            <div className="mt-1 text-sm text-slate-400">First detected consideration / payment.</div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-5">
            <div className="text-xs font-semibold text-slate-400">Land identifiers</div>
            <div className="mt-2 text-sm text-slate-200">
              <div><span className="text-slate-400">Survey:</span> {survey}</div>
              <div><span className="text-slate-400">Patta:</span> {patta}</div>
            </div>
            <div className="mt-2 text-xs text-slate-400">Useful for land-dispute verification.</div>
          </div>
        </div>

        {/* Details */}
        {result ? (
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2 space-y-4">
              <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-6">
                <div className="text-sm font-bold">Extracted facts</div>
                <div className="mt-4 grid gap-3 md:grid-cols-2 text-sm">
                  <div className="rounded-xl border border-white/10 bg-slate-950/40 p-4">
                    <div className="text-xs font-semibold text-slate-400">Parties</div>
                    <div className="mt-1 text-slate-100">{(result.facts?.parties || []).join(', ') || '-'}</div>
                  </div>

                  <div className="rounded-xl border border-white/10 bg-slate-950/40 p-4">
                    <div className="text-xs font-semibold text-slate-400">Vendor → Purchaser</div>
                    <div className="mt-1 text-slate-100">
                      {result.facts?.role_parties?.vendor || '-'} → {result.facts?.role_parties?.purchaser || '-'}
                    </div>
                  </div>

                  <div className="rounded-xl border border-white/10 bg-slate-950/40 p-4">
                    <div className="text-xs font-semibold text-slate-400">Dates</div>
                    <div className="mt-1 text-slate-100">{(result.facts?.dates || []).join(', ') || '-'}</div>
                  </div>

                  <div className="rounded-xl border border-white/10 bg-slate-950/40 p-4">
                    <div className="text-xs font-semibold text-slate-400">Amounts</div>
                    <div className="mt-1 text-slate-100">{(result.facts?.amounts || []).join(', ') || '-'}</div>
                  </div>

                  <div className="rounded-xl border border-white/10 bg-slate-950/40 p-4 md:col-span-2">
                    <div className="text-xs font-semibold text-slate-400">Property</div>
                    <div className="mt-1 text-slate-100">
                      Survey: {result.facts?.property?.survey_no || '-'} • Patta: {result.facts?.property?.patta_no || '-'} <br />
                      Village: {result.facts?.property?.village || '-'} • Taluk: {result.facts?.property?.taluk || '-'} • District: {result.facts?.property?.district || '-'}
                    </div>
                  </div>
                </div>

                <div className="mt-4 text-xs text-slate-400">
                  Disclaimer: This output is informational and not legal advice.
                </div>
              </div>

              {/* Document Q&A Card */}
              <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-6">
                <div className="text-sm font-bold mb-4">Document Q&A (RAG)</div>
                <div className="space-y-4">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={qaQuestion}
                      onChange={(e) => setQaQuestion(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && askQuestion()}
                      placeholder="Ask a question about this document..."
                      className="flex-1 rounded-xl border border-white/10 bg-slate-950/40 px-4 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-500/50 focus:outline-none focus:ring-1 focus:ring-cyan-500/30"
                    />
                    <button
                      onClick={askQuestion}
                      disabled={!qaQuestion.trim() || qaLoading || !result?.document_id}
                      className="rounded-xl bg-cyan-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {qaLoading ? 'Asking...' : 'Ask'}
                    </button>
                  </div>

                  {qaError && (
                    <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3">
                      <div className="text-sm font-semibold text-rose-300">Error: {qaError}</div>
                    </div>
                  )}

                  {qaResult && (
                    <div className="space-y-4">
                      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
                        <div className="text-xs font-semibold text-emerald-300">Answer</div>
                        <div className="mt-1 text-sm text-slate-200">{qaResult.answer}</div>
                        <div className="mt-2 text-xs text-emerald-400">
                          Best match similarity: {(qaResult.best_similarity * 100).toFixed(1)}%
                        </div>
                      </div>

                      <div className="rounded-xl border border-white/10 bg-slate-950/40 p-4">
                        <div className="text-xs font-semibold text-slate-400 mb-2">Evidence sources</div>
                        <div className="space-y-3">
                          {qaResult.sources?.map((source: any, index: number) => (
                            <div key={index} className="border-l-2 border-cyan-500/50 pl-3 py-1">
                              <div className="text-xs text-slate-500">
                                Chunk #{source.chunk_id} • Similarity: {(source.similarity * 100).toFixed(1)}%
                              </div>
                              <div className="text-sm text-slate-300 mt-1">{source.snippet}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="text-xs text-slate-500 pt-2 border-t border-white/10">
                    Ask questions like "What is the sale amount?" or "Who are the parties involved?" or "What are the property details?"
                  </div>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-6">
                  <div className="text-sm font-bold">English summary</div>
                  <p className="mt-3 text-sm text-slate-200 whitespace-pre-wrap">{result.summaries?.english}</p>
                </div>

                <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-6">
                  <div className="text-sm font-bold">Tamil summary</div>
                  <p className="mt-3 text-sm text-slate-200 whitespace-pre-wrap">{result.summaries?.tamil}</p>
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-6">
                <div className="text-sm font-bold">Tamil audio</div>
                <p className="mt-2 text-sm text-slate-400">Listen to the generated spoken explanation.</p>
                <audio className="mt-4 w-full" controls src={audioUrl} />
              </div>

              <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-6">
                <div className="text-sm font-bold">Document Tools</div>
                <div className="mt-3 space-y-3">
                  <button
                    onClick={downloadText}
                    className="w-full rounded-xl border border-white/10 bg-slate-950/40 px-4 py-3 text-sm font-medium text-slate-200 hover:bg-slate-800/40 hover:border-white/20 transition-colors"
                  >
                    <div className="flex items-center justify-center gap-2">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      Download extracted text
                    </div>
                  </button>
                  
                  <div className="text-xs text-slate-500 p-3 bg-slate-950/30 rounded-lg">
                    <div className="font-medium text-slate-400">Document ID:</div>
                    <div className="mt-1 font-mono text-xs break-all">{result.document_id}</div>
                    <div className="mt-2 text-slate-500">
                      {result.index_info?.num_chunks} chunks indexed for Q&A
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-6">
                <div className="text-sm font-bold">How it works</div>
                <ul className="mt-3 space-y-2 text-sm text-slate-300">
                  <li className="flex items-start gap-2">
                    <span className="text-cyan-400">1.</span>
                    <span>Upload PDF and extract text</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-cyan-400">2.</span>
                    <span>Extract entities & facts</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-cyan-400">3.</span>
                    <span>Risk color based on missing key fields</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-cyan-400">4.</span>
                    <span>Tamil summary + audio (TTS)</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-cyan-400">5.</span>
                    <span>Build RAG index for Q&A</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </main>
  )
}