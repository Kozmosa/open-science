import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createLiteratureSubscription, deleteLiteratureSubscription, triggerLiteratureFetch } from '../../api';
import { useT } from '../../i18n';
import { Button, Input, Select } from '../../components/ui';
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
    onSuccess: (data) => {
      invalidate();
      setShowNewForm(false);
      setLabel('');
      setKeywords('');
      setSelectedCategories([]);
      setFrequency('daily');
      // Auto-trigger fetch for the new subscription
      if (data.subscription_id) {
        triggerLiteratureFetch(data.subscription_id).catch(() => {
          // Silently handle fetch trigger errors
        });
      }
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
        <h2 className="text-sm font-semibold text-[var(--sidebar-foreground)]">{t('literature.mySubscriptions')}</h2>
        <Button size="sm" onClick={() => setShowNewForm(!showNewForm)}>{t('literature.newSubscription')}</Button>
      </div>

      {/* New subscription form */}
      {showNewForm && (
        <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--sidebar-primary)]/50 p-3 text-xs space-y-3">
          <div>
            <label htmlFor="sub-label" className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('literature.label')}
            </label>
            <Input
              id="sub-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="text-xs py-2"
              placeholder={t('literature.label')}
            />
          </div>
          <div>
            <label htmlFor="sub-keywords" className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('literature.keywords')}
            </label>
            <Input
              id="sub-keywords"
              type="text"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              className="text-xs py-2"
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
                  aria-pressed={selectedCategories.includes(cat)}
                  onClick={() => toggleCategory(cat)}
                  className={`rounded-full px-2 py-0.5 text-[10px] transition ${
                    selectedCategories.includes(cat)
                      ? 'bg-[var(--apple-blue)] text-white'
                      : 'bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface)]'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label htmlFor="sub-frequency" className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('literature.frequency')}
            </label>
            <Select
              id="sub-frequency"
              value={frequency}
              onChange={(e) => setFrequency(e.target.value as 'daily' | 'weekly')}
              className="text-xs py-2"
            >
              <option value="daily">{t('literature.daily')}</option>
              <option value="weekly">{t('literature.weekly')}</option>
            </Select>
          </div>
          <Button
            size="sm"
            onClick={handleCreate}
            disabled={!label.trim()}
            isLoading={createMutation.isPending}
            className="w-full"
          >
            {t('literature.create')}
          </Button>
        </div>
      )}

      {/* Subscription list */}
      <div className="flex-1 space-y-1 overflow-y-auto">
        {subscriptions.length === 0 && (
          <p className="py-4 text-center text-[11px] text-[var(--text-secondary)]">
            {t('literature.noSubscriptions')}
          </p>
        )}
        {subscriptions.map((sub) => (
          <div
            key={sub.subscription_id}
            className="group rounded-lg border border-[var(--border)] bg-[var(--sidebar-primary)]/30 p-3 transition hover:bg-[var(--sidebar-primary)]"
          >
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-[var(--sidebar-foreground)]">{sub.label}</p>
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
                className="shrink-0 rounded p-1 text-[var(--text-tertiary)] hover:text-red-500 opacity-0 group-hover:opacity-100 transition"
                title={t('literature.delete')}
                aria-label={t('literature.delete')}
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
