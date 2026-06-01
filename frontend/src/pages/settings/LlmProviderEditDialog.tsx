import { useState, useEffect, useCallback, useRef } from 'react';
import { Button, FormField, Input, Select } from '../../components/ui';
import { useT } from '../../i18n';
import type { LlmProvider, LlmProviderFormat } from '../../settings';

interface LlmProviderEditDialogProps {
  provider: LlmProvider | null;
  onSave: (provider: LlmProvider) => void;
  onClose: () => void;
}

function generateId(): string {
  return crypto.randomUUID();
}

export function LlmProviderEditDialog({ provider, onSave, onClose }: LlmProviderEditDialogProps) {
  const t = useT();
  const isEditing = provider !== null;
  const overlayRef = useRef<HTMLDivElement>(null);

  const [name, setName] = useState('');
  const [format, setFormat] = useState<LlmProviderFormat>('anthropic');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [opusModel, setOpusModel] = useState('');
  const [sonnetModel, setSonnetModel] = useState('');
  const [haikuModel, setHaikuModel] = useState('');
  const [defaultModel, setDefaultModel] = useState('');

  useEffect(() => {
    if (provider) {
      setName(provider.name);
      setFormat(provider.format);
      setBaseUrl(provider.baseUrl);
      setApiKey(provider.apiKey);
      setOpusModel(provider.opusModel ?? '');
      setSonnetModel(provider.sonnetModel ?? '');
      setHaikuModel(provider.haikuModel ?? '');
      setDefaultModel(provider.defaultModel ?? '');
    } else {
      setName('');
      setFormat('anthropic');
      setBaseUrl('');
      setApiKey('');
      setOpusModel('');
      setSonnetModel('');
      setHaikuModel('');
      setDefaultModel('');
    }
  }, [provider]);

  useEffect(() => {
    overlayRef.current?.focus();
  }, []);

  const handleSave = () => {
    const savedProvider: LlmProvider = {
      id: provider?.id ?? generateId(),
      name: name.trim(),
      format,
      baseUrl: baseUrl.trim(),
      apiKey,
      ...(format === 'anthropic'
        ? {
            opusModel: opusModel.trim() || undefined,
            sonnetModel: sonnetModel.trim() || undefined,
            haikuModel: haikuModel.trim() || undefined,
          }
        : {
            defaultModel: defaultModel.trim() || undefined,
          }),
    };
    onSave(savedProvider);
    onClose();
  };

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    },
    [onClose]
  );

  const canSave = name.trim().length > 0 && baseUrl.trim().length > 0;

  return (
    <div
      ref={overlayRef}
      tabIndex={-1}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 outline-none"
      onKeyDown={handleKeyDown}
    >
      <div className="w-full max-w-lg rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-lg">
        <h2 className="mb-4 text-lg font-semibold">
          {isEditing ? t('pages.settings.llmProviders.editProvider') : t('pages.settings.llmProviders.addProvider')}
        </h2>

        <div className="space-y-4">
          <FormField label={t('pages.settings.llmProviders.nameLabel')}>
            <Input
              aria-label={t('pages.settings.llmProviders.nameLabel')}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Kimi Coding"
            />
          </FormField>

          <FormField label={t('pages.settings.llmProviders.formatLabel')}>
            <Select
              aria-label={t('pages.settings.llmProviders.formatLabel')}
              value={format}
              onChange={(e) => setFormat(e.target.value as LlmProviderFormat)}
            >
              <option value="anthropic">{t('pages.settings.llmProviders.formatAnthropic')}</option>
              <option value="openai-chat">{t('pages.settings.llmProviders.formatOpenAIChat')}</option>
              <option value="openai-responses">{t('pages.settings.llmProviders.formatOpenAIResponses')}</option>
            </Select>
          </FormField>

          <FormField label={t('pages.settings.llmProviders.baseUrlLabel')}>
            <Input
              aria-label={t('pages.settings.llmProviders.baseUrlLabel')}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={format === 'anthropic' ? 'https://api.anthropic.com/' : 'https://api.openai.com/'}
            />
          </FormField>

          <FormField label={t('pages.settings.llmProviders.apiKeyLabel')}>
            <Input
              aria-label={t('pages.settings.llmProviders.apiKeyLabel')}
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
          </FormField>

          {format === 'anthropic' ? (
            <div className="grid gap-4 sm:grid-cols-3">
              <FormField label={t('pages.settings.llmProviders.opusModelLabel')}>
                <Input
                  aria-label={t('pages.settings.llmProviders.opusModelLabel')}
                  value={opusModel}
                  onChange={(e) => setOpusModel(e.target.value)}
                  placeholder="claude-opus-4-7"
                />
              </FormField>
              <FormField label={t('pages.settings.llmProviders.sonnetModelLabel')}>
                <Input
                  aria-label={t('pages.settings.llmProviders.sonnetModelLabel')}
                  value={sonnetModel}
                  onChange={(e) => setSonnetModel(e.target.value)}
                  placeholder="claude-sonnet-4-6"
                />
              </FormField>
              <FormField label={t('pages.settings.llmProviders.haikuModelLabel')}>
                <Input
                  aria-label={t('pages.settings.llmProviders.haikuModelLabel')}
                  value={haikuModel}
                  onChange={(e) => setHaikuModel(e.target.value)}
                  placeholder="claude-haiku-4-5"
                />
              </FormField>
            </div>
          ) : (
            <FormField label={t('pages.settings.llmProviders.defaultModelLabel')}>
              <Input
                aria-label={t('pages.settings.llmProviders.defaultModelLabel')}
                value={defaultModel}
                onChange={(e) => setDefaultModel(e.target.value)}
                placeholder="gpt-4o"
              />
            </FormField>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSave} disabled={!canSave}>
            {t('common.save')}
          </Button>
        </div>
      </div>
    </div>
  );
}
