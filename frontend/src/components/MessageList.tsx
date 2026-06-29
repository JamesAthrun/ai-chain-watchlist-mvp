interface Message {
    role: 'user' | 'assistant'
    content: string
    regime?: string
    time?: string
}

interface MessageListProps {
    messages: Message[]
    loading: boolean
}

export type { Message }

export default function MessageList({ messages, loading }: MessageListProps) {
    return (
        <div className="flex-1 overflow-y-auto hide-scrollbar p-4 space-y-3">
            {messages.length === 0 && (
                <div className="text-center text-gray-500 mt-20">
                    <p className="text-lg">👋 你好！</p>
                    <p className="text-sm mt-2">点击下方快捷按钮或输入问题开始</p>
                </div>
            )}
            {messages.map((msg, i) => (
                <div
                    key={i}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                    <div
                        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${msg.role === 'user'
                                ? 'bg-blue-600 text-white rounded-br-md'
                                : 'bg-gray-700 text-gray-100 rounded-bl-md'
                            }`}
                    >
                        {msg.content}
                    </div>
                </div>
            ))}
            {loading && (
                <div className="flex justify-start">
                    <div className="bg-gray-700 rounded-2xl rounded-bl-md px-4 py-3">
                        <div className="flex gap-1">
                            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
