import { useState, useEffect, useRef } from 'react'
import StatusBar from './components/StatusBar'
import MessageList from './components/MessageList'
import type { Message } from './components/MessageList'
import QuickActions from './components/QuickActions'
import ChatInput from './components/ChatInput'
import { sendChat, getHealth, getMarketSummary, getSleepPlan, getPortfolio, parsePortfolio, confirmPortfolio, getTradeHistory } from './api'

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [regime, setRegime] = useState('')
  const [connected, setConnected] = useState(false)
  const [enhance, setEnhance] = useState(true)
  const [pendingTrade, setPendingTrade] = useState<Record<string, unknown> | null>(null)
  const [tradeMode, setTradeMode] = useState(false)
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
    // Handle special quick action triggers
    if (message === '__TRADE_INPUT__') {
      setTradeMode(true)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '📝 请描述你的交易，例如：\n• "买了100股NVDA 均价135"\n• "卖了50股AVGO 180块"\n• "我现在持有 NVDA 200股成本130，MRVL 100股成本80"' },
      ])
      return
    }
    if (message === '__TRADE_HISTORY__') {
      setMessages((prev) => [...prev, { role: 'user', content: '查看交易记录' }])
      setLoading(true)
      try {
        const data = await getTradeHistory(20)
        setMessages((prev) => [...prev, { role: 'assistant', content: formatTradeHistory(data) }])
        setConnected(true)
      } catch (err) {
        setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
      } finally {
        setLoading(false)
      }
      return
    }

    // Handle confirm/cancel for pending trade
    if (pendingTrade) {
      if (message === '__CONFIRM__' || message.includes('确认') || message.toLowerCase() === 'y') {
        setMessages((prev) => [...prev, { role: 'user', content: '✅ 确认' }])
        setLoading(true)
        try {
          const result = await confirmPortfolio(pendingTrade)
          const status = (result as { status: string }).status
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: status === 'ok' ? '✅ 已记录！你可以点「💼 仓位」查看最新仓位。' : `❌ 记录失败: ${(result as { message?: string }).message || '未知错误'}`,
          }])
        } catch (err) {
          setMessages((prev) => [...prev, { role: 'assistant', content: `记录失败: ${err instanceof Error ? err.message : '未知错误'}` }])
        } finally {
          setPendingTrade(null)
          setTradeMode(false)
          setLoading(false)
        }
        return
      }
      if (message === '__CANCEL__' || message.includes('取消') || message.toLowerCase() === 'n') {
        setMessages((prev) => [...prev, { role: 'user', content: '❌ 取消' }, { role: 'assistant', content: '已取消，未做任何更改。' }])
        setPendingTrade(null)
        setTradeMode(false)
        return
      }
    }

    // Trade mode: parse natural language
    if (tradeMode) {
      // If user clicks a non-trade quick action, exit trade mode and handle normally
      const isQuickAction = message === '盯盘报告' || message === '睡前挂单计划' ||
        message === '哪个板块强' || message === '不能接的标的' || message === '我的仓位情况'
      if (isQuickAction) {
        setTradeMode(false)
      } else {
        setMessages((prev) => [...prev, { role: 'user', content: message }])
        setLoading(true)
        try {
          const result = await parsePortfolio(message)
          if (result.status === 'ok' && result.parsed) {
            setPendingTrade(result.parsed)
            setMessages((prev) => [...prev, {
              role: 'assistant',
              content: `${result.preview}\n\n请回复「确认」执行，或「取消」放弃。`,
            }])
          } else {
            setMessages((prev) => [...prev, { role: 'assistant', content: `解析失败: ${result.message || '请重新描述'}` }])
          }
          setConnected(true)
        } catch (err) {
          setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
        } finally {
          setLoading(false)
        }
        return
      }
    }

    // Normal message flow
    setMessages((prev) => [...prev, { role: 'user', content: message }])
    setLoading(true)

    try {
      const directResult = await handleDirectApi(message)
      if (directResult) {
        setMessages((prev) => [...prev, { role: 'assistant', content: directResult }])
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
    return null
  }

  return (
    <div className="flex flex-col h-dvh bg-gray-900">
      <StatusBar regime={regime} connected={connected} enhance={enhance} onToggleEnhance={() => setEnhance(!enhance)} />
      <div className="flex-1 overflow-y-auto hide-scrollbar p-4 space-y-3">
        <MessageList messages={messages} loading={loading} />
        <div ref={messagesEndRef} />
      </div>
      {pendingTrade ? (
        <div className="flex gap-2 px-4 py-2 shrink-0">
          <button onClick={() => handleSend('__CONFIRM__')} className="flex-1 py-2 text-sm font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg">✅ 确认记录</button>
          <button onClick={() => handleSend('__CANCEL__')} className="flex-1 py-2 text-sm font-medium bg-red-600 hover:bg-red-500 text-white rounded-lg">❌ 取消</button>
        </div>
      ) : (
        <QuickActions onAction={handleSend} disabled={loading} />
      )}
      <ChatInput onSend={handleSend} disabled={loading} placeholder={tradeMode ? '描述交易，如：买了100股NVDA 均价135' : undefined} />
    </div>
  )
}

function formatTradeHistory(data: { trades: Record<string, unknown>[]; count: number }): string {
  if (!data.trades.length) return '暂无交易记录'
  let text = `**最近 ${data.count} 条交易记录**:\n\n`
  for (const t of data.trades) {
    const action = t.action === 'buy' ? '买入' : t.action === 'sell' ? '卖出' : String(t.action)
    if (t.ticker) {
      text += `• ${t.timestamp} | ${action} ${t.ticker} ${t.shares}股 @ $${t.price}\n`
      text += `  现金: $${Number(t.cash_before).toLocaleString()} → $${Number(t.cash_after).toLocaleString()}\n`
    } else {
      text += `• ${t.timestamp} | ${action} | ${t.notes || ''}\n`
    }
  }
  return text
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
