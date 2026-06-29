import { useState, useEffect, useRef } from 'react'
import StatusBar from './components/StatusBar'
import MessageList from './components/MessageList'
import type { Message } from './components/MessageList'
import QuickActions from './components/QuickActions'
import ChatInput from './components/ChatInput'
import { sendChat, getHealth, getMarketSummary, getSleepPlan, getDailyPlan, getPortfolio, parsePortfolio, confirmPortfolio, getTradeHistory, getDashboard, getTechnical, getTickerScore, getExitPlan } from './api'
import type { MarketSummary } from './api'

export default function App() {
    const [messages, setMessages] = useState<Message[]>([])
    const [loading, setLoading] = useState(false)
    const [regime, setRegime] = useState('')
    const [connected, setConnected] = useState(false)
    const [enhance, setEnhance] = useState(false)
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
        if (message === '__DASHBOARD__') {
            setMessages((prev) => [...prev, { role: 'user', content: '🎯 仪表盘报告' }])
            setLoading(true)
            try {
                const data = await getDashboard(enhance)
                setMessages((prev) => [...prev, { role: 'assistant', content: data.report }])
                setConnected(true)
            } catch (err) {
                setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
            } finally {
                setLoading(false)
            }
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
        if (message === '__DAILY_PLAN__') {
            setMessages((prev) => [...prev, { role: 'user', content: '🎯 每日计划' }])
            setLoading(true)
            try {
                const data = await getDailyPlan()
                setMessages((prev) => [...prev, { role: 'assistant', content: formatDailyPlan(data) }])
                setConnected(true)
            } catch (err) {
                setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
            } finally {
                setLoading(false)
            }
            return
        }
        if (message === '__EXIT_PLAN__') {
            setMessages((prev) => [...prev, { role: 'user', content: '📉 持仓管理' }])
            setLoading(true)
            try {
                const data = await getExitPlan()
                setMessages((prev) => [...prev, { role: 'assistant', content: formatExitPlan(data) }])
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
        // Handle "加现金 5000" or "入金 2000" or "取现 1000"
        const cashMatch = message.match(/(?:加现金|入金|存入|deposit)\s*\$?(\d+(?:\.\d+)?)/i) || message.match(/(?:取现|取出|withdrawal)\s*\$?(\d+(?:\.\d+)?)/i)
        if (cashMatch) {
            const isWithdraw = /取现|取出|withdrawal/i.test(message)
            const amount = isWithdraw ? -parseFloat(cashMatch[1]) : parseFloat(cashMatch[1])
            const resp = await fetch('/api/portfolio/cash', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount, reason: message }),
            })
            const data = await resp.json()
            if (data.status === 'ok') {
                return `✅ ${isWithdraw ? '取出' : '入金'} $${Math.abs(amount).toLocaleString()}\n现金: $${data.cash_before.toLocaleString()} → $${data.cash_after.toLocaleString()}`
            }
            return `❌ 操作失败: ${data.message || '未知错误'}`
        }
        if (message.includes('挂单') || message.includes('睡前') || message.includes('睡觉')) {
            const data = await getSleepPlan(enhance)
            return formatSleepPlan(data)
        }
        if (message.includes('盯盘') || message.includes('报告') || message.includes('总结')) {
            const data = await getMarketSummary(enhance)
            return formatMarketSummary(data)
        }
        if (message.includes('仪表盘') || message.includes('dashboard')) {
            const data = await getDashboard(enhance)
            return data.report
        }
        if (message.includes('持仓管理') || message.includes('退出') || message.includes('止盈') || message.includes('止损') || message.includes('exit plan')) {
            const data = await getExitPlan()
            return formatExitPlan(data)
        }
        // Handle "评分 MU" or "MU评分" or "score NVDA" style queries
        const scoreMatch = message.match(/(?:评分|score|打分|挂单价)\s*([A-Z]{1,5})/i) || message.match(/([A-Z]{2,5})\s*(?:评分|打分|score|几分|多少分)/i)
        if (scoreMatch) {
            const ticker = scoreMatch[1].toUpperCase()
            const data = await getTickerScore(ticker)
            return formatTickerScore(data)
        }
        // Handle "查 NVDA" or "NVDA技术" style queries for single ticker TA
        const taMatch = message.match(/(?:查|技术|分析)\s*([A-Z]{1,5})/i) || message.match(/([A-Z]{2,5})\s*(?:技术|支撑|压力|RSI)/i)
        if (taMatch) {
            const ticker = taMatch[1].toUpperCase()
            const data = await getTechnical(ticker)
            return formatTechnical(data)
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

function formatMarketSummary(data: Record<string, unknown> | MarketSummary): string {
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
    const d = data as { market_regime?: string; orders?: { ticker: string; bucket_label: string; suggested_limit_low: number; suggested_limit_high: number; max_dollars: number; reason: string }[]; llm_analysis?: string }
    let text = `**😴 睡觉挂单计划** (市场: ${d.market_regime || 'unknown'})\n\n`
    if (d.orders?.length) {
        for (const o of d.orders) {
            text += `• **${o.ticker}** (${o.bucket_label}): $${o.suggested_limit_low.toFixed(2)} - $${o.suggested_limit_high.toFixed(2)}, 最多$${o.max_dollars}\n`
        }
    } else {
        text += '当前无挂单建议\n'
    }
    if (d.llm_analysis) {
        text += `\n---\n**🤖 AI 建议**:\n${d.llm_analysis}`
    }
    return text
}

function formatDailyPlan(data: Record<string, unknown>): string {
    const d = data as {
        market_regime_label?: string
        sector_pct_change?: number
        scored_stocks?: { ticker: string; score: number; category: string; action: string; reasons: string[] }[]
        limit_orders?: { ticker: string; score: number; category: string; current_price: number; limit_1: number; limit_2: number; amount_l1: number; amount_l2: number; limit_reason: string; reasons: string[]; capped_reason?: string }[]
        total_order_amount?: number
        max_daily_amount?: number
    }

    let text = `## 🎯 每日计划\n\n`
    text += `**市场**: ${d.market_regime_label || '未知'} | **板块(SMH)**: ${(d.sector_pct_change || 0) >= 0 ? '+' : ''}${(d.sector_pct_change || 0).toFixed(2)}%\n\n`

    // Limit orders (the main output)
    if (d.limit_orders?.length) {
        text += `### 📋 挂单计划 (${d.limit_orders.length}只)\n\n`
        for (const o of d.limit_orders) {
            const catLabel = { core: '核心', semi_core: '半核心', cyclical: '周期', high_beta: '高弹性', beta: '弹性' }[o.category] || o.category
            text += `**${o.ticker}** [${catLabel}] 评分${o.score}\n`
            text += `  现价 $${o.current_price} → 浅挂 $${o.limit_1.toFixed(2)} ($${o.amount_l1}) | 深挂 $${o.limit_2.toFixed(2)} ($${o.amount_l2})\n`
            text += `  💡 ${o.limit_reason}`
            if (o.reasons?.length) text += ` | ${o.reasons.join(', ')}`
            if (o.capped_reason) text += ` ⚠️${o.capped_reason}`
            text += '\n\n'
        }
        text += `---\n💰 总挂单: $${(d.total_order_amount || 0).toLocaleString()} / 上限$${(d.max_daily_amount || 0).toLocaleString()}\n\n`
    } else {
        text += '### 无挂单建议\n当前无满足条件的候选股\n\n'
    }

    // Top scored stocks summary
    if (d.scored_stocks?.length) {
        text += `### 📊 评分排行 (前10)\n`
        for (const s of d.scored_stocks.slice(0, 10)) {
            const icon = s.action === 'preferred_buy' ? '🟢' : s.action === 'buy_candidate' ? '🟡' : s.action === 'watch_only' ? '⚪' : '🔴'
            text += `${icon} **${s.ticker}** ${s.score}分 (${s.category})`
            if (s.reasons?.length) text += ` - ${s.reasons.join(', ')}`
            text += '\n'
        }
    }

    return text
}

function formatExitPlan(data: Record<string, unknown>): string {
    const d = data as {
        marketRegime?: string
        portfolioRisk?: { riskLevel?: string; equityExposurePct?: number } | string
        summary?: { holdCount: number; watchCount: number; trimCount: number; exitCount: number }
        exitPlans?: {
            ticker: string; type: string; action: string; confidence: string
            currentPrice: number; averageCost: number; gainPct: number; shares: number
            reasoning?: string[]; trimPlan?: { trigger: string; price: number }[]
            riskPlan?: { trigger: string; price: number }[]
        }[]
        generated_at?: string
    }

    let text = `## 📉 持仓管理\n\n`
    const riskLabel = typeof d.portfolioRisk === 'object' ? d.portfolioRisk?.riskLevel : d.portfolioRisk
    text += `**市场**: ${d.marketRegime || '未知'} | **组合风险**: ${riskLabel || '未知'}\n`

    if (d.summary) {
        const s = d.summary
        text += `持有 ${s.holdCount} | 观察 ${s.watchCount} | 减仓 ${s.trimCount} | 退出 ${s.exitCount}\n\n`
    }

    if (d.exitPlans?.length) {
        const actionIcon: Record<string, string> = {
            EXIT: '🔴', REDUCE_2_3: '🟠', TRIM_1_2: '🟡', TRIM_1_3: '🟡', WATCH: '👀', HOLD: '🟢',
        }
        const typeLabel: Record<string, string> = { CORE: '核心', SEMI_CORE: '半核心', CYCLICAL: '周期', HIGH_BETA: '高弹性', LEVERAGED_ETF: '杠杆ETF' }
        for (const p of d.exitPlans) {
            const icon = actionIcon[p.action] || '⚪'
            const pnlSign = p.gainPct >= 0 ? '+' : ''
            text += `${icon} **${p.ticker}** [${typeLabel[p.type] || p.type}] → **${p.action}** (${p.confidence})\n`
            text += `  ${p.shares}股 成本$${p.averageCost.toFixed(2)} 现价$${p.currentPrice.toFixed(2)} ${pnlSign}${p.gainPct.toFixed(1)}%\n`
            if (p.reasoning?.length) {
                text += `  💡 ${p.reasoning.join('; ')}\n`
            }
            if (p.trimPlan?.length) {
                for (const tp of p.trimPlan) {
                    text += `  📈 ${tp.trigger}: $${tp.price.toFixed(2)}\n`
                }
            }
            if (p.riskPlan?.length) {
                for (const rp of p.riskPlan) {
                    text += `  🛑 ${rp.trigger}: $${rp.price.toFixed(2)}\n`
                }
            }
            text += '\n'
        }
    } else {
        text += '当前无持仓\n'
    }

    if (d.generated_at) text += `---\n⏰ ${d.generated_at}\n`
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

function formatTickerScore(data: Record<string, unknown>): string {
    const d = data as {
        ticker?: string; error?: string; current_price?: number; score?: number
        category?: string; chain?: string; action?: string; reasons?: string[]
        limit_1?: number; limit_2?: number; limit_reason?: string
        amount_l1?: number; amount_l2?: number; capped_reason?: string
        amount_multipliers?: { market?: number; stock?: number; position?: number }
    }
    if (d.error) return `**${d.ticker}** 评分失败: ${d.error}`

    const catLabel = { core: '核心', semi_core: '半核心', cyclical: '周期', high_beta: '高弹性', beta: '弹性' }[d.category || ''] || d.category
    const actionLabel = { preferred_buy: '🟢 优先买入', buy_candidate: '🟡 挂单候选', watch_only: '⚪ 仅观察', do_not_buy: '🔴 不建议' }[d.action || ''] || d.action

    let text = `## ${d.ticker} 评分报告\n\n`
    text += `**评分**: ${d.score} | **类别**: ${catLabel} | **判定**: ${actionLabel}\n`
    if (d.chain) text += `**产业链**: ${d.chain}\n`
    text += `**现价**: $${d.current_price}\n\n`

    if (d.reasons?.length) text += `**理由**: ${d.reasons.join(', ')}\n\n`

    text += `### 挂单建议\n`
    text += `• 浅挂(Tier1): **$${d.limit_1?.toFixed(2)}** → $${d.amount_l1}\n`
    text += `• 深挂(Tier2): **$${d.limit_2?.toFixed(2)}** → $${d.amount_l2}\n`
    text += `• 方法: ${d.limit_reason}\n`

    if (d.amount_multipliers) {
        text += `• 乘数: 市场×${d.amount_multipliers.market} 个股×${d.amount_multipliers.stock} 仓位×${d.amount_multipliers.position}\n`
    }
    if (d.capped_reason) text += `• ⚠️ ${d.capped_reason}\n`

    return text
}

function formatTechnical(data: Record<string, unknown>): string {
    const d = data as {
        ticker?: string; error?: string
        ma5?: number; ma10?: number; ma20?: number; ma60?: number
        rsi_14?: number; macd?: number; macd_signal?: number; macd_hist?: number
        support_levels?: number[]; resistance_levels?: number[]
        volume_ratio?: number; trend?: string
    }
    if (d.error) return `❌ ${d.ticker}: ${d.error}`

    const trendLabel = d.trend === 'up' ? '🟢 多头排列' : d.trend === 'down' ? '🔴 空头排列' : '🟡 震荡'
    let text = `**📈 ${d.ticker} 技术分析**\n\n`
    text += `**趋势**: ${trendLabel}\n`
    text += `**均线**: MA5=${d.ma5} | MA10=${d.ma10} | MA20=${d.ma20} | MA60=${d.ma60}\n`
    text += `**RSI(14)**: ${d.rsi_14}\n`
    text += `**MACD**: DIF=${d.macd} | Signal=${d.macd_signal} | 柱=${d.macd_hist}\n`
    text += `**量比**: ${d.volume_ratio}x\n`
    if (d.support_levels?.length) {
        text += `**支撑位**: ${d.support_levels.map(s => `$${s}`).join(', ')}\n`
    }
    if (d.resistance_levels?.length) {
        text += `**压力位**: ${d.resistance_levels.map(r => `$${r}`).join(', ')}\n`
    }
    return text
}
