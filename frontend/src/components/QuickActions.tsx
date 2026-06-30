import { useState } from 'react'

interface QuickActionsProps {
    onAction: (message: string) => void
    disabled: boolean
}

const primaryActions = [
    { label: '\u{1F9E0} \u51B3\u7B56', message: '__DECISIONS__' },
    { label: '\u{1F30D} \u5168\u7403', message: '__GLOBAL_MARKET__' },
    { label: '\u{1F3AF} \u8BA1\u5212', message: '__DAILY_PLAN__' },
    { label: '\u{1F4C9} \u6301\u4ED3', message: '__EXIT_PLAN__' },
    { label: '\u{1F4DD} \u8BB0\u4EA4\u6613', message: '__TRADE_INPUT__' },
]

const moreActions = [
    { label: '\u{1F4BC} \u4ED3\u4F4D', message: '\u6211\u7684\u4ED3\u4F4D\u60C5\u51B5' },
    { label: '\u{1F4DC} \u4EA4\u6613\u8BB0\u5F55', message: '__TRADE_HISTORY__' },
    { label: '\u{1F3AF} \u4EEA\u8868\u76D8', message: '__DASHBOARD__' },
    { label: '\u{1F6CC} \u6302\u5355', message: '\u7761\u524D\u6302\u5355\u8BA1\u5212' },
    { label: '\u{1F4B0} \u8C03\u73B0\u91D1', message: '__CASH_ADJUST__' },
]

export default function QuickActions({ onAction, disabled }: QuickActionsProps) {
    const [showMore, setShowMore] = useState(false)

    return (
        <div className="shrink-0">
            <div className="flex gap-2 px-4 py-2 overflow-x-auto hide-scrollbar">
                {primaryActions.map((action) => (
                    <button
                        key={action.message}
                        onClick={() => { setShowMore(false); onAction(action.message) }}
                        disabled={disabled}
                        className="flex-none px-3 py-1.5 text-xs font-medium bg-gray-700 hover:bg-gray-600 
                         active:bg-gray-500 text-gray-200 rounded-full border border-gray-600 
                         transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {action.label}
                    </button>
                ))}
                <button
                    onClick={() => setShowMore(!showMore)}
                    disabled={disabled}
                    className={`flex-none px-3 py-1.5 text-xs font-medium rounded-full border transition-colors
                        disabled:opacity-50 disabled:cursor-not-allowed
                        ${showMore ? 'bg-blue-600 border-blue-500 text-white' : 'bg-gray-700 hover:bg-gray-600 border-gray-600 text-gray-200'}`}
                >
                    {'\u22EF\u66F4\u591A'}
                </button>
            </div>
            {showMore && (
                <div className="flex gap-2 px-4 py-1.5 overflow-x-auto hide-scrollbar border-t border-gray-800">
                    {moreActions.map((action) => (
                        <button
                            key={action.message}
                            onClick={() => { setShowMore(false); onAction(action.message) }}
                            disabled={disabled}
                            className="flex-none px-3 py-1.5 text-xs font-medium bg-gray-800 hover:bg-gray-700 
                             active:bg-gray-600 text-gray-300 rounded-full border border-gray-700 
                             transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {action.label}
                        </button>
                    ))}
                </div>
            )}
        </div>
    )
}
