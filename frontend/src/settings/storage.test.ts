import { beforeEach, describe, expect, it } from 'vitest';
import {
  createDefaultWebUiSettings,
  defaultResearchAgentProfileId,
  rawPromptTaskConfigurationId,
  readStoredSettings,
  settingsStorageKey,
  structuredResearchTaskConfigurationId,
} from '.';

describe('settings storage v2 task configuration', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('creates default task configuration catalog', () => {
    const settings = createDefaultWebUiSettings();

    expect(settings.version).toBe(2);
    expect(settings.taskConfiguration.defaultExecutionEngineId).toBe('claude-code');
    expect(settings.taskConfiguration.defaultResearchAgentProfileId).toBe(
      defaultResearchAgentProfileId
    );
    expect(settings.taskConfiguration.defaultTaskConfigurationId).toBe(rawPromptTaskConfigurationId);
    expect(settings.taskConfiguration.researchAgentProfiles[0]?.profileId).toBe(
      defaultResearchAgentProfileId
    );
    expect(settings.taskConfiguration.taskConfigurations.map((config) => config.configId)).toEqual([
      rawPromptTaskConfigurationId,
      structuredResearchTaskConfigurationId,
    ]);
  });

  it('upgrades v1 settings and preserves environment task templates', () => {
    window.localStorage.setItem(
      settingsStorageKey,
      JSON.stringify({
        version: 1,
        general: {
          defaultRoute: 'tasks',
          terminal: { fontSize: 16 },
        },
        projectDefaults: {
          default: {
            defaultEnvironmentId: 'env-1',
            selection: { lastEnvironmentId: 'env-2' },
            environmentDefaults: {
              'env-1': {
                titleTemplate: 'Daily check',
                taskInputTemplate: 'Inspect the environment.',
              },
            },
          },
        },
      })
    );

    const result = readStoredSettings();

    expect(result.recoveryReason).toBeNull();
    expect(result.settings.version).toBe(2);
    expect(result.settings.general.defaultRoute).toBe('tasks');
    expect(result.settings.general.terminal.fontSize).toBe(16);
    expect(result.settings.projectDefaults.default.environmentDefaults['env-1']).toEqual({
      titleTemplate: 'Daily check',
      taskInputTemplate: 'Inspect the environment.',
      researchAgentProfileId: defaultResearchAgentProfileId,
      taskConfigurationId: rawPromptTaskConfigurationId,
    });
  });
});
