const API_BASE = '/api'

export interface ChatResponse {
  answer: string
  market_regime: string
  generated_at: string
}

export interface MarketSummary {
  market_regime: string
  benchmark_strength: Record<string, string>
  bucket_scores: {
    bucket_name: string
    label: string
    role: string
    avg_pct_change: number
    stronger_than_smh: boolean
    stronger_than_soxx: boolean
    tickers: string[]
  }[]
  add_candidates: { ticker: string }[]
  do_not_buy: { ticker: string }[]
}

export async function sendChat(message: string): Promise<ChatResponse> {
  const resp = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!resp.ok) throw new Error(`API error: ${resp.status}`)
  return resp.json()
}

export async function getMarketSummary(): Promise<MarketSummary> {
  const resp = await fetch(`${API_BASE}/market/summary`)
  if (!resp.ok) throw new Error(`API error: ${resp.status}`)
  return resp.json()
}

export async function getHealth(): Promise<{ status: string }> {
  const resp = await fetch(`${API_BASE}/health`)
  if (!resp.ok) throw new Error(`API error: ${resp.status}`)
  return resp.json()
}
