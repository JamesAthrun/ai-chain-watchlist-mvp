import { useState, useEffect, useRef } from 'react'
import StatusBar from './components/StatusBar'
import MessageList from './components/MessageList'
import type { Message } from './components/MessageList'
import QuickActions from './components/QuickActions'
import ChatInput from './components/ChatInput'
import { sendChat, getHealth, getMarketSummary, getSleepPlan, getPortfolio } from './api'

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [regime, setRegime] = useState('')
  const [connected, setConnected] = useState(false)
  const [enhance, setEnhance] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Check backend connection on mount
  useEffect(() => {
    getHealth()
      .then(() => setConnected(true))
      .catch(() => setConnected(false))
  }, [])

  // Auto scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const handleSend = async (message: string) => {
    // Add user message
    setMessages((prev) => [...prev, { role: 'user', content: message }])
    setLoading(true)

    try {
      // Check if it's a quick action that can use direct API + enhance
      const directResult = await handleDirectApi(message)
      if (directResult) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: directResult },
        ])
      } else {
        const resp = await sendChat(message)
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: resp.answer,
            regime: resp.market_regime,
            time: resp.generated_at,
          },
        ])
        if (resp.market_regime) {
          setRegime(resp.market_regime)
        }
      }
      setConnected(true)
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}`,
        },
      ])
      setConnected(false)
    } finally {
      setLoading(false)
    }
  }

  const handleDirectApi = async (message: string): Promise<string | null> => {
    // Route specific quick actions to direct API calls with enhance
    if (message.includes('仓位')) {
      const data = await getPortfolio(enhance)
      return formatPortfolio(data)
    }
    if (message.includes('挂单') || message.includes('睡前') || message.includes('睡觉')) {
      const data = await getSleepPlan(enhance)
      return formatSleepPlan(data)
    }
    if (message.includes('盯盘') || message.includes('报告') || message.includes('总结')) {
      const data = await getMarketSummary(enhance)
      return formatMarketSummary(data)
    }
    return null // Fall through to chat API
  }

  return (
    <div className="flex flex-col h-dvh bg-gray-900">
      <StatusBar regime={regime} connected={connected} enhance={enhance} onToggleEnhance={() => setEnhance(!enhance)} />
      <div className="flex-1 overflow-y-auto hide-scrollbar p-4 space-y-3">
        <MessageList messages={messages} loading={loading} />
        <div ref={messagesEndRef} />
      </div>
      <QuickActions onAction={handleSend} disabled={loading} />
      <ChatInput onSend={handleSend} disabled={loading} />
    </div>
  )
}

function formatMarketSummary(data: Record<string, unknown>): string {
  const d = data as { market_regime?: string; bucket_scores?: { label: string; avg_pct_change: number }[]; add_candidates?: { ticker: string }[]; do_not_buy?: { ticker: string }[]; llm_analysis?: string }
  let text = `**市场状态**: ${d.market_regime || 'unknown'}\n\n`
  if (d.bucket_scores) {
    text += '**板块表现**:\n'
    for (const b of d.bucket_scores) {
      text += `• ${b.label}: ${b.avg_pct_change > 0 ? '+' : ''}${b.avg_pct_change}%\n`
    }
  }
  if (d.add_candidates?.length) {
    text += `\n**加仓候选**: ${d.add_candidates.map((c) => c.ticker).join(', ')}\n`
  }
  if (d.do_not_buy?.length) {
    text += `\n**避雷**: ${d.do_not_buy.map((c) => c.ticker).join(', ')}\n`
  }
  if (d.llm_analysis) {
    text += `\n---\n**🤖 AI 分析**:\n${d.llm_analysis}`
  }
  return text
}

function formatSleepPlan(data: Record<string, unknown>): string {
  const d = data as { market_regime?: string; orders?: { ticker: string; limit_price: number; discount_pct: number }[]; llm_analysis?: string }
  let text = `**挂单计划** (市场: ${d.market_regime || 'unknown'})\n\n`
  if (d.orders?.length) {
    for (const o of d.orders) {
      text += `• ${o.ticker}: $${o.limit_price.toFixed(2)} (折扣 ${o.discount_pct}%)\n`
    }
  } else {
    text += '当前无挂单建议\n'
  }
  if (d.llm_analysis) {
    text += `\n---\n**🤖 AI 建议**:\n${d.llm_analysis}`
  }
  return text
}

function formatPortfolio(data: Record<string, unknown>): string {
  const d = data as { account_value?: number; cash?: number; cash_pct?: number; positions?: { ticker: string; shares: number; market_value?: number }[]; llm_analysis?: string }
  let text = `**仓位概览**\n`
  text += `• 总资产: $${(d.account_value || 0).toLocaleString()}\n`
  text += `• 现金: $${(d.cash || 0).toLocaleString()} (${(d.cash_pct || 0).toFixed(1)}%)\n\n`
  if (d.positions?.length) {
    text += '**持仓**:\n'
    for (const p of d.positions) {
      text += `• ${p.ticker}: ${p.shares}股${p.market_value ? ` ($${p.market_value.toLocaleString()})` : ''}\n`
    }
  } else {
    text += '当前无持仓（全现金）\n'
  }
  if (d.llm_analysis) {
    text += `\n---\n**🤖 AI 建议**:\n${d.llm_analysis}`
  }
  return text
}
