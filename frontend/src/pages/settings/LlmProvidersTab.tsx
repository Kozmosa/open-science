import { useState } from 'react';
import { Button, SectionCard, SectionHeader } from '../../components/ui';
import { SectionStack } from '../../components/layout';
import { useT } from '../../i18n';
import { useSettings } from '../../settings';
import type { LlmProvider } from '../../settings';
import { LlmProviderEditDialog } from './LlmProviderEditDialog';

export function LlmProvidersTab() {
  const t = useT();
  const { settings, saveLlmProvider, updateLlmProvider, deleteLlmProvider } = useSettings();
  const providers = settings.llmProviders;

  const [editingProvider, setEditingProvider] = useState<LlmProvider | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  const handleAdd = () => {
    setEditingProvider(null);
    setIsDialogOpen(true);
  };

  const handleEdit = (provider: LlmProvider) => {
    setEditingProvider(provider);
    setIsDialogOpen(true);
  };

  const handleSave = (provider: LlmProvider) => {
    if (editingProvider) {
      updateLlmProvider(provider);
    } else {
      saveLlmProvider(provider);
    }
  };

  const handleDelete = (provider: LlmProvider) => {
    if (confirm(t('pages.settings.llmProviders.confirmDelete').replace('{{name}}', provider.name))) {
      deleteLlmProvider(provider.id);
    }
  };

  return (
    <SectionStack>
      <SectionCard
        header={
          <SectionHeader
            title={t('pages.settings.llmProviders.title')}
            description={t('pages.settings.llmProviders.description')}
          />
        }
      >
        <div className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={handleAdd}>{t('pages.settings.llmProviders.addProvider')}</Button>
          </div>

          {providers.length === 0 ? (
            <p className="text-sm text-[var(--text-secondary)]">
              {t('pages.settings.llmProviders.noProviders')}
            </p>
          ) : (
            <div className="space-y-2">
              {providers.map((provider) => (
                <div
                  key={provider.id}
                  className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{provider.name}</span>
                      <span className="rounded-full bg-[var(--bg-secondary)] px-2 py-0.5 text-xs font-medium uppercase text-[var(--text-secondary)] border border-[var(--border)]">
                        {provider.format}
                      </span>
                    </div>
                    <div className="text-xs text-[var(--text-secondary)]">{provider.baseUrl}</div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="secondary" size="sm" onClick={() => handleEdit(provider)}>
                      {t('common.edit')}
                    </Button>
                    <Button variant="danger" size="sm" onClick={() => handleDelete(provider)}>
                      {t('common.delete')}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </SectionCard>

      {isDialogOpen && (
        <LlmProviderEditDialog
          provider={editingProvider}
          onSave={handleSave}
          onClose={() => setIsDialogOpen(false)}
        />
      )}
    </SectionStack>
  );
}
