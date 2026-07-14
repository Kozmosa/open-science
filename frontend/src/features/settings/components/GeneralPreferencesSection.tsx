import { useState } from 'react';
import { Button, FormField, Input, SectionCard, SectionHeader, NativeSelect } from '@design-system/primitives';
import { useT } from '@/shared/i18n';
import type { DefaultRoute, WebUiSettingsDocument } from '@features/settings';
import { clampEditorFontSize, clampTerminalFontSize, maxEditorFontSize, maxTerminalFontSize, minEditorFontSize, minTerminalFontSize } from '@features/settings';

export interface GeneralDraftState {
  defaultRoute: DefaultRoute;
  terminalFontSize: string;
  editorFontSize: string;
  editorFontFamily: string;
}

export interface GeneralPreferencesSectionProps {
  savedGeneral: WebUiSettingsDocument['general'];
  onSave: (general: WebUiSettingsDocument['general']) => void;
  onReset: () => void;
}

export function GeneralPreferencesSection({
  savedGeneral,
  onSave,
  onReset,
}: GeneralPreferencesSectionProps) {
  const t = useT();
  const [draft, setDraft] = useState<GeneralDraftState>({
    defaultRoute: savedGeneral.defaultRoute,
    terminalFontSize: String(savedGeneral.terminal.fontSize),
    editorFontSize: String(savedGeneral.editor.fontSize),
    editorFontFamily: savedGeneral.editor.fontFamily,
  });
  const clampedTerminalFontSize = clampTerminalFontSize(Number.parseInt(draft.terminalFontSize, 10));
  const clampedEditorFontSize = clampEditorFontSize(Number.parseInt(draft.editorFontSize, 10));
  const hasChanges =
    draft.defaultRoute !== savedGeneral.defaultRoute ||
    clampedTerminalFontSize !== savedGeneral.terminal.fontSize ||
    clampedEditorFontSize !== savedGeneral.editor.fontSize ||
    draft.editorFontFamily !== savedGeneral.editor.fontFamily;

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.general.title')}
          description={t('pages.settings.general.description')}
        />
      }
    >

      <div className="grid gap-4 lg:grid-cols-2">
        <FormField label={t('pages.settings.general.defaultRouteLabel')}>
          <NativeSelect
            aria-label={t('pages.settings.general.defaultRouteLabel')}
            value={draft.defaultRoute}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                defaultRoute: event.target.value as DefaultRoute,
              }))
            }
          >
            <option value="terminal">{t('pages.settings.routes.terminal')}</option>
            <option value="tasks">{t('pages.settings.routes.tasks')}</option>
            <option value="workspaces">{t('pages.settings.routes.workspaces')}</option>
            <option value="environments">{t('pages.settings.routes.environments')}</option>
          </NativeSelect>
        </FormField>

        <FormField label={t('pages.settings.general.terminalFontSizeLabel')}>
          <Input
            aria-label={t('pages.settings.general.terminalFontSizeLabel')}
            type="number"
            min={minTerminalFontSize}
            max={maxTerminalFontSize}
            step={1}
            value={draft.terminalFontSize}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                terminalFontSize: event.target.value,
              }))
            }
          />
        </FormField>

        <FormField label={t('pages.settings.general.editorFontSizeLabel')}>
          <Input
            aria-label={t('pages.settings.general.editorFontSizeLabel')}
            type="number"
            min={minEditorFontSize}
            max={maxEditorFontSize}
            step={1}
            value={draft.editorFontSize}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                editorFontSize: event.target.value,
              }))
            }
          />
        </FormField>

        <FormField label={t('pages.settings.general.editorFontFamilyLabel')}>
          <Input
            aria-label={t('pages.settings.general.editorFontFamilyLabel')}
            type="text"
            value={draft.editorFontFamily}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                editorFontFamily: event.target.value,
              }))
            }
          />
        </FormField>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--bg-secondary)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
        <p>
          {t('pages.settings.general.terminalFontSizeHelp', {
            min: minTerminalFontSize,
            max: maxTerminalFontSize,
            current: clampedTerminalFontSize,
          })}
          {' / '}
          {t('pages.settings.general.editorFontSizeHelp', {
            min: minEditorFontSize,
            max: maxEditorFontSize,
            current: clampedEditorFontSize,
          })}
        </p>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={onReset}>
            {t('common.reset')}
          </Button>
          <Button
            onClick={() =>
              onSave({
                defaultRoute: draft.defaultRoute,
                terminal: {
                  fontSize: clampedTerminalFontSize,
                },
                editor: {
                  fontSize: clampedEditorFontSize,
                  fontFamily: draft.editorFontFamily || 'monospace',
                },
                appearance: savedGeneral.appearance,
              })
            }
            disabled={!hasChanges}
          >
            {t('common.saveChanges')}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

