import { useState } from 'react';
import Input from '../../components/ui/Input';
import StatusDot from '../../components/ui/StatusDot';
import LoadMoreSentinel from '../../components/common/LoadMoreSentinel';
import { useT } from '../../i18n';
import type { SessionRecord } from '../../types';

interface Props {
  sessions: SessionRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  onLoadMore?: () => void;
}

const STATUS_COLOR: Record<string, 'success' | 'warning' | 'idle'> = {
  active: 'success',
  completed: 'warning',
  archived: 'idle',
};

export function SessionList({ sessions, selectedId, onSelect, loading, hasNextPage, isFetchingNextPage, onLoadMore }: Props) {
  const t = useT();
  const [search, setSearch] = useState('');

  const filtered = sessions.filter((s) =>
    s.title.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex flex-col gap-3 p-2 min-h-0">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t('pages.sessions.sidebarTitle')}</h3>
        <span className="text-xs text-[var(--text-secondary)]">
          {t('pages.sessions.sidebarCount', { count: sessions.length })}
        </span>
      </div>
      <Input
        placeholder={t('pages.sessions.searchPlaceholder')}
        value={search}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
      />
      {loading && filtered.length === 0 ? (
        <p className="px-1 text-sm text-[var(--text-tertiary)]">{t('common.loading')}</p>
      ) : filtered.length === 0 ? (
        <p className="px-1 text-sm text-[var(--text-tertiary)]">{t('pages.sessions.empty')}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {filtered.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onSelect(s.id)}
                className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  selectedId === s.id
                    ? 'border border-[var(--info-border)] bg-[var(--info-soft)]'
                    : 'border border-transparent hover:bg-[var(--bg-secondary)]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <StatusDot status={STATUS_COLOR[s.status] ?? 'idle'} />
                  <span className="truncate font-medium text-[var(--text)]" title={s.title}>{s.title}</span>
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-[var(--text-secondary)]">
                  <span>{t('pages.sessions.taskCount', { count: s.task_count })}</span>
                  <span>${s.total_cost_usd.toFixed(2)}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      {hasNextPage && (
        <LoadMoreSentinel onVisible={onLoadMore ?? (() => {})} loading={isFetchingNextPage ?? false} />
      )}
    </div>
  );
}
