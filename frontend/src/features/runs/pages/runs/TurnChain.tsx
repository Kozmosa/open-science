import { TokenFlowBar } from '@features/tasks';
import { SectionStack, semanticDotClasses, semanticToneClasses } from '@design-system';
import { useT } from '@/shared/i18n';
import type { TurnResponse } from '@/shared/api/transportTypes';

interface Props {
  turns: TurnResponse[];
}

const STATUS_BADGE_CLASSES: Record<string, string> = {
  running: semanticToneClasses.info,
  completed: semanticToneClasses.success,
  failed: semanticToneClasses.danger,
  interrupted: semanticToneClasses.warning,
};

const STATUS_DOT_CLASSES: Record<string, string> = {
  running: `${semanticDotClasses.info} shadow-[0_0_0_2px_var(--info-border)]`,
  completed: semanticDotClasses.success,
  failed: semanticDotClasses.danger,
  interrupted: semanticDotClasses.warning,
};

function formatDuration(ms: number | null): string {
  if (ms === null) return '--';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function TurnChain({ turns }: Props) {
  const t = useT();
  const attemptStatusLabel = (status: string): string => {
    if (status === 'running') return t('pages.runs.attemptStatus.running');
    if (status === 'completed' || status === 'succeeded') {
      return t('pages.runs.attemptStatus.completed');
    }
    if (status === 'failed') return t('pages.runs.attemptStatus.failed');
    if (status === 'interrupted' || status === 'cancelled') {
      return t('pages.runs.attemptStatus.interrupted');
    }
    return status;
  };

  if (turns.length === 0) {
    return <p className="text-sm text-[var(--text-tertiary)]">No Turns recorded</p>;
  }

  return (
    <SectionStack gap={2}>
      <h3 className="text-sm font-semibold text-[var(--text)]">
        Turns
      </h3>
      <div className="relative pl-6">
        {turns.map((a, i) => {
          const startedAt = typeof a.started_at === 'string' ? a.started_at : null;
          const finishedAt = typeof a.finished_at === 'string' ? a.finished_at : null;
          const durationMs = startedAt && finishedAt
            ? Math.max(0, new Date(finishedAt).getTime() - new Date(startedAt).getTime())
            : null;
          const failureReason = typeof a.failure_code === 'string' ? a.failure_code : null;
          const tokenUsageJson = typeof a.token_usage_json === 'string' ? a.token_usage_json : null;
          return <div key={a.turn_id} className="relative pb-4 last:pb-0">
            <div
              className={`absolute left-[-22px] top-[14px] z-10 h-3 w-3 rounded-full border-2 border-[var(--surface)] ${STATUS_DOT_CLASSES[a.status] ?? semanticDotClasses.muted}`}
            />
            {i < turns.length - 1 && (
              <div className="absolute left-[-16.5px] top-[26px] h-full w-[1px] bg-[var(--border)]" />
            )}

            <div className={`rounded-lg border p-3 ${STATUS_BADGE_CLASSES[a.status] ?? STATUS_BADGE_CLASSES.interrupted}`}>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-[var(--text)]">
                  Turn {a.turn_seq}
                </span>
                <span
                  className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_BADGE_CLASSES[a.status] ?? STATUS_BADGE_CLASSES.interrupted}`}
                >
                  {attemptStatusLabel(a.status)}
                </span>
              </div>
              {failureReason && (
                <p className="mt-1 text-xs text-[var(--text-secondary)]">{failureReason}</p>
              )}
              <div className="mt-2 flex items-center gap-4 text-xs text-[var(--text-secondary)]">
                {a.task_id && (
                  <a
                    href={`/tasks/${a.task_id}`}
                    className="text-[var(--info)] hover:underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {t('pages.runs.viewTask')}
                  </a>
                )}
                <span>{formatDuration(durationMs)}</span>
                <TokenFlowBar tokenUsageJson={tokenUsageJson} />
                {(() => {
                  if (!tokenUsageJson) return null;
                  try {
                    const tu = JSON.parse(tokenUsageJson);
                    if (!tu.by_model || Object.keys(tu.by_model).length === 0) return null;
                    return (
                      <details className="mt-2 text-xs">
                        <summary className="cursor-pointer font-medium text-[var(--info)]">
                          {t('pages.runs.perModelBreakdown')}
                        </summary>
                        <div className="mt-2 flex flex-col gap-1">
                          {Object.entries(tu.by_model as Record<string, Record<string, number>>).map(([model, usage]) => {
                            const modelTokens = (usage.input_tokens || 0) + (usage.output_tokens || 0);
                            const cost = typeof usage.cost_usd === 'number' ? usage.cost_usd : null;
                            return (
                              <div key={model} className="flex items-center justify-between rounded bg-[var(--bg-secondary)] px-2 py-1">
                                <span className="font-mono text-[11px] text-[var(--text)]">{model}</span>
                                <span className="text-[var(--text-secondary)]">
                                  {modelTokens >= 1000 ? `${(modelTokens / 1000).toFixed(1)}K` : modelTokens}
                                  {cost != null ? ` · $${cost.toFixed(2)}` : ''}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </details>
                    );
                  } catch { return null; }
                })()}
              </div>
            </div>
          </div>;
        })}
      </div>
    </SectionStack>
  );
}
