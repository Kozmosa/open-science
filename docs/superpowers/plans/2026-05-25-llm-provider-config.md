# LLM Provider 全局配置管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 SettingsPage 新增「LLM Providers」Tab，支持创建/编辑/删除全局 LLM Provider 配置；在 TaskConfiguration 的 profile 编辑区新增 provider 选择器，选择后自动回填到 profile 字段。

**Architecture:** 纯前端实现。Provider 数据存储在 `WebUiSettingsDocument.llmProviders` 数组中。Provider 编辑表单根据 `format`（openai/anthropic）自适应显示模型字段。Profile 编辑区的 provider 选择器读取全局 provider 列表，选择后即时回填 profile 的 `apiBaseUrl`/`apiKey`/`default*Model` 字段。

**Tech Stack:** React + TypeScript, Tailwind CSS, localStorage

---

## File Structure

| File | Action | Responsibility |
|------|--------|--------------|
| `frontend/src/settings/types.ts` | Modify | Add `LlmProviderFormat`, `LlmProvider`; extend `WebUiSettingsDocument` |
| `frontend/src/settings/defaults.ts` | Modify | `createDefaultWebUiSettings()` returns `llmProviders: []` |
| `frontend/src/settings/storage.ts` | Modify | `readStoredSettings()` backward-compat for missing `llmProviders` |
| `frontend/src/settings/context.tsx` | Modify | Add `saveLlmProvider` / `updateLlmProvider` / `deleteLlmProvider` to context |
| `frontend/src/i18n/messages.ts` | Modify | Add LLM Provider i18n keys (en + zh) |
| `frontend/src/pages/settings/LlmProviderEditDialog.tsx` | Create | Dialog form for creating/editing a provider; adaptive fields per format |
| `frontend/src/pages/settings/LlmProvidersTab.tsx` | Create | Tab content: provider list, add/edit/delete buttons, empty state |
| `frontend/src/pages/SettingsPage.tsx` | Modify | Add `llmProviders` tab, render `LlmProvidersTab`, add provider selector to profile editor |
| `frontend/__tests__/pages/SettingsPage.test.tsx` | Modify | Add test: LLM Providers tab renders and provider CRUD persists |

---

### Task 1: Type definitions + defaults + storage backward compatibility

**Files:**
- Modify: `frontend/src/settings/types.ts`
- Modify: `frontend/src/settings/defaults.ts`
- Modify: `frontend/src/settings/storage.ts`

- [ ] **Step 1: Add types to `types.ts`**

Add at the bottom of `types.ts` (before the `WebUiSettingsDocument` interface, or after — order does not matter for TypeScript):

```typescript
export type LlmProviderFormat = 'openai' | 'anthropic';

export interface LlmProvider {
  id: string;
  name: string;
  format: LlmProviderFormat;
  baseUrl: string;
  apiKey: string;
  opusModel?: string;
  sonnetModel?: string;
  haikuModel?: string;
  defaultModel?: string;
}
```

Then extend `WebUiSettingsDocument`:

```typescript
export interface WebUiSettingsDocument {
  version: 3;
  general: {
    defaultRoute: DefaultRoute;
    terminal: {
      fontSize: number;
    };
    editor: {
      fontSize: number;
      fontFamily: string;
    };
    appearance: AppearanceSettings;
  };
  taskConfiguration: TaskConfigurationSettings;
  projectDefaults: Record<string, DefaultProjectSettings>;
  llmProviders: LlmProvider[]; // ADD THIS LINE
}
```

- [ ] **Step 2: Update `defaults.ts`**

In `createDefaultWebUiSettings()`, add `llmProviders: []`:

