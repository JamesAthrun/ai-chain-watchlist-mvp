import { useState, useEffect, useRef } from 'react'
import StatusBar from './components/StatusBar'
import MessageList from './components/MessageList'
import type { Message } from './components/MessageList'
import QuickActions from './components/QuickActions'
import ChatInput from './components/ChatInput'
import { sendChat, getHealth } from './api'

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [regime, setRegime] = useState('')
  const [connected, setConnected] = useState(false)
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

  return (
    <div className="flex flex-col h-dvh bg-gray-900">
      <StatusBar regime={regime} connected={connected} />
      <div className="flex-1 overflow-y-auto hide-scrollbar p-4 space-y-3">
        <MessageList messages={messages} loading={loading} />
        <div ref={messagesEndRef} />
      </div>
      <QuickActions onAction={handleSend} disabled={loading} />
      <ChatInput onSend={handleSend} disabled={loading} />
    </div>
  )
}
