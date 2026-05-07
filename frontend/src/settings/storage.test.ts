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

    expect(settings.version).toBe(3);
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
      'reproduce-baseline-default',
      'discover-ideas-default',
      'validate-ideas-default',
    ]);
    const modes = settings.taskConfiguration.taskConfigurations.map((c) => c.mode);
    expect(modes).toContain('reproduce_baseline');
    expect(modes).toContain('discover_ideas');
    expect(modes).toContain('validate_ideas');
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
    expect(result.settings.version).toBe(3);
    expect(result.settings.general.defaultRoute).toBe('tasks');
    expect(result.settings.general.terminal.fontSize).toBe(16);
    expect(result.settings.projectDefaults.default.environmentDefaults['env-1']).toEqual({
      titleTemplate: 'Daily check',
      taskInputTemplate: 'Inspect the environment.',
      researchAgentProfileId: defaultResearchAgentProfileId,
      taskConfigurationId: rawPromptTaskConfigurationId,
    });
  });

  it('migrates v3 settings without skillModes from skills array', () => {
    window.localStorage.setItem(
      settingsStorageKey,
      JSON.stringify({
        version: 3,
        general: {
          defaultRoute: 'tasks',
          terminal: { fontSize: 13 },
          editor: { fontSize: 14, fontFamily: 'monospace' },
        },
        taskConfiguration: {
          defaultExecutionEngineId: 'claude-code',
          researchAgentProfiles: [
            {
              profileId: 'claude-code-default',
              label: 'Claude Code Default',
              systemPrompt: '',
              skills: ['web-search', 'code-analysis'],
              skillsPrompt: '',
              settingsJson: '',
            },
          ],
          taskConfigurations: [
            { configId: 'raw-prompt', label: 'Raw Prompt', mode: 'raw_prompt' },
          ],
          defaultResearchAgentProfileId: 'claude-code-default',
          defaultTaskConfigurationId: 'raw-prompt',
        },
        projectDefaults: {
          default: {
            defaultEnvironmentId: null,
            defaultWorkspaceId: null,
            selection: { lastEnvironmentId: null, lastWorkspaceId: null },
            environmentDefaults: {},
          },
        },
      })
    );

    const result = readStoredSettings();

    expect(result.recoveryReason).toBeNull();
    const profile = result.settings.taskConfiguration.researchAgentProfiles[0]!;
    expect(profile.skillModes).toEqual({
      'web-search': 'enabled',
      'code-analysis': 'enabled',
    });
    expect(profile.skills).toEqual(['web-search', 'code-analysis']);
  });

  it('preserves skillModes when present in v3 settings', () => {
    window.localStorage.setItem(
      settingsStorageKey,
      JSON.stringify({
        version: 3,
        general: {
          defaultRoute: 'tasks',
          terminal: { fontSize: 13 },
          editor: { fontSize: 14, fontFamily: 'monospace' },
        },
        taskConfiguration: {
          defaultExecutionEngineId: 'kimi-claude-code',
          researchAgentProfiles: [
            {
              profileId: 'claude-code-default',
              label: 'Claude Code Default',
              systemPrompt: '',
              skills: ['web-search'],
              skillModes: { 'web-search': 'auto', 'code-analysis': 'disabled' },
              skillsPrompt: '',
              settingsJson: '',
            },
          ],
          taskConfigurations: [
            { configId: 'raw-prompt', label: 'Raw Prompt', mode: 'raw_prompt' },
          ],
          defaultResearchAgentProfileId: 'claude-code-default',
          defaultTaskConfigurationId: 'raw-prompt',
        },
        projectDefaults: {
          default: {
            defaultEnvironmentId: null,
            defaultWorkspaceId: null,
            selection: { lastEnvironmentId: null, lastWorkspaceId: null },
            environmentDefaults: {},
          },
        },
      })
    );

    const result = readStoredSettings();
    const profile = result.settings.taskConfiguration.researchAgentProfiles[0]!;
    expect(profile.skillModes).toEqual({
      'web-search': 'auto',
      'code-analysis': 'disabled',
    });
    expect(profile.skills).toEqual(['web-search']);
  });
});
