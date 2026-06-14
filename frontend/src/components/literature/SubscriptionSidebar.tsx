import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Pencil, Trash2 } from 'lucide-react';
import {
  createLiteratureSubscription,
  deleteLiteratureSubscription,
  updateLiteratureSubscription,
  triggerLiteratureFetch,
} from '@/shared/api';
import { useT } from '@/shared/i18n';
import { Button, Input, Select } from '@design-system/primitives';
import type { LiteratureSubscription } from '@/shared/types';

const ARXIV_CATEGORIES = ['cs.AI', 'cs.CL', 'cs.LG', 'cs.CV', 'stat.ML'];

interface Props {
  subscriptions: LiteratureSubscription[];
  selectedSubscriptionId?: string;
  onSelectSubscription?: (id: string | undefined) => void;
}

interface FormState {
  label: string;
  keywords: string;
  selectedCategories: string[];
  frequency: 'daily' | 'weekly';
}

function emptyForm(): FormState {
  return { label: '', keywords: '', selectedCategories: [], frequency: 'daily' };
}

function subToForm(sub: LiteratureSubscription): FormState {
  return {
    label: sub.label,
    keywords: sub.keywords.join(', '),
    selectedCategories: [...sub.arxiv_categories],
    frequency: sub.frequency as 'daily' | 'weekly',
  };
}

