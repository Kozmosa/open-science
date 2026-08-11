/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from 'react';
import { applyOsciTheme, MotionPreferenceProvider } from '@design-system';
import type { EnvironmentSelectionPreferences } from '@features/environments';
import {
  clampEditorFontSize,
  clampTerminalFontSize,
  createDefaultWebUiSettings,
  isDefaultRoute,
} from '@features/settings/utils/defaults';
import { readStoredSettings, writeStoredSettings } from '@features/settings/utils/storage';
import type {
  DefaultProjectSettings,
  SettingsRecoveryReason,
  WebUiSettingsDocument,
} from '@features/settings/types';

import { GeneralSettingsProvider } from './GeneralSettingsContext';
import { AppearanceSettingsProvider } from './AppearanceSettingsContext';

// ── Shared state helpers ──────────────────────────────────────────

interface SettingsState {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
}

function getOrCreateProjectSettings(
  projectDefaults: Record<string, DefaultProjectSettings>,
  projectId: string
): DefaultProjectSettings {
  return (
    projectDefaults[projectId] ?? {
      defaultEnvironmentId: null,
      selection: { lastEnvironmentId: null },
    }
  );
}

function sanitizeSettings(settings: WebUiSettingsDocument): WebUiSettingsDocument {
  const editorFontSize = clampEditorFontSize(settings.general.editor?.fontSize);
  const editorFontFamily =
    typeof settings.general.editor?.fontFamily === 'string' &&
    settings.general.editor.fontFamily.length > 0
      ? settings.general.editor.fontFamily
      : 'monospace';

  const appearanceTheme =
    settings.general.appearance?.theme === 'dark' || settings.general.appearance?.theme === 'system'
      ? settings.general.appearance.theme
      : 'light';
  const motionEnabled = settings.general.appearance?.motionEnabled !== false;

  const sanitizedProjectDefaults: Record<string, DefaultProjectSettings> = {};
  for (const [projectId, projectSettings] of Object.entries(settings.projectDefaults)) {
    sanitizedProjectDefaults[projectId] = {
      defaultEnvironmentId:
        typeof projectSettings.defaultEnvironmentId === 'string'
          ? projectSettings.defaultEnvironmentId : null,
      selection: {
        lastEnvironmentId:
          typeof projectSettings.selection?.lastEnvironmentId === 'string'
            ? projectSettings.selection.lastEnvironmentId : null,
      },
    };
  }

  if (!sanitizedProjectDefaults.default) {
    sanitizedProjectDefaults.default = {
      defaultEnvironmentId: null,
      selection: { lastEnvironmentId: null },
    };
  }

  return {
    version: 6,
    general: {
      defaultRoute: isDefaultRoute(settings.general.defaultRoute)
        ? settings.general.defaultRoute : 'today',
      terminal: { fontSize: clampTerminalFontSize(settings.general.terminal.fontSize) },
      editor: { fontSize: editorFontSize, fontFamily: editorFontFamily },
      appearance: { theme: appearanceTheme, motionEnabled },
    },
    projectDefaults: sanitizedProjectDefaults,
  };
}

// ── Legacy context (backwards compatible) ─────────────────────────

const LegacySettingsContext = createContext<{
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
  saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => void;
  resetGeneralPreferences: () => void;
  saveAppearanceSettings: (appearance: WebUiSettingsDocument['general']['appearance']) => void;
  resetAppearanceSettings: () => void;
  saveProjectDefaultEnvironment: (projectId: string, environmentId: string | null) => void;
  rememberSelectedEnvironment: (projectId: string, environmentId: string | null) => void;
} | null>(null);

// ── Composite Provider ───────────────────────────────────────────

interface ProviderProps {
  children: ReactNode;
  userId?: string;
}

