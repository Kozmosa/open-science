import { beforeEach, describe, expect, it } from 'vitest';
import {
  createDefaultWebUiSettings,
  readStoredSettings,
  settingsStorageKey,
  settingsStorageKeyForUser,
} from '@/features/settings';

describe('settings storage v6 active preferences', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('migrates legacy settings storage to the OpenScience key', () => {
    const settings = createDefaultWebUiSettings();
    settings.general.defaultRoute = 'tasks';
    window.localStorage.setItem('scholar-agent:webui-settings', JSON.stringify(settings));

    const result = readStoredSettings();

    expect(result.settings.general.defaultRoute).toBe('tasks');
    expect(window.localStorage.getItem(settingsStorageKey)).not.toBeNull();
  });

  it('claims an unscoped legacy document only after a stable user is known', () => {
    const settings = createDefaultWebUiSettings();
    settings.general.defaultRoute = 'tasks';
    window.localStorage.setItem('openscience:webui-settings', JSON.stringify(settings));

    expect(readStoredSettings('user-a').settings.general.defaultRoute).toBe('tasks');
    expect(window.localStorage.getItem('openscience:webui-settings')).toBeNull();
    expect(window.localStorage.getItem(settingsStorageKeyForUser('user-a'))).not.toBeNull();
    expect(readStoredSettings('user-b').settings.general.defaultRoute).toBe('today');
  });

  it('does not convert the retired serif preference into a color theme', () => {
    const legacy = createDefaultWebUiSettings() as unknown as Record<string, unknown>;
    legacy.version = 3;
    const general = legacy.general as Record<string, unknown>;
    general.appearance = { fontFamily: 'serif' };
    window.localStorage.setItem(settingsStorageKeyForUser('test-user'), JSON.stringify(legacy));

    expect(readStoredSettings().settings.general.appearance.theme).toBe('light');
  });

  it('creates only active browser preferences', () => {
    const settings = createDefaultWebUiSettings();

    expect(settings).toEqual({
      version: 6,
      general: {
        defaultRoute: 'today',
        terminal: { fontSize: 13 },
        editor: { fontSize: 14, fontFamily: 'monospace' },
        appearance: { theme: 'light', motionEnabled: true },
      },
      projectDefaults: {
        default: {
          defaultEnvironmentId: null,
          selection: { lastEnvironmentId: null },
        },
      },
    });
  });

  it('backfills enabled motion for older appearance settings', () => {
    const settings = createDefaultWebUiSettings() as unknown as Record<string, unknown>;
    settings.version = 5;
    const general = settings.general as Record<string, unknown>;
    general.appearance = { theme: 'dark' };
    window.localStorage.setItem(settingsStorageKeyForUser('test-user'), JSON.stringify(settings));

    expect(readStoredSettings().settings.general.appearance).toEqual({
      theme: 'dark',
      motionEnabled: true,
    });
  });

  it('migrates v5 active preferences and scrubs detached execution credentials', () => {
    window.localStorage.setItem(
      settingsStorageKey,
      JSON.stringify({
        version: 5,
        general: {
          defaultRoute: 'tasks',
          terminal: { fontSize: 16 },
          editor: { fontSize: 15, fontFamily: 'monospace' },
          appearance: { theme: 'dark', motionEnabled: false },
        },
        taskConfiguration: {
          defaultExecutionEngineId: 'codex-app-server',
          researchAgentProfiles: [{
            profileId: 'secret-profile',
            label: 'Secret profile',
            apiKey: 'sk-browser-secret',
            codexAuthJson: '{"token":"browser-secret"}',
            skills: ['disabled-skill'],
          }],
        },
        llmProviders: [{
          id: 'secret-provider',
          name: 'Secret provider',
          format: 'anthropic',
          baseUrl: 'https://example.invalid',
          apiKey: 'sk-provider-secret',
        }],
        projectDefaults: {
          default: {
            defaultEnvironmentId: 'env-1',
            defaultWorkspaceId: 'workspace-1',
            selection: { lastEnvironmentId: 'env-2', lastWorkspaceId: 'workspace-2' },
            environmentDefaults: {
              'env-1': {
                titleTemplate: 'Detached title',
                taskInputTemplate: 'Detached prompt',
                researchAgentProfileId: 'secret-profile',
                taskConfigurationId: 'raw-prompt',
              },
            },
          },
        },
      })
    );

    const result = readStoredSettings();

    expect(result.recoveryReason).toBeNull();
    expect(result.settings).toMatchObject({
      version: 6,
      general: {
        defaultRoute: 'tasks',
        terminal: { fontSize: 16 },
        editor: { fontSize: 15, fontFamily: 'monospace' },
        appearance: { theme: 'dark', motionEnabled: false },
      },
      projectDefaults: {
        default: {
          defaultEnvironmentId: 'env-1',
          selection: { lastEnvironmentId: 'env-2' },
        },
      },
    });
    const rewritten = window.localStorage.getItem(settingsStorageKey) ?? '';
    expect(rewritten).not.toContain('taskConfiguration');
    expect(rewritten).not.toContain('llmProviders');
    expect(rewritten).not.toContain('environmentDefaults');
    expect(rewritten).not.toContain('defaultWorkspaceId');
    expect(rewritten).not.toContain('lastWorkspaceId');
    expect(rewritten).not.toContain('browser-secret');
    expect(rewritten).not.toContain('disabled-skill');
  });

  it.each(['projects', 'terminal', 'tasks', 'workspaces', 'environments'] as const)(
    'preserves the legal v5 default route %s during the v6 upgrade',
    (defaultRoute) => {
      const settings = createDefaultWebUiSettings() as unknown as Record<string, unknown>;
      settings.version = 5;
      (settings.general as Record<string, unknown>).defaultRoute = defaultRoute;
      window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));

      const result = readStoredSettings();

      expect(result.settings.version).toBe(6);
      expect(result.settings.general.defaultRoute).toBe(defaultRoute);
    },
  );

  it('migrates the legacy containers route to environments', () => {
    const settings = createDefaultWebUiSettings() as unknown as Record<string, unknown>;
    settings.version = 5;
    (settings.general as Record<string, unknown>).defaultRoute = 'containers';
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));

    const result = readStoredSettings();

    expect(result.recoveryReason).toBeNull();
    expect(result.settings.general.defaultRoute).toBe('environments');
    expect(window.localStorage.getItem(settingsStorageKey)).not.toContain('containers');
  });

  it.each([
    { label: 'missing', value: undefined },
    { label: 'invalid', value: 'dashboard' },
  ])('migrates a $label v5 default route to today', ({ value }) => {
    const settings = createDefaultWebUiSettings() as unknown as Record<string, unknown>;
    settings.version = 5;
    const general = settings.general as Record<string, unknown>;
    if (value === undefined) delete general.defaultRoute;
    else general.defaultRoute = value;
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));

    const result = readStoredSettings();

    expect(result.settings.version).toBe(6);
    expect(result.settings.general.defaultRoute).toBe('today');
    expect(result.recoveryReason).toBe('invalid_document');
  });
});