export default function SubscriptionSidebar({
  subscriptions,
  selectedSubscriptionId,
  onSelectSubscription,
}: Props) {
  const t = useT();
  const queryClient = useQueryClient();

  const [mode, setMode] = useState<'list' | 'new' | 'edit'>('list');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['literature-subscriptions'] });
  };

  const startNew = () => {
    setForm(emptyForm());
    setEditingId(null);
    setMode('new');
  };

  const startEdit = (sub: LiteratureSubscription) => {
    setForm(subToForm(sub));
    setEditingId(sub.subscription_id);
    setMode('edit');
  };

  const cancelForm = () => {
    setMode('list');
    setEditingId(null);
    setForm(emptyForm());
  };

  const createMutation = useMutation({
    mutationFn: (payload: Partial<LiteratureSubscription>) =>
      createLiteratureSubscription(payload),
    onSuccess: (data) => {
      invalidate();
      cancelForm();
      if (data.subscription_id) {
        triggerLiteratureFetch(data.subscription_id).catch(() => {});
      }
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<LiteratureSubscription> }) =>
      updateLiteratureSubscription(id, payload),
    onSuccess: () => {
      invalidate();
      cancelForm();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteLiteratureSubscription(id),
    onSuccess: () => invalidate(),
  });

  const fetchMutation = useMutation({
    mutationFn: (id: string) => triggerLiteratureFetch(id),
  });

  const toggleCategory = (cat: string) => {
    setForm((prev) => ({
      ...prev,
      selectedCategories: prev.selectedCategories.includes(cat)
        ? prev.selectedCategories.filter((c) => c !== cat)
        : [...prev.selectedCategories, cat],
    }));
  };

  const handleCreate = () => {
    if (!form.label.trim()) return;
    createMutation.mutate({
      label: form.label.trim(),
      keywords: form.keywords.split(',').map((k) => k.trim()).filter(Boolean),
      arxiv_categories: form.selectedCategories,
      frequency: form.frequency,
    });
  };

  const handleUpdate = () => {
    if (!editingId || !form.label.trim()) return;
    updateMutation.mutate({
      id: editingId,
      payload: {
        label: form.label.trim(),
        keywords: form.keywords.split(',').map((k) => k.trim()).filter(Boolean),
        arxiv_categories: form.selectedCategories,
        frequency: form.frequency,
      },
    });
  };

  const isFormOpen = mode === 'new' || mode === 'edit';
  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--sidebar-foreground)]">
          {t('literature.mySubscriptions')}
        </h2>
        <Button size="sm" onClick={startNew} disabled={isFormOpen}>
          {t('literature.newSubscription')}
        </Button>
      </div>

      {/* New / Edit form */}
      {isFormOpen && (
        <div className="mb-4 space-y-3 rounded-lg border border-[var(--border)] bg-[var(--sidebar-primary)]/50 p-3 text-xs">
          <div>
            <label
              htmlFor="sub-label"
              className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]"
            >
              {t('literature.label')}
            </label>
            <Input
              id="sub-label"
              type="text"
              value={form.label}
              onChange={(e) => setForm((p) => ({ ...p, label: e.target.value }))}
              className="py-2 text-xs"
              placeholder={t('literature.label')}
            />
          </div>
          <div>
            <label
              htmlFor="sub-keywords"
              className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]"
            >
              {t('literature.keywords')}
            </label>
            <Input
              id="sub-keywords"
              type="text"
              value={form.keywords}
              onChange={(e) => setForm((p) => ({ ...p, keywords: e.target.value }))}
              className="py-2 text-xs"
              placeholder={t('literature.keywordsPlaceholder')}
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
                  aria-pressed={form.selectedCategories.includes(cat)}
                  onClick={() => toggleCategory(cat)}
                  className={`rounded-full px-2 py-0.5 text-[10px] transition ${
                    form.selectedCategories.includes(cat)
                      ? 'bg-[var(--apple-blue)] text-white'
                      : 'border border-[var(--border)] bg-[var(--bg)] text-[var(--text)] hover:bg-[var(--surface)]'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label
              htmlFor="sub-frequency"
              className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]"
            >
              {t('literature.frequency')}
            </label>
            <Select
              id="sub-frequency"
              value={form.frequency}
              onChange={(e) =>
                setForm((p) => ({ ...p, frequency: e.target.value as 'daily' | 'weekly' }))
              }
              className="py-2 text-xs"
            >
              <option value="daily">{t('literature.daily')}</option>
              <option value="weekly">{t('literature.weekly')}</option>
            </Select>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={mode === 'new' ? handleCreate : handleUpdate}
              disabled={!form.label.trim() || isSubmitting}
              isLoading={isSubmitting}
              className="flex-1"
            >
              {mode === 'new' ? t('literature.create') : t('common.save')}
            </Button>
            <Button variant="secondary" size="sm" onClick={cancelForm}>
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      )}

      {/* Subscription list */}
      <div className="flex-1 space-y-1 overflow-y-auto">
        {subscriptions.length === 0 && (
          <p className="py-4 text-center text-[11px] text-[var(--text-secondary)]">
            {t('literature.noSubscriptions')}
          </p>
        )}
        {subscriptions.map((sub) => {
          const isSelected = selectedSubscriptionId === sub.subscription_id;
          return (
            <div
              key={sub.subscription_id}
              role="button"
              tabIndex={0}
              onClick={() => onSelectSubscription?.(isSelected ? undefined : sub.subscription_id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelectSubscription?.(isSelected ? undefined : sub.subscription_id);
                }
              }}
              className={`group relative cursor-pointer rounded-lg border p-3 transition ${
                isSelected
                  ? 'border-[var(--apple-blue)] bg-[var(--apple-blue)]/10'
                  : 'border-[var(--border)] bg-[var(--sidebar-primary)]/30 hover:bg-[var(--sidebar-primary)]'
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p
                    className={`truncate text-xs font-medium ${
                      isSelected ? 'text-[var(--apple-blue)]' : 'text-[var(--sidebar-foreground)]'
                    }`}
                  >
                    {sub.label}
                  </p>
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

                {/* Action buttons */}
                <div className="flex shrink-0 flex-col gap-1 opacity-0 transition group-hover:opacity-100">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      fetchMutation.mutate(sub.subscription_id);
                    }}
                    disabled={fetchMutation.isPending && fetchMutation.variables === sub.subscription_id}
                    className="rounded p-1 text-[var(--text-tertiary)] transition hover:text-[var(--apple-blue)]"
                    title={t('literature.refresh')}
                    aria-label={t('literature.refresh')}
                  >
                    <RefreshCw
                      size={12}
                      className={
                        fetchMutation.isPending && fetchMutation.variables === sub.subscription_id
                          ? 'animate-spin'
                          : ''
                      }
                    />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      startEdit(sub);
                    }}
                    className="rounded p-1 text-[var(--text-tertiary)] transition hover:text-[var(--apple-blue)]"
                    title={t('common.edit')}
                    aria-label={t('common.edit')}
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteMutation.mutate(sub.subscription_id);
                    }}
                    className="rounded p-1 text-[var(--text-tertiary)] transition hover:text-red-500"
                    title={t('literature.delete')}
                    aria-label={t('literature.delete')}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
