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
    llm_analysis?: string | null
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

export async function getMarketSummary(enhance = false): Promise<MarketSummary> {
    const resp = await fetch(`${API_BASE}/market/summary?enhance=${enhance}`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function getSleepPlan(enhance = false): Promise<Record<string, unknown>> {
    const resp = await fetch(`${API_BASE}/sleep-plan?enhance=${enhance}`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function getDailyPlan(): Promise<Record<string, unknown>> {
    const resp = await fetch(`${API_BASE}/daily-plan`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function getPortfolio(enhance = false): Promise<Record<string, unknown>> {
    const resp = await fetch(`${API_BASE}/portfolio?enhance=${enhance}`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function getHealth(): Promise<{ status: string }> {
    const resp = await fetch(`${API_BASE}/health`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function parsePortfolio(text: string): Promise<{ status: string; parsed?: Record<string, unknown>; preview?: string; message?: string }> {
    const resp = await fetch(`${API_BASE}/portfolio/parse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
    })
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function confirmPortfolio(parsed: Record<string, unknown>): Promise<Record<string, unknown>> {
    const resp = await fetch(`${API_BASE}/portfolio/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parsed }),
    })
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function getTradeHistory(limit = 50): Promise<{ trades: Record<string, unknown>[]; count: number }> {
    const resp = await fetch(`${API_BASE}/portfolio/history?limit=${limit}`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export interface DashboardResponse {
    report: string
    generated_at: string | null
}

export async function getDashboard(enhance = false): Promise<DashboardResponse> {
    const resp = await fetch(`${API_BASE}/market/dashboard?enhance=${enhance}`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function getTechnical(ticker: string): Promise<Record<string, unknown>> {
    const resp = await fetch(`${API_BASE}/market/technical/${ticker.toUpperCase()}`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}

export async function getTickerScore(ticker: string): Promise<Record<string, unknown>> {
    const resp = await fetch(`${API_BASE}/market/score/${ticker.toUpperCase()}`)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    return resp.json()
}
