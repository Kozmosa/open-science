import { useState } from 'react';
import Input from '../../components/ui/Input';
import StatusDot from '../../components/ui/StatusDot';
import { useT } from '../../i18n';
import type { SessionRecord } from '../../types';

interface Props {
  sessions: SessionRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
}

const STATUS_COLOR: Record<string, 'success' | 'warning' | 'idle'> = {
  active: 'success',
  completed: 'warning',
  archived: 'idle',
};

export function SessionList({ sessions, selectedId, onSelect, loading }: Props) {
  const t = useT();
  const [search, setSearch] = useState('');

  const filtered = sessions.filter((s) =>
    s.title.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex flex-col gap-3 p-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t('pages.sessions.sidebarTitle')}</h3>
        <span className="text-xs text-gray-500">
          {t('pages.sessions.sidebarCount', { count: sessions.length })}
        </span>
      </div>
      <Input
        placeholder={t('pages.sessions.searchPlaceholder')}
        value={search}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
      />
      {loading && filtered.length === 0 ? (
        <p className="text-sm text-gray-400 px-1">{t('common.loading')}</p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-gray-400 px-1">{t('pages.sessions.empty')}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {filtered.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onSelect(s.id)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                  selectedId === s.id
                    ? 'bg-blue-50 border border-blue-200'
                    : 'hover:bg-gray-50 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2">
                  <StatusDot status={STATUS_COLOR[s.status] ?? 'idle'} />
                  <span className="font-medium truncate">{s.title}</span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                  <span>{t('pages.sessions.taskCount', { count: s.task_count })}</span>
                  <span>${s.total_cost_usd.toFixed(2)}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
