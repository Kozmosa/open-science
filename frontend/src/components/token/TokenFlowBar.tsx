import type { TokenUsage } from '../../types';

interface Props {
  tokenUsageJson: string | null;
}

function parseTokenUsage(json: string | null): TokenUsage | null {
  if (!json) return null;
  try {
    return JSON.parse(json) as TokenUsage;
  } catch {
    return null;
  }
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

const SEGMENTS = [
  { key: 'input_tokens', label: 'Input', color: 'bg-blue-300' },
  { key: 'cache_creation_input_tokens', label: 'Cache', color: 'bg-green-300' },
  { key: 'output_tokens', label: 'Output', color: 'bg-yellow-300' },
  { key: 'cache_read_input_tokens', label: 'Think', color: 'bg-gray-300' },
] as const;

export function TokenFlowBar({ tokenUsageJson }: Props) {
  const usage = parseTokenUsage(tokenUsageJson);
  if (!usage) return null;

  const total = usage.total;
  const totalTokens =
    (total.input_tokens || 0) +
    (total.output_tokens || 0) +
    (total.cache_creation_input_tokens || 0) +
    (total.cache_read_input_tokens || 0);
  if (totalTokens === 0) return null;

  return (
    <div className="mt-2">
      <div className="flex justify-between text-[10px] text-gray-500 mb-1">
        <span>Tokens</span>
        <span className="font-medium text-gray-700">
          Total: {formatTokens(totalTokens)}
          {total.cost_usd != null ? ` · $${total.cost_usd.toFixed(2)}` : ''}
        </span>
      </div>
      <div className="flex h-[10px] rounded-sm overflow-hidden gap-px">
        {SEGMENTS.map(({ key, color }) => {
          const val = (usage.total as Record<string, number | undefined>)[key] || 0;
          if (val === 0) return null;
          return (
            <div
              key={key}
              className={color}
              style={{ width: `${(val / totalTokens) * 100}%` }}
              title={`${key}: ${formatTokens(val)}`}
            />
          );
        })}
      </div>
      <div className="flex gap-3 mt-1 text-[9px] text-gray-400">
        {SEGMENTS.map(({ key, label, color }) => {
          const val = (usage.total as Record<string, number | undefined>)[key] || 0;
          if (val === 0) return null;
          return (
            <span key={key} className="flex items-center gap-1">
              <span className={`inline-block w-[6px] h-[6px] rounded-sm ${color}`} />
              {label} {formatTokens(val)}
            </span>
          );
        })}
      </div>
    </div>
  );
}
