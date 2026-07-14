import { TokenFlowBar } from '../../components/token/TokenFlowBar';
import { SectionStack, semanticDotClasses, semanticToneClasses } from '@design-system';
import { useT } from '@/shared/i18n';
import type { AttemptRecord } from '@/shared/types';

interface Props {
  attempts: AttemptRecord[];
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

export function AttemptChain({ attempts }: Props) {
  const t = useT();

  if (attempts.length === 0) {
    return <p className="text-sm text-[var(--text-tertiary)]">{t('pages.sessions.noAttempts')}</p>;
  }

  return (
    <SectionStack gap={2}>
      <h3 className="text-sm font-semibold text-[var(--text)]">
        {t('pages.sessions.attemptsTitle')}
      </h3>
      <div className="relative pl-6">
        {attempts.map((a, i) => (
          <div key={a.id} className="relative pb-4 last:pb-0">
            <div
              className={`absolute left-[-22px] top-[14px] z-10 h-3 w-3 rounded-full border-2 border-[var(--surface)] ${STATUS_DOT_CLASSES[a.status] ?? semanticDotClasses.muted}`}
            />
            {i < attempts.length - 1 && (
              <div className="absolute left-[-16.5px] top-[26px] h-full w-[1px] bg-[var(--border)]" />
            )}

            <div className={`rounded-lg border p-3 ${STATUS_BADGE_CLASSES[a.status] ?? STATUS_BADGE_CLASSES.interrupted}`}>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-[var(--text)]">
                  {t('pages.sessions.attemptLabel', { seq: a.attempt_seq })}
                </span>
                <span
                  className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_BADGE_CLASSES[a.status] ?? STATUS_BADGE_CLASSES.interrupted}`}
                >
                  {t(`pages.sessions.attemptStatus.${a.status}`)}
                </span>
              </div>
              {a.intervention_reason && (
                <p className="mt-1 text-xs text-[var(--text-secondary)]">{a.intervention_reason}</p>
              )}
              <div className="mt-2 flex items-center gap-4 text-xs text-[var(--text-secondary)]">
                {a.task_id && (
                  <a
                    href={`/tasks/${a.task_id}`}
                    className="text-[var(--info)] hover:underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {t('pages.sessions.viewTask')}
                  </a>
                )}
                <span>{formatDuration(a.duration_ms)}</span>
                <TokenFlowBar tokenUsageJson={a.token_usage_json} />
                {(() => {
                  if (!a.token_usage_json) return null;
                  try {
                    const tu = JSON.parse(a.token_usage_json);
                    if (!tu.by_model || Object.keys(tu.by_model).length === 0) return null;
                    return (
                      <details className="mt-2 text-xs">
                        <summary className="cursor-pointer font-medium text-[var(--info)]">
                          {t('pages.sessions.perModelBreakdown')}
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
          </div>
        ))}
      </div>
    </SectionStack>
  );
}