```typescript
export function createDefaultWebUiSettings(): WebUiSettingsDocument {
  return {
    version: 3,
    general: {
      defaultRoute: 'terminal',
      terminal: {
        fontSize: defaultTerminalFontSize,
      },
      editor: {
        fontSize: defaultEditorFontSize,
        fontFamily: defaultEditorFontFamily,
      },
      appearance: {
        fontFamily: 'sans-serif',
      },
    },
    taskConfiguration: createDefaultTaskConfigurationSettings(),
    projectDefaults: {
      default: createDefaultProjectSettings(),
    },
    llmProviders: [], // ADD THIS LINE
  };
}
```

- [ ] **Step 3: Update `storage.ts`**

In `readStoredSettings()`, after `const projectDefaultsMap = ...` and before the `taskConfiguration` normalization, add:

```typescript
  // Normalize llmProviders (backward compat: missing = empty array)
  const llmProviders = Array.isArray(parsed.llmProviders)
    ? parsed.llmProviders.filter((item: unknown): item is LlmProvider => {
        if (typeof item !== 'object' || item === null) return false;
        const p = item as Record<string, unknown>;
        return (
          typeof p.id === 'string' &&
          typeof p.name === 'string' &&
          (p.format === 'openai' || p.format === 'anthropic') &&
          typeof p.baseUrl === 'string' &&
          typeof p.apiKey === 'string'
        );
      })
    : [];
```

Then in the returned `settings` object, add `llmProviders`:

```typescript
    settings: {
      version: 3,
      general: { /* ... */ },
      taskConfiguration,
      projectDefaults: projectDefaultsMap,
      llmProviders, // ADD THIS LINE
    },
```

Import `LlmProvider` at the top of `storage.ts`:

```typescript
import type {
  /* existing imports... */
  LlmProvider,
} from './types';
```

- [ ] **Step 4: Run type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/settings/types.ts frontend/src/settings/defaults.ts frontend/src/settings/storage.ts
git commit -m "feat: add LlmProvider types, defaults, and storage compat

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Settings Context — Provider CRUD methods

**Files:**
- Modify: `frontend/src/settings/context.tsx`

- [ ] **Step 1: Extend `SettingsContextValue`**

Add three new methods to the interface:

```typescript
interface SettingsContextValue {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
  activeProjectId: string;
  setActiveProjectId: (projectId: string) => void;
  saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => void;
  resetGeneralPreferences: () => void;
  saveAppearanceSettings: (appearance: AppearanceSettings) => void;
  resetAppearanceSettings: () => void;
  saveTaskConfigurationSettings: (taskConfiguration: TaskConfigurationSettings) => void;
  resetTaskConfigurationSettings: () => void;
  saveResearchAgentProfile: (profile: ResearchAgentProfileSettings) => void;
  saveProjectDefaultEnvironment: (projectId: string, environmentId: string | null) => void;
  saveProjectDefaultWorkspace: (projectId: string, workspaceId: string | null) => void;
  saveProjectEnvironmentDefaults: (
    projectId: string,
    environmentId: string,
    defaults: EnvironmentTaskDefaults
  ) => void;
  resetProjectEnvironmentDefaults: (projectId: string, environmentId: string) => void;
  rememberSelectedEnvironment: (projectId: string, environmentId: string | null) => void;
  rememberSelectedWorkspace: (projectId: string, workspaceId: string | null) => void;
  getProjectEnvironmentDefaults: (projectId: string, environmentId: string | null) => EnvironmentTaskDefaults;
  saveLlmProvider: (provider: LlmProvider) => void;      // NEW
  updateLlmProvider: (provider: LlmProvider) => void;    // NEW
  deleteLlmProvider: (providerId: string) => void;        // NEW
}
```

Import `LlmProvider`:

```typescript
import type {
  AppearanceSettings,
  DefaultProjectSettings,
  EnvironmentTaskDefaults,
  LlmProvider,  // ADD
  ResearchAgentProfileSettings,
  SettingsRecoveryReason,
  TaskConfigurationSettings,
  WebUiSettingsDocument,
} from './types';
```

- [ ] **Step 2: Implement the three methods in `useMemo`**

Inside the `value = useMemo(() => ({ ... }), [state, activeProjectId])`, after `getProjectEnvironmentDefaults` and before the closing `}),`, add:

