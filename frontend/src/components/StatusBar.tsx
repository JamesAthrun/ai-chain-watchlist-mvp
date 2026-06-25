interface StatusBarProps {
  regime: string
  connected: boolean
  enhance?: boolean
  onToggleEnhance?: () => void
}

export default function StatusBar({ regime, connected, enhance, onToggleEnhance }: StatusBarProps) {
  const regimeLabel =
    regime === 'market_strong' ? '强势' :
    regime === 'market_weak' ? '弱势' :
    regime === 'market_neutral' ? '震荡' : '--'

  const regimeColor =
    regime === 'market_strong' ? 'text-green-400' :
    regime === 'market_weak' ? 'text-red-400' :
    'text-yellow-400'

  return (
    <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700 shrink-0">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-gray-300">AI 盯盘助手</span>
        {onToggleEnhance && (
          <button
            onClick={onToggleEnhance}
            className={`px-2 py-0.5 text-xs rounded-full border transition-colors ${
              enhance
                ? 'bg-blue-600 border-blue-500 text-white'
                : 'bg-gray-700 border-gray-600 text-gray-400'
            }`}
          >
            🤖 AI分析
          </button>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-400">
          市场: <span className={`font-medium ${regimeColor}`}>{regimeLabel}</span>
        </span>
        <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
      </div>
    </div>
  )
}
