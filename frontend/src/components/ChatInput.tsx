import { useState, useRef } from 'react'

interface ChatInputProps {
  onSend: (message: string) => void
  disabled: boolean
  placeholder?: string
}

export default function ChatInput({ onSend, disabled, placeholder }: ChatInputProps) {
  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSend = () => {
    const msg = input.trim()
    if (!msg || disabled) return
    onSend(msg)
    setInput('')
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex items-center gap-2 px-4 py-3 bg-gray-800 border-t border-gray-700 shrink-0">
      <input
        ref={inputRef}
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder || "输入问题..."}
        className="flex-1 px-4 py-2.5 bg-gray-700 border border-gray-600 rounded-full 
                   text-sm text-white placeholder-gray-400 outline-none focus:border-blue-500 
                   transition-colors disabled:opacity-50"
      />
      <button
        onClick={handleSend}
        disabled={disabled || !input.trim()}
        className="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 
                   text-white text-sm font-medium rounded-full transition-colors 
                   disabled:opacity-50 disabled:cursor-not-allowed"
      >
        发送
      </button>
    </div>
  )
}