```typescript
      saveLlmProvider: (provider) => {
        commitSettings({
          ...state.settings,
          llmProviders: [...state.settings.llmProviders, provider],
        });
      },
      updateLlmProvider: (provider) => {
        commitSettings({
          ...state.settings,
          llmProviders: state.settings.llmProviders.map((p) =>
            p.id === provider.id ? provider : p
          ),
        });
      },
      deleteLlmProvider: (providerId) => {
        commitSettings({
          ...state.settings,
          llmProviders: state.settings.llmProviders.filter((p) => p.id !== providerId),
        });
      },
```

- [ ] **Step 3: Run type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/settings/context.tsx
git commit -m "feat: add LLM provider CRUD to settings context

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: i18n translations

**Files:**
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Add English translations**

Under `en.pages.settings`, after the `users` block, add:

```typescript
        llmProviders: {
          title: 'LLM Providers',
          description: 'Manage global LLM API configurations for quick profile fill.',
          addProvider: 'Add Provider',
          editProvider: 'Edit Provider',
          deleteProvider: 'Delete Provider',
          noProviders: 'No providers configured yet. Add one to enable quick fill in agent profiles.',
          nameLabel: 'Name',
          formatLabel: 'Format',
          baseUrlLabel: 'Base URL',
          apiKeyLabel: 'API Key',
          opusModelLabel: 'Opus Model',
          sonnetModelLabel: 'Sonnet Model',
          haikuModelLabel: 'Haiku Model',
          defaultModelLabel: 'Default Model',
          formatAnthropic: 'Anthropic',
          formatOpenAI: 'OpenAI',
          confirmDelete: 'Delete provider "{{name}}"?',
          fillFromProvider: 'Fill from provider',
          customOption: 'Custom',
        },
```

Also add the tab label under `en.pages.settings.tabs`:

```typescript
        tabs: {
          general: 'General',
          llmProviders: 'LLM Providers',  // ADD
          users: 'User Management',
          envAccess: 'Environment Access',
          collaborators: 'Collaborators',
        },
```

- [ ] **Step 2: Add Chinese translations**

Under `zh.pages.settings`, after the `users` block, add:

```typescript
        llmProviders: {
          title: 'LLM 提供商',
          description: '管理全局 LLM API 配置，以便在 Agent 配置中快速填充。',
          addProvider: '添加提供商',
          editProvider: '编辑提供商',
          deleteProvider: '删除提供商',
          noProviders: '尚未配置任何提供商。添加一个以在 Agent 配置中启用快速填充。',
          nameLabel: '名称',
          formatLabel: '格式',
          baseUrlLabel: 'Base URL',
          apiKeyLabel: 'API Key',
          opusModelLabel: 'Opus 模型',
          sonnetModelLabel: 'Sonnet 模型',
          haikuModelLabel: 'Haiku 模型',
          defaultModelLabel: '默认模型',
          formatAnthropic: 'Anthropic',
          formatOpenAI: 'OpenAI',
          confirmDelete: '删除提供商「{{name}}」？',
          fillFromProvider: '从提供商填充',
          customOption: '自定义',
        },
```

Also add the tab label under `zh.pages.settings.tabs`:

```typescript
        tabs: {
          general: '通用',
          llmProviders: 'LLM 提供商',  // ADD
          users: '用户管理',
          envAccess: '环境访问',
          collaborators: '协作者',
        },
```

- [ ] **Step 3: Run type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

Expected: 0 errors. If you get "Type instantiation is excessively deep", it usually means a typo in the nested object structure — check that both `en` and `zh` have exactly the same nesting.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/messages.ts
git commit -m "feat: add LLM provider i18n translations

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: LlmProviderEditDialog component

**Files:**
- Create: `frontend/src/pages/settings/LlmProviderEditDialog.tsx`

- [ ] **Step 1: Create the dialog component**

