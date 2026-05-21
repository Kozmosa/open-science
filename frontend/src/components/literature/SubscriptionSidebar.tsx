import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createLiteratureSubscription, deleteLiteratureSubscription } from '../../api';
import { useT } from '../../i18n';
import type { LiteratureSubscription } from '../../types';

const ARXIV_CATEGORIES = ['cs.AI', 'cs.CL', 'cs.LG', 'cs.CV', 'stat.ML'];

interface Props {
  subscriptions: LiteratureSubscription[];
}

export default function SubscriptionSidebar({ subscriptions }: Props) {
  const t = useT();
  const queryClient = useQueryClient();
  const [showNewForm, setShowNewForm] = useState(false);
  const [label, setLabel] = useState('');
  const [keywords, setKeywords] = useState('');
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [frequency, setFrequency] = useState<'daily' | 'weekly'>('daily');

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['literature-subscriptions'] });
  };

  const createMutation = useMutation({
    mutationFn: (payload: Partial<LiteratureSubscription>) => createLiteratureSubscription(payload),
    onSuccess: () => {
      invalidate();
      setShowNewForm(false);
      setLabel('');
      setKeywords('');
      setSelectedCategories([]);
      setFrequency('daily');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteLiteratureSubscription(id),
    onSuccess: () => invalidate(),
  });

  const toggleCategory = (cat: string) => {
    setSelectedCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  };

  const handleCreate = () => {
    if (!label.trim()) return;
    createMutation.mutate({
      label: label.trim(),
      keywords: keywords.split(',').map((k) => k.trim()).filter(Boolean),
      arxiv_categories: selectedCategories,
      frequency,
    });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">{t('literature.mySubscriptions')}</h2>
        <button
          type="button"
          onClick={() => setShowNewForm(!showNewForm)}
          className="rounded-md bg-[var(--apple-blue)] px-2.5 py-1 text-[11px] text-white hover:opacity-90"
        >
          {t('literature.newSubscription')}
        </button>
      </div>

      {/* New subscription form */}
      {showNewForm && (
        <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs space-y-3">
          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('literature.label')}
            </label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-xs text-[var(--foreground)]"
              placeholder={t('literature.label')}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('literature.keywords')}
            </label>
            <input
              type="text"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-xs text-[var(--foreground)]"
              placeholder="machine learning, NLP"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('literature.categories')}
            </label>
            <div className="flex flex-wrap gap-1">
              {ARXIV_CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => toggleCategory(cat)}
                  className={`rounded-full px-2 py-0.5 text-[10px] transition ${
                    selectedCategories.includes(cat)
                      ? 'bg-[var(--apple-blue)] text-white'
                      : 'border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg)]'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('literature.frequency')}
            </label>
            <select
              value={frequency}
              onChange={(e) => setFrequency(e.target.value as 'daily' | 'weekly')}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-xs text-[var(--foreground)]"
            >
              <option value="daily">{t('literature.daily')}</option>
              <option value="weekly">{t('literature.weekly')}</option>
            </select>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            disabled={!label.trim() || createMutation.isPending}
            className="w-full rounded-md bg-[var(--apple-blue)] py-1.5 text-xs text-white hover:opacity-90 disabled:opacity-50"
          >
            {createMutation.isPending ? t('common.loading') : t('literature.create')}
          </button>
        </div>
      )}

      {/* Subscription list */}
      <div className="flex-1 space-y-2 overflow-y-auto">
        {subscriptions.length === 0 && (
          <p className="py-4 text-center text-[11px] text-[var(--text-tertiary)]">
            {t('literature.mySubscriptions')}
          </p>
        )}
        {subscriptions.map((sub) => (
          <div
            key={sub.subscription_id}
            className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3"
          >
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">{sub.label}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {sub.keywords.slice(0, 3).map((kw) => (
                    <span
                      key={kw}
                      className="rounded-full bg-[var(--bg)] px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)]"
                    >
                      {kw}
                    </span>
                  ))}
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {sub.arxiv_categories.slice(0, 3).map((cat) => (
                    <span
                      key={cat}
                      className="rounded-full bg-[var(--apple-blue)]/10 px-1.5 py-0.5 text-[10px] text-[var(--apple-blue)]"
                    >
                      {cat}
                    </span>
                  ))}
                </div>
                <span className="mt-1 inline-block text-[10px] text-[var(--text-tertiary)]">
                  {t(`literature.${sub.frequency}`)}
                </span>
              </div>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(sub.subscription_id)}
                className="shrink-0 rounded p-1 text-[var(--text-tertiary)] hover:text-red-500"
                title={t('literature.delete')}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                </svg>
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
