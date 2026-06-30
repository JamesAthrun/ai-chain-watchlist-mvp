import { useState, useEffect, useRef } from 'react'
import StatusBar from './components/StatusBar'
import MessageList from './components/MessageList'
import type { Message } from './components/MessageList'
import QuickActions from './components/QuickActions'
import ChatInput from './components/ChatInput'
import { sendChat, getHealth, getMarketSummary, getSleepPlan, getDailyPlan, getPortfolio, parsePortfolio, confirmPortfolio, getTradeHistory, getDashboard, getTechnical, getTickerScore, getExitPlan, postAIExitAnalysis, getGlobalMarket, getDecisions, createTrade, getNewTrades, getRebuildPositions, adjustCash } from './api'
import type { MarketSummary } from './api'

export default function App() {
    const [messages, setMessages] = useState<Message[]>([])
    const [loading, setLoading] = useState(false)
    const [regime, setRegime] = useState('')
    const [connected, setConnected] = useState(false)
    const [enhance, setEnhance] = useState(false)
    const [pendingTrade, setPendingTrade] = useState<Record<string, unknown> | null>(null)
    const [tradeMode, setTradeMode] = useState(false)
    const [cashMode, setCashMode] = useState(false)
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
        if (message === '__CASH_ADJUST__') {
            setCashMode(true)
            setMessages((prev) => [
                ...prev,
                { role: 'assistant', content: '💰 请输入现金调整：\n• 正数 = 入金，如 "5000" 或 "入金5000"\n• 负数 = 出金，如 "-2000" 或 "出金2000"' },
            ])
            return
        }
        if (message === '__DECISIONS__') {
            setMessages((prev) => [...prev, { role: 'user', content: enhance ? '🧠 决策中心 (AI增强)' : '🧠 决策中心' }])
            setLoading(true)
            try {
                const data = await getDecisions()
                let content = formatDecisions(data)
                if (enhance) {
                    try {
                        const aiResp = await sendChat(`请根据以下决策中心数据，给出今日操作优先级建议（最多3条），重点关注信号冲突和最佳机会：\n${content}`)
                        content += `\n\n---\n### 🤖 AI 建议\n${aiResp.answer || ''}`
                    } catch {
                        content += '\n\n> ⚠️ AI 增强分析暂不可用'
                    }
                }
                setMessages((prev) => [...prev, { role: 'assistant', content }])
                setConnected(true)
            } catch (err) {
                setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
            } finally {
                setLoading(false)
            }
            return
        }
        if (message === '__GLOBAL_MARKET__') {
            setMessages((prev) => [...prev, { role: 'user', content: enhance ? '🌍 全球市场 (AI增强)' : '🌍 全球市场' }])
            setLoading(true)
            try {
                const data = await getGlobalMarket(false)
                let content = formatGlobalMarket(data)
                if (enhance) {
                    try {
                        const aiResp = await sendChat(`请根据以下全球市场数据，分析当前市场环境对我的持仓影响，给出风险提示和机会建议（最多3条）：\n${content}`)
                        content += `\n\n---\n### 🤖 AI 建议\n${aiResp.answer || ''}`
                    } catch {
                        content += '\n\n> ⚠️ AI 增强分析暂不可用'
                    }
                }
                setMessages((prev) => [...prev, { role: 'assistant', content }])
                setConnected(true)
            } catch (err) {
                setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
            } finally {
                setLoading(false)
            }
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
            setMessages((prev) => [...prev, { role: 'user', content: enhance ? '📝 交易记录 (AI增强)' : '查看交易记录' }])
            setLoading(true)
            try {
                const data = await getNewTrades(undefined, 20)
                let content = formatNewTradeHistory(data)
                if (enhance) {
                    try {
                        const aiResp = await sendChat(`请根据以下近期交易记录，分析交易模式和改进建议（最多3条）：\n${content}`)
                        content += `\n\n---\n### 🤖 AI 建议\n${aiResp.answer || ''}`
                    } catch {
                        content += '\n\n> ⚠️ AI 增强分析暂不可用'
                    }
                }
                setMessages((prev) => [...prev, { role: 'assistant', content }])
                setConnected(true)
            } catch (err) {
                setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
            } finally {
                setLoading(false)
            }
            return
        }
        if (message === '__DAILY_PLAN__') {
            setMessages((prev) => [...prev, { role: 'user', content: enhance ? '🎯 每日计划 (AI增强)' : '🎯 每日计划' }])
            setLoading(true)
            try {
                const data = await getDailyPlan()
                let content = formatDailyPlan(data)
                if (enhance) {
                    try {
                        const aiResp = await sendChat(`请根据以下每日交易计划数据，给出执行优先级建议和需要特别注意的风险点（最多3条）：\n${content}`)
                        content += `\n\n---\n### 🤖 AI 建议\n${aiResp.answer || ''}`
                    } catch {
                        content += '\n\n> ⚠️ AI 增强分析暂不可用'
                    }
                }
                setMessages((prev) => [...prev, { role: 'assistant', content }])
                setConnected(true)
            } catch (err) {
                setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
            } finally {
                setLoading(false)
            }
            return
        }
        if (message === '__EXIT_PLAN__') {
            setMessages((prev) => [...prev, { role: 'user', content: enhance ? '📉 持仓管理 (AI增强)' : '📉 持仓管理' }])
            setLoading(true)
            try {
                const data = await getExitPlan()
                let content = formatExitPlan(data)
                if (enhance) {
                    try {
                        const aiData = await postAIExitAnalysis()
                        content += '\n\n' + formatAIExitAnalysis(aiData)
                    } catch (aiErr) {
                        content += '\n\n> ⚠️ AI 增强分析暂不可用'
                    }
                }
                setMessages((prev) => [...prev, { role: 'assistant', content }])
                setConnected(true)
            } catch (err) {
                setMessages((prev) => [...prev, { role: 'assistant', content: `请求失败: ${err instanceof Error ? err.message : '未知错误'}` }])
            } finally {
                setLoading(false)
            }
            return
        }
        if (message === '__PULLBACK_ADD__') {
            // Pullback add plan is now merged into exit-plan
            // Redirect to exit plan
            return handleSend('__EXIT_PLAN__')
        }

        // Handle confirm/cancel for pending trade
        if (pendingTrade) {
            if (message === '__CONFIRM__' || message.includes('确认') || message.toLowerCase() === 'y') {
                setMessages((prev) => [...prev, { role: 'user', content: '✅ 确认' }])
                setLoading(true)
                try {
                    if (pendingTrade._legacy) {
                        // Legacy portfolio confirm path
                        const { _legacy, ...parsed } = pendingTrade
                        const result = await confirmPortfolio(parsed)
                        const status = (result as { status: string }).status
                        setMessages((prev) => [...prev, {
                            role: 'assistant',
                            content: status === 'ok' ? '✅ 已记录！你可以点「📉 持仓」查看最新仓位。' : `❌ 记录失败: ${(result as { message?: string }).message || '未知错误'}`,
                        }])
                    } else {
                        // New trade ledger path
                        const result = await createTrade({
                            symbol: pendingTrade.symbol as string,
                            side: pendingTrade.side as string,
                            quantity: pendingTrade.quantity as number,
                            price: pendingTrade.price as number,
                            source: 'MANUAL',
                        })
                        const status = (result as { status: string }).status
                        const sideLabel = pendingTrade.side === 'BUY' ? '买入' : '卖出'
                        setMessages((prev) => [...prev, {
                            role: 'assistant',
                            content: status === 'ok'
                                ? `✅ 已记录 ${sideLabel} ${pendingTrade.symbol} ${pendingTrade.quantity}股 @ $${pendingTrade.price}！\n点「📉 持仓」查看最新仓位。`
                                : `❌ 记录失败: ${(result as { message?: string }).message || '未知错误'}`,
                        }])
                    }
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

        // Cash adjust mode
        if (cashMode) {
            setMessages((prev) => [...prev, { role: 'user', content: message }])
            setLoading(true)
            try {
                const depositMatch = message.match(/入金\s*(\d+(?:\.\d+)?)/)
                const withdrawMatch = message.match(/出金\s*(\d+(?:\.\d+)?)/)
                let amount: number
                let reason: string
                if (depositMatch) {
                    amount = parseFloat(depositMatch[1])
                    reason = '入金'
                } else if (withdrawMatch) {
                    amount = -parseFloat(withdrawMatch[1])
                    reason = '出金'
                } else {
                    amount = parseFloat(message.replace(/[^\d.-]/g, ''))
                    reason = amount >= 0 ? '入金' : '出金'
                }
                if (isNaN(amount) || amount === 0) {
                    setMessages((prev) => [...prev, { role: 'assistant', content: '❌ 无法识别金额，请输入数字，如 "5000" 或 "出金2000"' }])
                } else {
                    const result = await adjustCash(amount, reason) as { cash_after?: number }
                    const direction = amount > 0 ? '入金' : '出金'
                    setMessages((prev) => [...prev, { role: 'assistant', content: `✅ ${direction} $${Math.abs(amount).toLocaleString()} 成功！\n当前现金: $${(result.cash_after ?? 0).toLocaleString()}` }])
                }
            } catch (err) {
                setMessages((prev) => [...prev, { role: 'assistant', content: `操作失败: ${err instanceof Error ? err.message : '未知错误'}` }])
            } finally {
                setCashMode(false)
                setLoading(false)
            }
            return
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
                    // Try direct trade parsing: "买了100股NVDA 均价135" or "卖了50股AVGO 180块"
                    const buyMatch = message.match(/买[了入]?\s*(\d+(?:\.\d+)?)\s*股?\s*([A-Z]{1,5})\s*(?:均价|@|价格?)\s*\$?(\d+(?:\.\d+)?)/i) ||
                        message.match(/买[了入]?\s*([A-Z]{1,5})\s*(\d+(?:\.\d+)?)\s*股?\s*(?:均价|@|价格?)\s*\$?(\d+(?:\.\d+)?)/i)
                    const sellMatch = message.match(/卖[了出]?\s*(\d+(?:\.\d+)?)\s*股?\s*([A-Z]{1,5})\s*(?:均价|@|价格?)\s*\$?(\d+(?:\.\d+)?)/i) ||
                        message.match(/卖[了出]?\s*([A-Z]{1,5})\s*(\d+(?:\.\d+)?)\s*股?\s*(?:均价|@|价格?)\s*\$?(\d+(?:\.\d+)?)/i)

                    if (buyMatch || sellMatch) {
                        const match = (buyMatch || sellMatch)!
                        const side = buyMatch ? 'BUY' : 'SELL'
                        // Determine which capture group is the ticker vs quantity
                        let symbol: string, quantity: number, price: number
                        if (/^[A-Z]/i.test(match[1])) {
                            symbol = match[1].toUpperCase()
                            quantity = parseFloat(match[2])
                            price = parseFloat(match[3])
                        } else {
                            quantity = parseFloat(match[1])
                            symbol = match[2].toUpperCase()
                            price = parseFloat(match[3])
                        }
                        const total = (quantity * price).toFixed(2)
                        const sideLabel = side === 'BUY' ? '买入' : '卖出'
                        setPendingTrade({ symbol, side, quantity, price })
                        setMessages((prev) => [...prev, {
                            role: 'assistant',
                            content: `${sideLabel} ${symbol} ${quantity}股 @ $${price} (总计 $${total})\n\n请回复「确认」执行，或「取消」放弃。`,
                        }])
                    } else {
                        // Fallback to old parsePortfolio for complex inputs
                        const result = await parsePortfolio(message)
                        if (result.status === 'ok' && result.parsed) {
                            setPendingTrade({ ...result.parsed, _legacy: true })
                            setMessages((prev) => [...prev, {
                                role: 'assistant',
                                content: `${result.preview}\n\n请回复「确认」执行，或「取消」放弃。`,
                            }])
                        } else {
                            setMessages((prev) => [...prev, { role: 'assistant', content: `解析失败: ${result.message || '请重新描述'}` }])
                        }
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
            <ChatInput onSend={handleSend} disabled={loading} placeholder={tradeMode ? '描述交易，如：买了100股NVDA 均价135' : cashMode ? '输入金额，如：5000 或 出金2000' : undefined} />
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

function formatGlobalMarket(data: Record<string, unknown>): string {
    const d = data as {
        timestamp?: string
        markets?: { category: string; name: string; ticker: string; price: number | null; change_pct: number | null; currency: string; error?: string }[]
        error?: string
    }
    if (d.error && (!d.markets || d.markets.length === 0)) {
        return `⚠️ 全球市场数据获取失败: ${d.error}`
    }

    const lines: string[] = []
    const ts = d.timestamp ? new Date(d.timestamp).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '未知'
    lines.push(`🌍 **全球市场概览**`)
    lines.push(`📅 ${ts}\n`)

    let lastCategory = ''
    for (const m of d.markets || []) {
        if (m.category !== lastCategory) {
            if (lastCategory) lines.push('')
            lines.push(`**${m.category}**`)
            lastCategory = m.category
        }
        if (m.price == null || m.change_pct == null) {
            lines.push(`  ${m.name}: ⚠️ 暂无数据`)
            continue
        }
        const emoji = m.change_pct >= 0 ? '🟢' : '🔴'
        const sign = m.change_pct >= 0 ? '+' : ''
        const priceStr = m.price >= 10000 ? m.price.toLocaleString() : m.price.toFixed(2)
        lines.push(`  ${m.name}  ${priceStr}  ${emoji} ${sign}${m.change_pct.toFixed(2)}%`)
    }

    return lines.join('\n')
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
            trendStatus?: string
            reasoning?: string[]; trimPlan?: { trigger: string; price: number }[]
            riskPlan?: { trigger: string; price: number }[]
        }[]
        addOnPullback?: {
            summary?: {
                addSmallCount: number; addNormalCount: number; addDeepOnlyCount: number
                watchOnlyCount: number; doNotAddCount: number; reduceInsteadCount: number
                totalSuggestedAddAmount: number
            }
            plans?: {
                symbol: string; type: string; action: string
                currentPrice: number; averageCost: number
                singlePositionExposurePct: number
                trendStatus: string; pullbackStatus: string
                addLimits?: { level: number; price: number; amount: number; reason: string }[]
                invalidationTriggers?: { trigger: string; action: string }[]
                reasoning?: string[]
            }[]
        }
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
            EXIT: '🔴', REDUCE_2_3: '🟠', REDUCE_1_2: '🟡', REDUCE_1_3: '🟡',
            TRIM_RISK: '🟡', TRIM_PROFIT: '🟢', WATCH_PULLBACK: '👀', WATCH: '👀', HOLD: '🟢',
        }
        const typeLabel: Record<string, string> = { CORE: '核心', SEMI_CORE: '半核心', CYCLICAL: '周期', HIGH_BETA: '高弹性', LEVERAGED_ETF: '杠杆ETF' }
        const actionLabel: Record<string, string> = {
            HOLD: '持有', WATCH: '观察', WATCH_PULLBACK: '回调观察',
            TRIM_PROFIT: '止盈减仓', TRIM_RISK: '风控减仓',
            REDUCE_1_3: '减仓1/3', REDUCE_1_2: '减仓1/2', REDUCE_2_3: '减仓2/3', EXIT: '退出',
        }
        for (const p of d.exitPlans) {
            const icon = actionIcon[p.action] || '⚪'
            const pnlSign = p.gainPct >= 0 ? '+' : ''
            text += `${icon} **${p.ticker}** [${typeLabel[p.type] || p.type}] → **${actionLabel[p.action] || p.action}** (${p.confidence})\n`
            text += `  ${p.shares}股 成本$${p.averageCost.toFixed(2)} 现价$${p.currentPrice.toFixed(2)} ${pnlSign}${p.gainPct.toFixed(1)}%\n`
            if (p.trendStatus) {
                const trendLabel: Record<string, string> = {
                    STRONG_UPTREND: '📈 强势上升', PULLBACK_IN_UPTREND: '🔄 上升趋势回调',
                    SHORT_TERM_BREAK_ONLY: '⚡ 短期走弱', MEDIUM_TREND_BREAK: '⚠️ 中期破位',
                    LONG_TREND_BREAK: '🔴 长期破位', RELATIVE_UNDERPERFORMER: '📉 持续弱势',
                }
                text += `  ${trendLabel[p.trendStatus] || p.trendStatus}\n`
            }
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

    // Pullback add-on section
    if (d.addOnPullback?.plans?.length) {
        const pb = d.addOnPullback
        const addable = (pb.plans || []).filter(p => ['ADD_SMALL', 'ADD_NORMAL', 'ADD_DEEP_ONLY'].includes(p.action))
        const noAdd = (pb.plans || []).filter(p => ['DO_NOT_ADD', 'REDUCE_INSTEAD'].includes(p.action))

        if (addable.length > 0 || noAdd.length > 0) {
            text += `---\n### 🔄 回调加仓评估\n`
            if (pb.summary && pb.summary.totalSuggestedAddAmount > 0) {
                text += `建议加仓总额: $${pb.summary.totalSuggestedAddAmount.toFixed(0)}\n\n`
            } else {
                text += '\n'
            }

            const pbActionIcon: Record<string, string> = {
                ADD_NORMAL: '🟢', ADD_SMALL: '🟡', ADD_DEEP_ONLY: '🔵',
                WATCH_ONLY: '👀', DO_NOT_ADD: '🚫', REDUCE_INSTEAD: '🔴',
            }
            const pbActionLabel: Record<string, string> = {
                ADD_NORMAL: '正常加仓', ADD_SMALL: '少量加仓', ADD_DEEP_ONLY: '深度回调才加',
                WATCH_ONLY: '观察', DO_NOT_ADD: '不加仓', REDUCE_INSTEAD: '应减仓',
            }
            const pbPullbackLabel: Record<string, string> = {
                BUYABLE_PULLBACK: '✅可买', NORMAL_PULLBACK: '➖正常回调',
                WATCH_ONLY: '👀观察', BREAKDOWN_DO_NOT_ADD: '❌破位', REDUCE_INSTEAD: '🔴应减仓',
            }

            for (const p of addable) {
                const icon = pbActionIcon[p.action] || '❓'
                text += `${icon} **${p.symbol}** → ${pbActionLabel[p.action] || p.action} (${pbPullbackLabel[p.pullbackStatus] || p.pullbackStatus})\n`
                if (p.addLimits?.length) {
                    for (const lim of p.addLimits) {
                        text += `  L${lim.level}: $${lim.price.toFixed(2)} ($${lim.amount.toFixed(0)})\n`
                    }
                }
                if (p.invalidationTriggers?.length) {
                    text += `  ⚠️ 失效: ${p.invalidationTriggers.map(t => t.trigger).join('; ')}\n`
                }
            }

            if (noAdd.length > 0) {
                const noAddList = noAdd.map(p => `${pbActionIcon[p.action] || '🚫'} ${p.symbol}(${pbActionLabel[p.action]})`).join(' | ')
                text += `\n${noAddList}\n`
            }
        }
    }

    if (d.generated_at) text += `---\n⏰ ${d.generated_at}\n`
    return text
}

function formatAIExitAnalysis(data: Record<string, unknown>): string {
    const d = data as {
        overallPositionBias?: string
        oneLineSummary?: string
        userFacingSummary?: string
        portfolioRead?: { exposureComment?: string; concentrationComment?: string; trendComment?: string; riskComment?: string }
        actionBuckets?: {
            hold?: { symbol: string; reason: string }[]
            watch?: { symbol: string; reason: string }[]
            trim?: { symbol: string; suggestedAction?: string; reason: string }[]
            exit?: { symbol: string; reason: string }[]
            avoidAdding?: { symbol: string; reason: string }[]
        }
        conflicts?: { symbol: string; conflictType: string; severity: string; explanation: string }[]
        positionExplanations?: { symbol: string; action: string; plainEnglishReason: string; whatWouldChangeTheDecision: string; nextTriggerToWatch: string }[]
        riskWarnings?: string[]
        finalInstruction?: string
        generated_at?: string
    }

    const biasLabel: Record<string, string> = {
        HOLD_CORE: '🟢 持有核心', SELECTIVE_TRIM: '🟡 选择性减仓',
        DEFENSIVE_REDUCE: '🟠 防御性减仓', RISK_CONTROL: '🔴 风控优先', EXIT_RISK: '⛔ 退出风险',
    }

    let text = `## 🤖 AI 持仓分析\n\n`
    text += `**整体判断**: ${biasLabel[d.overallPositionBias || ''] || d.overallPositionBias || '未知'}\n\n`

    if (d.oneLineSummary) text += `> ${d.oneLineSummary}\n\n`
    if (d.userFacingSummary) text += `${d.userFacingSummary}\n\n`

    if (d.portfolioRead) {
        text += `### 组合评估\n`
        if (d.portfolioRead.exposureComment) text += `- 💰 ${d.portfolioRead.exposureComment}\n`
        if (d.portfolioRead.concentrationComment) text += `- 📊 ${d.portfolioRead.concentrationComment}\n`
        if (d.portfolioRead.trendComment) text += `- 📈 ${d.portfolioRead.trendComment}\n`
        if (d.portfolioRead.riskComment) text += `- ⚠️ ${d.portfolioRead.riskComment}\n`
        text += '\n'
    }

    if (d.actionBuckets) {
        const b = d.actionBuckets
        if (b.trim?.length) {
            text += `### 🟡 建议减仓\n`
            for (const item of b.trim) {
                text += `- **${item.symbol}** (${item.suggestedAction || 'TRIM'}): ${item.reason}\n`
            }
            text += '\n'
        }
        if (b.exit?.length) {
            text += `### 🔴 建议退出\n`
            for (const item of b.exit) {
                text += `- **${item.symbol}**: ${item.reason}\n`
            }
            text += '\n'
        }
        if (b.watch?.length) {
            text += `### 👀 需要关注\n`
            for (const item of b.watch) {
                text += `- **${item.symbol}**: ${item.reason}\n`
            }
            text += '\n'
        }
        if (b.avoidAdding?.length) {
            text += `### 🚫 避免加仓\n`
            for (const item of b.avoidAdding) {
                text += `- **${item.symbol}**: ${item.reason}\n`
            }
            text += '\n'
        }
    }

    if (d.conflicts?.length) {
        text += `### ⚡ 信号冲突\n`
        for (const c of d.conflicts) {
            const sev = c.severity === 'HIGH' ? '🔴' : c.severity === 'MEDIUM' ? '🟡' : '⚪'
            text += `- ${sev} **${c.symbol}**: ${c.explanation}\n`
        }
        text += '\n'
    }

    if (d.positionExplanations?.length) {
        text += `### 📋 个股解读\n`
        for (const pe of d.positionExplanations) {
            text += `**${pe.symbol}** → ${pe.action}\n`
            text += `  ${pe.plainEnglishReason}\n`
            text += `  变化条件: ${pe.whatWouldChangeTheDecision}\n`
            text += `  关注触发: ${pe.nextTriggerToWatch}\n\n`
        }
    }

    if (d.riskWarnings?.length) {
        text += `### ⚠️ 风险提醒\n`
        for (const w of d.riskWarnings) {
            text += `- ${w}\n`
        }
        text += '\n'
    }

    if (d.finalInstruction) {
        text += `---\n**📌 操作指令**: ${d.finalInstruction}\n`
    }

    if (d.generated_at) text += `\n⏰ ${d.generated_at}\n`
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

function formatDecisions(data: Record<string, unknown>): string {
    const d = data as {
        active_buy_plans?: { ticker: string; score?: number; category?: string; limit_1?: number; limit_2?: number; amount_l1?: number; amount_l2?: number; limit_reason?: string }[]
        exit_signals?: { symbol: string; action: string; urgency?: string; reasoning?: string[] }[]
        pullback_candidates?: { symbol: string; action: string; pullbackStatus?: string; addLimits?: { level: number; price: number; amount: number }[]; in_cooldown?: boolean }[]
        conflicts?: { symbol: string; conflict_type: string; severity: string; message: string }[]
        trade_history?: Record<string, { recently_added?: boolean; recently_trimmed?: boolean; recently_sold?: boolean; cooldown_until?: string; adds_last_10_days?: number }>
        summary?: { market_regime?: string; total_buy_orders?: number; total_buy_amount?: number; exit_signal_count?: number; pullback_add_count?: number; conflict_count?: number; high_severity_conflicts?: number; held_positions?: number; cash_available?: number }
        generated_at?: string
        error?: string
    }

    if (d.error) return `⚠️ 决策中心暂不可用: ${d.error}`

    let text = `## 🧠 决策中心\n\n`

    // Summary
    if (d.summary) {
        const s = d.summary
        const regimeLabel: Record<string, string> = { market_strong: '🟢 强势', market_neutral: '🟡 中性', market_weak: '🔴 弱势', semi_strong_qqq_weak: '🟡 分化' }
        text += `**市场**: ${regimeLabel[s.market_regime || ''] || s.market_regime || '未知'}`
        text += ` | **持仓**: ${s.held_positions || 0}只`
        text += ` | **现金**: $${(s.cash_available || 0).toLocaleString()}\n`
        if (s.conflict_count && s.conflict_count > 0) {
            text += `⚡ **${s.conflict_count}个信号冲突** (${s.high_severity_conflicts || 0}个高危)\n`
        }
        text += '\n'
    }

    // Conflicts (show first if any)
    if (d.conflicts?.length) {
        text += `### ⚡ 信号冲突\n`
        for (const c of d.conflicts) {
            const sev = c.severity === 'HIGH' ? '🔴' : c.severity === 'MEDIUM' ? '🟡' : '⚪'
            text += `${sev} **${c.symbol}** [${c.conflict_type}]: ${c.message}\n`
        }
        text += '\n'
    }

    // Exit signals
    if (d.exit_signals?.length) {
        const actionLabel: Record<string, string> = {
            EXIT: '🔴 退出', REDUCE_2_3: '🟠 减2/3', REDUCE_1_2: '🟡 减半',
            REDUCE_1_3: '🟡 减1/3', TRIM_RISK: '🟡 风控减仓', TRIM_PROFIT: '🟢 止盈',
            WATCH_PULLBACK: '👀 观察', WATCH: '👀 观察',
        }
        text += `### 📉 持仓信号 (${d.exit_signals.length}只需关注)\n`
        for (const s of d.exit_signals) {
            text += `${actionLabel[s.action] || s.action} **${s.symbol}**`
            if (s.reasoning?.length) text += ` — ${s.reasoning[0]}`
            text += '\n'
        }
        text += '\n'
    }

    // Buy plans
    if (d.active_buy_plans?.length) {
        text += `### 🎯 挂单计划 (${d.active_buy_plans.length}只)\n`
        for (const o of d.active_buy_plans) {
            const catLabel: Record<string, string> = { core: '核心', semi_core: '半核心', cyclical: '周期', high_beta: '高弹性', beta: '弹性' }
            text += `**${o.ticker}** [${catLabel[o.category || ''] || o.category}]`
            if (o.score) text += ` ${o.score}分`
            text += ` → $${o.limit_1?.toFixed(2)} ($${o.amount_l1}) | $${o.limit_2?.toFixed(2)} ($${o.amount_l2})\n`
        }
        if (d.summary?.total_buy_amount) {
            text += `💰 总挂单 $${d.summary.total_buy_amount.toLocaleString()}\n`
        }
        text += '\n'
    }

    // Pullback candidates
    if (d.pullback_candidates?.length) {
        const pbLabel: Record<string, string> = { ADD_NORMAL: '🟢加仓', ADD_SMALL: '🟡少量加', ADD_AGGRESSIVE: '🔵积极加' }
        text += `### 🔄 回调加仓 (${d.pullback_candidates.length}只)\n`
        for (const p of d.pullback_candidates) {
            text += `${pbLabel[p.action] || p.action} **${p.symbol}**`
            if (p.in_cooldown) text += ` ⏸️冷却中`
            if (p.addLimits?.length) {
                const limits = p.addLimits.map(l => `$${l.price.toFixed(2)}($${l.amount})`).join(' | ')
                text += ` → ${limits}`
            }
            text += '\n'
        }
        text += '\n'
    }

    // Trade history summary
    if (d.trade_history && Object.keys(d.trade_history).length > 0) {
        const active = Object.entries(d.trade_history).filter(([, ctx]) =>
            ctx.recently_added || ctx.recently_trimmed || ctx.recently_sold || ctx.cooldown_until
        )
        if (active.length > 0) {
            text += `### 📋 近期交易活动\n`
            for (const [sym, ctx] of active) {
                const tags: string[] = []
                if (ctx.recently_added) tags.push('近期加仓')
                if (ctx.recently_trimmed) tags.push('近期减仓')
                if (ctx.recently_sold) tags.push('近期卖出')
                if (ctx.cooldown_until) tags.push(`冷却至${ctx.cooldown_until}`)
                if (ctx.adds_last_10_days) tags.push(`10日加仓${ctx.adds_last_10_days}次`)
                text += `• **${sym}**: ${tags.join(' | ')}\n`
            }
            text += '\n'
        }
    }

    if (d.generated_at) text += `---\n⏰ ${d.generated_at}\n`
    return text
}

function formatNewTradeHistory(data: { trades: Record<string, unknown>[]; count: number }): string {
    if (!data.trades.length) return '暂无交易记录'
    let text = `**最近 ${data.count} 条交易记录**:\n\n`
    for (const t of data.trades) {
        const side = t.side === 'BUY' ? '买入' : t.side === 'SELL' ? '卖出' : String(t.side)
        const symbol = t.symbol || t.ticker || '?'
        const qty = t.quantity || t.shares || 0
        const price = t.price || 0
        const total = (Number(qty) * Number(price)).toFixed(2)
        const source = t.source === 'MANUAL' ? '手动' : t.source === 'MIGRATED' ? '迁移' : String(t.source || '')
        const time = t.trade_time || t.created_at || ''
        text += `• ${time} | ${side} **${symbol}** ${qty}股 @ $${price} ($${total}) [${source}]\n`
        if (t.note) text += `  💬 ${t.note}\n`
    }
    return text
}