```typescript
import { useState, useEffect } from 'react';
import { Button, FormField, Input, Select } from '../../components/ui';
import { useT } from '../../i18n';
import type { LlmProvider, LlmProviderFormat } from '../../settings';

interface LlmProviderEditDialogProps {
  provider: LlmProvider | null;
  onSave: (provider: LlmProvider) => void;
  onClose: () => void;
}

function generateId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function LlmProviderEditDialog({ provider, onSave, onClose }: LlmProviderEditDialogProps) {
  const t = useT();
  const isEditing = provider !== null;

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

  const canSave = name.trim().length > 0 && baseUrl.trim().length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
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
              <option value="openai">{t('pages.settings.llmProviders.formatOpenAI')}</option>
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
```

- [ ] **Step 2: Run type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/settings/LlmProviderEditDialog.tsx
git commit -m "feat: add LlmProviderEditDialog component

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: LlmProvidersTab component

**Files:**
- Create: `frontend/src/pages/settings/LlmProvidersTab.tsx`

- [ ] **Step 1: Create the tab component**

```typescript
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
```

- [ ] **Step 2: Run type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/settings/LlmProvidersTab.tsx
git commit -m "feat: add LlmProvidersTab component

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: SettingsPage — integrate LLM Providers tab

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Import `LlmProvidersTab`**

Add import near the top (after existing tab imports):

```typescript
import { LlmProvidersTab } from './settings/LlmProvidersTab';
```

- [ ] **Step 2: Add `llmProviders` to tabs array**

Change the `tabs` definition from:

```typescript
  const tabs = [
    { key: 'general' as const, label: t('pages.settings.tabs.general') },
    ...(currentUser?.role === 'admin' ? [
      { key: 'users' as const, label: t('pages.settings.tabs.users') },
      { key: 'envAccess' as const, label: t('pages.settings.tabs.envAccess') },
      { key: 'collaborators' as const, label: t('pages.settings.tabs.collaborators') },
    ] : []),
  ];
```

To:

```typescript
  const tabs = [
    { key: 'general' as const, label: t('pages.settings.tabs.general') },
    { key: 'llmProviders' as const, label: t('pages.settings.tabs.llmProviders') },
    ...(currentUser?.role === 'admin' ? [
      { key: 'users' as const, label: t('pages.settings.tabs.users') },
      { key: 'envAccess' as const, label: t('pages.settings.tabs.envAccess') },
      { key: 'collaborators' as const, label: t('pages.settings.tabs.collaborators') },
    ] : []),
  ];
```

- [ ] **Step 3: Add tab rendering**

After `{activeTab === 'general' && (...)}` and before `{activeTab === 'users' && <UsersTab />}`, add:

```typescript
        {activeTab === 'llmProviders' && <LlmProvidersTab />}
```

- [ ] **Step 4: Run type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: integrate LLM Providers tab into SettingsPage

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: TaskConfigurationSection — add Provider selector + auto-fill

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Locate the profile editor API Configuration block**

Find the block starting with:

```typescript
        {taskConfiguration.defaultExecutionEngineId === 'agent-sdk' && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label={t('pages.settings.taskConfiguration.apiBaseUrlLabel')}>
```

This is where the `agent-sdk` API fields are rendered (around line 435–500). Add a provider selector **before** the `apiBaseUrl` field, inside the `agent-sdk` conditional block.

- [ ] **Step 2: Add provider selector + fill logic**

Inside the `taskConfiguration.defaultExecutionEngineId === 'agent-sdk'` conditional, right after the `<>` and before the first `<div className="grid gap-4 sm:grid-cols-2">`, insert:

```typescript
            <div className="flex items-end gap-2">
              <FormField label={t('pages.settings.llmProviders.fillFromProvider')} className="flex-1">
                <Select
                  aria-label={t('pages.settings.llmProviders.fillFromProvider')}
                  value=""
                  onChange={(event) => {
                    const providerId = event.target.value;
                    if (!providerId) return;
                    const provider = settings.llmProviders.find((p) => p.id === providerId);
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
                  {settings.llmProviders.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.name}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
```

