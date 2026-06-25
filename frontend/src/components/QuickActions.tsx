interface QuickActionsProps {
  onAction: (message: string) => void
  disabled: boolean
}

const actions = [
  { label: '📊 盯盘', message: '盯盘报告' },
  { label: '🛌 挂单', message: '睡前挂单计划' },
  { label: '💪 强势', message: '哪个板块强' },
  { label: '⚠️ 避雷', message: '不能接的标的' },
  { label: '💼 仓位', message: '我的仓位情况' },
  { label: '📝 记仓位', message: '__TRADE_INPUT__' },
  { label: '📜 交易记录', message: '__TRADE_HISTORY__' },
]

export default function QuickActions({ onAction, disabled }: QuickActionsProps) {
  return (
    <div className="flex gap-2 px-4 py-2 overflow-x-auto hide-scrollbar shrink-0">
      {actions.map((action) => (
        <button
          key={action.message}
          onClick={() => onAction(action.message)}
          disabled={disabled}
          className="flex-none px-3 py-1.5 text-xs font-medium bg-gray-700 hover:bg-gray-600 
                     active:bg-gray-500 text-gray-200 rounded-full border border-gray-600 
                     transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {action.label}
        </button>
      ))}
    </div>
  )
}