export function SettingsProvider({ children, userId = 'test-user' }: ProviderProps) {
  const [state, setState] = useState<SettingsState>(() => readStoredSettings(userId));

  useLayoutEffect(() => {
    const preference = state.settings.general.appearance.theme;
    applyOsciTheme(preference);
    if (preference !== 'system' || typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => applyOsciTheme('system');
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [state.settings.general.appearance.theme]);

  useLayoutEffect(() => {
    document.documentElement.dataset.osciMotion = state.settings.general.appearance.motionEnabled
      ? 'full'
      : 'reduced';
  }, [state.settings.general.appearance.motionEnabled]);

  const commitSettings = useCallback((nextSettings: WebUiSettingsDocument): void => {
    const sanitized = sanitizeSettings(nextSettings);
    writeStoredSettings(sanitized, userId);
    setState({ settings: sanitized, recoveryReason: null });
  }, [userId]);

  // ── Domain context values ────────────────────────────────────

  const generalValue = useMemo(() => ({
    settings: state.settings,
    recoveryReason: state.recoveryReason,
    saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => {
      commitSettings({
        ...state.settings,
        general: {
          defaultRoute: general.defaultRoute,
          terminal: { fontSize: general.terminal.fontSize },
          editor: { fontSize: general.editor.fontSize, fontFamily: general.editor.fontFamily },
          appearance: state.settings.general.appearance,
        },
      });
    },
    resetGeneralPreferences: () => {
      const defaults = createDefaultWebUiSettings();
      commitSettings({ ...state.settings, general: defaults.general });
    },
    saveAppearanceSettings: (appearance: WebUiSettingsDocument['general']['appearance']) => {
      commitSettings({ ...state.settings, general: { ...state.settings.general, appearance } });
    },
    resetAppearanceSettings: () => {
      const defaults = createDefaultWebUiSettings();
      commitSettings({ ...state.settings, general: { ...state.settings.general, appearance: defaults.general.appearance } });
    },
  }), [state, commitSettings]);

  const appearanceValue = useMemo(() => ({
    appearance: state.settings.general.appearance,
    saveAppearanceSettings: (appearance: WebUiSettingsDocument['general']['appearance']) => {
      commitSettings({ ...state.settings, general: { ...state.settings.general, appearance } });
    },
    resetAppearanceSettings: () => {
      const defaults = createDefaultWebUiSettings();
      commitSettings({ ...state.settings, general: { ...state.settings.general, appearance: defaults.general.appearance } });
    },
  }), [state, commitSettings]);

  const projectDefaultsValue = useMemo(() => ({
    saveProjectDefaultEnvironment: (projectId: string, environmentId: string | null) => {
      const cp = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
      commitSettings({
        ...state.settings,
        projectDefaults: { ...state.settings.projectDefaults, [projectId]: { ...cp, defaultEnvironmentId: environmentId } },
      });
    },
    rememberSelectedEnvironment: (projectId: string, environmentId: string | null) => {
      const cp = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
      commitSettings({
        ...state.settings,
        projectDefaults: {
          ...state.settings.projectDefaults,
          [projectId]: { ...cp, selection: { ...cp.selection, lastEnvironmentId: environmentId } },
        },
      });
    },
  }), [state, commitSettings]);

  // ── Legacy value for backwards compatibility ─────────────────

  const legacyValue = useMemo(() => {
    // generalValue carries `settings`/`recoveryReason` as well — avoid duplicate keys
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { settings: _settings, recoveryReason: _recoveryReason, ...generalRest } = generalValue;
    return {
      settings: state.settings,
      recoveryReason: state.recoveryReason,
      ...generalRest,
      ...appearanceValue,
      ...projectDefaultsValue,
    };
  }, [state, generalValue, appearanceValue, projectDefaultsValue]);

  return (
    <LegacySettingsContext.Provider value={legacyValue}>
      <GeneralSettingsProvider value={generalValue}>
        <AppearanceSettingsProvider value={appearanceValue}>
          <MotionPreferenceProvider motionEnabled={state.settings.general.appearance.motionEnabled}>
            {children}
          </MotionPreferenceProvider>
        </AppearanceSettingsProvider>
      </GeneralSettingsProvider>
    </LegacySettingsContext.Provider>
  );
}

// ── Legacy hook (deprecated) ─────────────────────────────────────

/** @deprecated Prefer useGeneralSettings / useAppearanceSettings. */
export function useSettings() {
  const context = useContext(LegacySettingsContext);
  if (context === null) {
    throw new Error('useSettings must be used within a SettingsProvider');
  }
  return context;
}

export function useEnvironmentSelectionPreferences(): EnvironmentSelectionPreferences {
  const { settings, rememberSelectedEnvironment } = useSettings();
  return useMemo(() => ({
    getProjectSelection: (projectId: string) => {
      const projectSettings = settings.projectDefaults[projectId] ?? settings.projectDefaults.default;
      return {
        defaultEnvironmentId: projectSettings?.defaultEnvironmentId ?? null,
        rememberedEnvironmentId: projectSettings?.selection.lastEnvironmentId ?? null,
      };
    },
    rememberSelectedEnvironment,
  }), [rememberSelectedEnvironment, settings.projectDefaults]);
}

export function useTerminalFontSize(): number {
  return useSettings().settings.general.terminal.fontSize;
}

export function useEditorSettings(): { fontSize: number; fontFamily: string } {
  const { settings } = useSettings();
  return { fontSize: settings.general.editor.fontSize, fontFamily: settings.general.editor.fontFamily };
}