**Important:** The `Select` component in this codebase may not accept a `className` prop on `FormField`. If `FormField` does not have a `className` prop, wrap the `<Select>` and its label in a plain `<div className="flex-1">` instead:

```typescript
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <FormField label={t('pages.settings.llmProviders.fillFromProvider')}>
                  <Select ...>...</Select>
                </FormField>
              </div>
            </div>
```

The `settings` variable is already available in the `TaskConfigurationSection` scope (destructured from `useSettings()` at the top of the component).

- [ ] **Step 3: Run type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: add provider selector with auto-fill to profile editor

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: Tests

**Files:**
- Modify: `frontend/__tests__/pages/SettingsPage.test.tsx`

- [ ] **Step 1: Add test for LLM Providers tab**

After the last test in `describe('SettingsPage')`, add:

```typescript
  it('renders LLM Providers tab and allows adding a provider', async () => {
    renderWithProviders(<SettingsPage />);

    // Wait for page to load
    await screen.findByRole('heading', { name: 'Settings' });

    // Click the LLM Providers tab
    fireEvent.click(screen.getByRole('button', { name: 'LLM Providers' }));

    // Should show the empty state
    expect(
      screen.getByText(/No providers configured yet/)
    ).toBeInTheDocument();

    // Click Add Provider
    fireEvent.click(screen.getByRole('button', { name: 'Add Provider' }));

    // Fill the form
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Test Provider' },
    });
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'https://api.test.com/' },
    });
    fireEvent.change(screen.getByLabelText('API Key'), {
      target: { value: 'sk-test' },
    });
    fireEvent.change(screen.getByLabelText('Opus Model'), {
      target: { value: 'claude-opus-test' },
    });

    // Save
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    // Should now show the provider in the list
    await waitFor(() => {
      expect(screen.getByText('Test Provider')).toBeInTheDocument();
    });
    expect(screen.getByText('anthropic')).toBeInTheDocument();

    // Verify persistence
    const storedSettings = JSON.parse(
      window.localStorage.getItem(settingsStorageKey) ?? '{}'
    ) as ReturnType<typeof createDefaultWebUiSettings>;
    expect(storedSettings.llmProviders).toHaveLength(1);
    expect(storedSettings.llmProviders[0].name).toBe('Test Provider');
    expect(storedSettings.llmProviders[0].baseUrl).toBe('https://api.test.com/');
  });
```

- [ ] **Step 2: Run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && npm run test:run
```

Expected: all tests pass (137+ tests).

- [ ] **Step 3: Commit**

```bash
git add frontend/__tests__/pages/SettingsPage.test.tsx
git commit -m "test: add LLM Provider tab rendering and CRUD test

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

### 1. Spec coverage

| Spec requirement | Task |
|------------------|------|
| `LlmProvider` data model | Task 1 |
| `WebUiSettingsDocument` extension | Task 1 |
| Backward compat (missing `llmProviders`) | Task 1 |
| Provider CRUD in context | Task 2 |
| i18n translations | Task 3 |
| Provider edit dialog with adaptive fields | Task 4 |
| Provider list tab | Task 5 |
| SettingsPage tab integration | Task 6 |
| Profile editor provider selector + auto-fill | Task 7 |
| Tests | Task 8 |

All requirements covered.

### 2. Placeholder scan

No TBD/TODO/"implement later"/"add appropriate error handling" found.

### 3. Type consistency

- `LlmProvider` interface name consistent across tasks
- `llmProviders` field name consistent across tasks
- `saveLlmProvider` / `updateLlmProvider` / `deleteLlmProvider` method names consistent
- i18n keys match the `pages.settings.llmProviders` prefix consistently

All consistent.

### 4. Scope check

This plan is focused on a single feature: global LLM provider config + profile auto-fill. No scope creep. Backend is intentionally excluded per spec.
