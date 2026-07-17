import { useEffect, useState } from 'react';
import { Button, FormField, Input, SectionCard, SectionHeader, NativeSelect, SkillToggleGroup, Textarea } from '@design-system';
import { useT } from '@/shared/i18n';
import type { ExecutionEngineId, ResearchAgentProfileSettings, TaskConfigurationSettings } from '@features/settings';
import { useLlmProviders } from '@features/settings';
import type { SkillItem } from '@/shared/types';

export interface TaskConfigurationSectionProps {
  taskConfiguration: TaskConfigurationSettings;
  availableSkills: SkillItem[];
  onSaveTaskConfigurationSettings: (settings: TaskConfigurationSettings) => void;
  onResetTaskConfigurationSettings: () => void;
}

export function TaskConfigurationSection({
  taskConfiguration,
  availableSkills,
  onSaveTaskConfigurationSettings,
  onResetTaskConfigurationSettings,
}: TaskConfigurationSectionProps) {
  const t = useT();
  const { llmProviders: savedProviders } = useLlmProviders();
  const [profileDraft, setProfileDraft] = useState<ResearchAgentProfileSettings>(
    taskConfiguration.researchAgentProfiles.find(
      (p) => p.profileId === taskConfiguration.defaultResearchAgentProfileId
    ) ?? taskConfiguration.researchAgentProfiles[0] ?? {
      profileId: 'claude-code-default',
      label: 'Claude Code Default',
      systemPrompt: '',
      skills: [],
      skillModes: {},
      skillsPrompt: '',
      settingsJson: '',
      apiBaseUrl: '',
      apiKey: '',
      defaultOpusModel: '',
      defaultSonnetModel: '',
      defaultHaikuModel: '',
      envOverrides: '',
      codexBaseUrl: '',
      codexApiKey: '',
      codexModel: '',
      codexAppServerCommand: '',
      codexApprovalPolicy: '',
      codexConfigToml: '',
      codexAuthJson: '',
      codexConfigTomlSource: 'custom',
      codexAuthJsonSource: 'custom',
    }
  );
  const [defaultProfileId, setDefaultProfileId] = useState(
    taskConfiguration.defaultResearchAgentProfileId
  );
  const [defaultConfigId, setDefaultConfigId] = useState(taskConfiguration.defaultTaskConfigurationId);

  useEffect(() => {
    const nextProfile = taskConfiguration.researchAgentProfiles.find(
      (p) => p.profileId === taskConfiguration.defaultResearchAgentProfileId
    );
    // Reset draft when the external server configuration changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProfileDraft(
      nextProfile ?? taskConfiguration.researchAgentProfiles[0] ?? {
        profileId: 'claude-code-default',
        label: 'Claude Code Default',
        systemPrompt: '',
        skills: [],
        skillModes: {},
        skillsPrompt: '',
        settingsJson: '',
        apiBaseUrl: '',
        apiKey: '',
        defaultOpusModel: '',
        defaultSonnetModel: '',
        defaultHaikuModel: '',
        envOverrides: '',
        codexBaseUrl: '',
        codexApiKey: '',
        codexModel: '',
        codexAppServerCommand: '',
        codexApprovalPolicy: '',
        codexConfigToml: '',
        codexAuthJson: '',
        codexConfigTomlSource: 'custom',
        codexAuthJsonSource: 'custom',
      }
    );
    setDefaultProfileId(taskConfiguration.defaultResearchAgentProfileId);
    setDefaultConfigId(taskConfiguration.defaultTaskConfigurationId);
  }, [taskConfiguration]);

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.taskConfiguration.title')}
          description={t('pages.settings.taskConfiguration.description')}
        />
      }
    >

      <div className="grid gap-4 lg:grid-cols-2">
        <FormField label={t('pages.settings.taskConfiguration.executionEngineLabel')}>
          <NativeSelect
            aria-label={t('pages.settings.taskConfiguration.executionEngineLabel')}
            value={taskConfiguration.defaultExecutionEngineId}
            onChange={(event) =>
              onSaveTaskConfigurationSettings({
                ...taskConfiguration,
                defaultExecutionEngineId: event.target.value as ExecutionEngineId,
              })
            }
          >
            <option value="claude-code">{t('pages.settings.engine.claudeCode')}</option>
            <option value="agent-sdk">{t('pages.settings.engine.claudeAgent')}</option>
            <option value="codex-app-server">{t('pages.settings.engine.codexAppServer')}</option>
          </NativeSelect>
        </FormField>

        <FormField label={t('pages.settings.taskConfiguration.defaultTaskConfigurationLabel')}>
          <NativeSelect
            aria-label={t('pages.settings.taskConfiguration.defaultTaskConfigurationLabel')}
            value={defaultConfigId}
            onChange={(event) => setDefaultConfigId(event.target.value)}
          >
            {taskConfiguration.taskConfigurations.map((config) => (
              <option key={config.configId} value={config.configId}>
                {config.label}
              </option>
            ))}
          </NativeSelect>
        </FormField>
      </div>

      <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
        <FormField label={t('pages.settings.taskConfiguration.defaultResearchAgentLabel')}>
          <NativeSelect
            aria-label={t('pages.settings.taskConfiguration.defaultResearchAgentLabel')}
            value={defaultProfileId}
            onChange={(event) => {
              const nextId = event.target.value;
              setDefaultProfileId(nextId);
              const nextProfile = taskConfiguration.researchAgentProfiles.find(
                (profile) => profile.profileId === nextId
              );
              if (nextProfile) {
                setProfileDraft(nextProfile);
              }
            }}
          >
            {taskConfiguration.researchAgentProfiles.map((profile) => (
              <option key={profile.profileId} value={profile.profileId}>
                {profile.label}
              </option>
            ))}
          </NativeSelect>
        </FormField>

        <FormField label={t('pages.settings.taskConfiguration.profileLabel')}>
          <Input
            aria-label={t('pages.settings.taskConfiguration.profileLabel')}
            value={profileDraft.label}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, label: event.target.value }))
            }
          />
        </FormField>

        <FormField label={t('pages.settings.taskConfiguration.systemPromptLabel')}>
          <Textarea
            aria-label={t('pages.settings.taskConfiguration.systemPromptLabel')}
            value={profileDraft.systemPrompt}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, systemPrompt: event.target.value }))
            }
            className="min-h-24"
          />
        </FormField>

        {availableSkills.length > 0 ? (
          <div className="space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.settings.taskConfiguration.skillsLabel')}
            </span>
            <SkillToggleGroup
              skills={availableSkills}
              skillModes={profileDraft.skillModes}
              onChange={(skillModes) =>
                setProfileDraft((current) => ({
                  ...current,
                  skillModes,
                  skills: Object.entries(skillModes)
                    .filter(([, mode]) => mode === 'enabled')
                    .map(([skillId]) => skillId),
                }))
              }
            />
            <p className="text-xs text-[var(--text-tertiary)]">
              {t('pages.settings.taskConfiguration.skillsDescription')}
            </p>
          </div>
        ) : null}

        <FormField label={t('pages.settings.taskConfiguration.skillsPromptLabel')}>
          <Textarea
            aria-label={t('pages.settings.taskConfiguration.skillsPromptLabel')}
            value={profileDraft.skillsPrompt}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, skillsPrompt: event.target.value }))
            }
            className="min-h-16"
          />
        </FormField>

        {taskConfiguration.defaultExecutionEngineId === 'agent-sdk' && (
          <>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <FormField label={t('pages.settings.llmProviders.fillFromProvider')}>
                  <NativeSelect
                    aria-label={t('pages.settings.llmProviders.fillFromProvider')}
                    value=""
                    onChange={(event) => {
                      const providerId = event.target.value;
                      if (!providerId) return;
                      const provider = savedProviders.find((p) => p.id === providerId);
                      if (!provider) return;
                      setProfileDraft((current) => ({
                        ...current,
                        apiBaseUrl: provider.baseUrl,
                        apiKey: provider.apiKey,
                        defaultOpusModel:
                          provider.format === 'anthropic'
                            ? (provider.opusModel ?? current.defaultOpusModel)
                            : (provider.defaultModel ?? current.defaultOpusModel),
                        defaultSonnetModel:
                          provider.format === 'anthropic'
                            ? (provider.sonnetModel ?? current.defaultSonnetModel)
                            : (provider.defaultModel ?? current.defaultSonnetModel),
                        defaultHaikuModel:
                          provider.format === 'anthropic'
                            ? (provider.haikuModel ?? current.defaultHaikuModel)
                            : (provider.defaultModel ?? current.defaultHaikuModel),
                      }));
                    }}
                  >
                    <option value="">{t('pages.settings.llmProviders.customOption')}</option>
                    {savedProviders
                      .filter((p) => p.format === 'anthropic')
                      .map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name}
                        </option>
                      ))}
                  </NativeSelect>
                </FormField>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label={t('pages.settings.taskConfiguration.apiBaseUrlLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.apiBaseUrlLabel')}
                  value={profileDraft.apiBaseUrl}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, apiBaseUrl: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.apiBaseUrl')}
                />
              </FormField>
              <FormField label={t('pages.settings.taskConfiguration.apiKeyLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.apiKeyLabel')}
                  type="password"
                  value={profileDraft.apiKey}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, apiKey: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.apiKey')}
                />
              </FormField>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <FormField label={t('pages.settings.taskConfiguration.defaultOpusModelLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.defaultOpusModelLabel')}
                  value={profileDraft.defaultOpusModel}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, defaultOpusModel: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.opusModel')}
                />
              </FormField>
              <FormField label={t('pages.settings.taskConfiguration.defaultSonnetModelLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.defaultSonnetModelLabel')}
                  value={profileDraft.defaultSonnetModel}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, defaultSonnetModel: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.sonnetModel')}
                />
              </FormField>
              <FormField label={t('pages.settings.taskConfiguration.defaultHaikuModelLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.defaultHaikuModelLabel')}
                  value={profileDraft.defaultHaikuModel}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, defaultHaikuModel: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.haikuModel')}
                />
              </FormField>
            </div>
            <FormField label={t('pages.settings.taskConfiguration.envOverridesLabel')}>
              <Textarea
                aria-label={t('pages.settings.taskConfiguration.envOverridesLabel')}
                value={profileDraft.envOverrides}
                onChange={(event) =>
                  setProfileDraft((current) => ({ ...current, envOverrides: event.target.value }))
                }
                className="min-h-20 font-mono text-xs"
                placeholder={t('pages.settings.taskConfiguration.placeholders.envOverrides')}
              />
            </FormField>
          </>
        )}

        {taskConfiguration.defaultExecutionEngineId === 'codex-app-server' && (
          <>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <FormField label={t('pages.settings.llmProviders.fillFromProvider')}>
                  <NativeSelect
                    aria-label={t('pages.settings.llmProviders.fillFromProvider')}
                    value=""
                    onChange={(event) => {
                      const providerId = event.target.value;
                      if (!providerId) return;
                      const provider = savedProviders.find((p) => p.id === providerId);
                      if (!provider) return;
                      setProfileDraft((current) => ({
                        ...current,
                        codexBaseUrl: provider.baseUrl,
                        codexApiKey: provider.apiKey,
                        codexModel: provider.defaultModel ?? current.codexModel,
                      }));
                    }}
                  >
                    <option value="">{t('pages.settings.llmProviders.customOption')}</option>
                    {savedProviders
                      .filter((p) => p.format === 'openai-responses')
                      .map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name}
                        </option>
                      ))}
                  </NativeSelect>
                </FormField>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label={t('pages.settings.codex.baseUrl')}>
                <Input
                  aria-label={t('pages.settings.codex.baseUrl')}
                  value={profileDraft.codexBaseUrl}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, codexBaseUrl: event.target.value }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.baseUrl')}
                />
              </FormField>
              <FormField label={t('pages.settings.codex.apiKey')}>
                <Input
                  aria-label={t('pages.settings.codex.apiKey')}
                  type="password"
                  value={profileDraft.codexApiKey}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, codexApiKey: event.target.value }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.apiKey')}
                />
              </FormField>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <FormField label={t('pages.settings.codex.model')}>
                <Input
                  aria-label={t('pages.settings.codex.model')}
                  value={profileDraft.codexModel}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, codexModel: event.target.value }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.model')}
                />
              </FormField>
              <FormField label={t('pages.settings.codex.command')}>
                <Input
                  aria-label={t('pages.settings.codex.command')}
                  value={profileDraft.codexAppServerCommand}
                  onChange={(event) =>
                    setProfileDraft((current) => ({
                      ...current,
                      codexAppServerCommand: event.target.value,
                    }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.command')}
                />
              </FormField>
              <FormField label={t('pages.settings.codex.approval')}>
                <Input
                  aria-label={t('pages.settings.codex.approval')}
                  value={profileDraft.codexApprovalPolicy}
                  onChange={(event) =>
                    setProfileDraft((current) => ({
                      ...current,
                      codexApprovalPolicy: event.target.value,
                    }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.approval')}
                />
              </FormField>
            </div>
            <FormField label={t('pages.settings.codex.config')}>
              <Textarea
                aria-label={t('pages.settings.codex.config')}
                value={profileDraft.codexConfigToml}
                onChange={(event) =>
                  setProfileDraft((current) => ({
                    ...current,
                    codexConfigToml: event.target.value,
                    codexConfigTomlSource: 'custom',
                  }))
                }
                className="min-h-24 font-mono text-xs"
                placeholder={t('pages.settings.codex.placeholders.config')}
              />
            </FormField>
            <FormField label={t('pages.settings.codex.auth')}>
              <Textarea
                aria-label={t('pages.settings.codex.auth')}
                value={profileDraft.codexAuthJson}
                onChange={(event) =>
                  setProfileDraft((current) => ({
                    ...current,
                    codexAuthJson: event.target.value,
                    codexAuthJsonSource: 'custom',
                  }))
                }
                className="min-h-24 font-mono text-xs"
                placeholder={t('pages.settings.codex.placeholders.auth')}
              />
            </FormField>
          </>
        )}

        <FormField label={t('pages.settings.taskConfiguration.settingsJsonLabel')}>
          <Textarea
            aria-label={t('pages.settings.taskConfiguration.settingsJsonLabel')}
            value={profileDraft.settingsJson}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, settingsJson: event.target.value }))
            }
            className="min-h-28 font-mono text-xs"
          />
        </FormField>
      </div>

      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="secondary" onClick={onResetTaskConfigurationSettings}>
          {t('common.reset')}
        </Button>
        <Button
          onClick={() => {
            const nextProfiles = taskConfiguration.researchAgentProfiles.some(
              (p) => p.profileId === profileDraft.profileId
            )
              ? taskConfiguration.researchAgentProfiles.map((p) =>
                  p.profileId === profileDraft.profileId ? profileDraft : p
                )
              : [...taskConfiguration.researchAgentProfiles, profileDraft];
            onSaveTaskConfigurationSettings({
              ...taskConfiguration,
              researchAgentProfiles: nextProfiles,
              defaultResearchAgentProfileId: defaultProfileId,
              defaultTaskConfigurationId: defaultConfigId,
            });
          }}
        >
          {t('common.saveChanges')}
        </Button>
      </div>
    </SectionCard>
  );
}

