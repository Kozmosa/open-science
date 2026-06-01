# Provider Format Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展 LLM Provider 格式为 `anthropic | openai-chat | openai-responses`，让三种执行引擎（claude-code、agent-sdk、codex-app-server）都能通过前端配置的 Provider 切换 API 端点，同时保持向后兼容。

**Architecture:** 前端扩展 Provider 格式和 UI 条件渲染，后端三个引擎分别注入对应环境变量（ANTHROPIC_* / OPENAI_*）。未指定 provider 时不注入环境变量，让 CLI 使用默认配置。

**Tech Stack:** TypeScript/React, Python, Bash

---

## File Structure

| 文件 | 职责 |
|------|------|
| `frontend/src/settings/types.ts` | 扩展 `LlmProviderFormat` 类型 |
| `frontend/src/settings/storage.ts` | `normalizeLlmProviders()` 添加 openai → openai-chat 迁移 |
| `frontend/src/pages/settings/LlmProviderEditDialog.tsx` | 支持 `openai-responses` 格式，条件显示模型字段 |
| `frontend/src/pages/SettingsPage.tsx` | codex 区域添加 provider 填充和 baseUrl/apiKey 输入框；agent-sdk 区域过滤 anthropic provider |
| `frontend/src/i18n/messages.ts` | 新增翻译键 |
| `src/ainrf/task_harness/engines/claude_code.py` | 注入 ANTHROPIC_* 环境变量 |
| `src/ainrf/task_harness/engines/codex_app_server.py` | 注入 OPENAI_* 环境变量 |
| `tests/test_llm_provider_migration.py` | 测试 provider 格式迁移逻辑 |

---

## Task 1: 扩展前端 Provider 类型和迁移逻辑

**Files:**
- Modify: `frontend/src/settings/types.ts`
- Modify: `frontend/src/settings/storage.ts`

- [ ] **Step 1: 扩展 `LlmProviderFormat` 类型**

在 `frontend/src/settings/types.ts` 中：

```typescript
export type LlmProviderFormat = 'anthropic' | 'openai-chat' | 'openai-responses';
```

- [ ] **Step 2: 更新 `normalizeLlmProviders()` 添加迁移和验证**

在 `frontend/src/settings/storage.ts` 中，修改 `normalizeLlmProviders`：

```typescript
export function normalizeLlmProviders(value: unknown): LlmProvider[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((item): item is LlmProvider => {
    if (!isRecord(item)) {
      return false;
    }
    const id = typeof item.id === 'string';
    const name = typeof item.name === 'string';
    // Migrate old 'openai' format to 'openai-chat'
    let format = item.format;
    if (format === 'openai') {
      format = 'openai-chat';
    }
    const formatValid = format === 'openai-chat' || format === 'openai-responses' || format === 'anthropic';
    const baseUrl = typeof item.baseUrl === 'string';
    const apiKey = typeof item.apiKey === 'string';
    return id && name && formatValid && baseUrl && apiKey;
  });
}
```

- [ ] **Step 3: 验证 TypeScript 编译**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/settings/types.ts frontend/src/settings/storage.ts
git commit -m "feat: extend LlmProviderFormat with openai-chat and openai-responses"
```

---

## Task 2: 更新 LlmProviderEditDialog 支持新格式

**Files:**
- Modify: `frontend/src/pages/settings/LlmProviderEditDialog.tsx`

- [ ] **Step 1: 更新 format 下拉框选项**

将 Select 中的 option 改为：

```tsx
<option value="anthropic">{t('pages.settings.llmProviders.formatAnthropic')}</option>
<option value="openai-chat">{t('pages.settings.llmProviders.formatOpenAIChat')}</option>
<option value="openai-responses">{t('pages.settings.llmProviders.formatOpenAIResponses')}</option>
```

- [ ] **Step 2: 条件渲染模型字段**

 anthropic 格式显示 opus/sonnet/haiku，openai-chat / openai-responses 显示 defaultModel：

```tsx
{format === 'anthropic' ? (
  <div className="grid gap-4 sm:grid-cols-3">
    <FormField label={t('pages.settings.llmProviders.opusModelLabel')}>
      <Input value={opusModel} onChange={(e) => setOpusModel(e.target.value)} placeholder="claude-opus-4-7" />
    </FormField>
    <FormField label={t('pages.settings.llmProviders.sonnetModelLabel')}>
      <Input value={sonnetModel} onChange={(e) => setSonnetModel(e.target.value)} placeholder="claude-sonnet-4-6" />
    </FormField>
    <FormField label={t('pages.settings.llmProviders.haikuModelLabel')}>
      <Input value={haikuModel} onChange={(e) => setHaikuModel(e.target.value)} placeholder="claude-haiku-4-5" />
    </FormField>
  </div>
) : (
  <FormField label={t('pages.settings.llmProviders.defaultModelLabel')}>
    <Input value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)} placeholder="gpt-5-codex" />
  </FormField>
)}
```

- [ ] **Step 3: 更新 handleSave 中的模型字段处理**

```typescript
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
```

- [ ] **Step 4: 验证 TypeScript 编译**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/settings/LlmProviderEditDialog.tsx
git commit -m "feat: LlmProviderEditDialog supports openai-responses and conditional model fields"
```

---

## Task 3: 更新 i18n 翻译

**Files:**
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: 在 en 和 zh 中添加新翻译键**

在 `en.pages.settings.llmProviders` 和 `zh.pages.settings.llmProviders` 中分别添加：

```typescript
formatOpenAIChat: 'OpenAI Chat',
formatOpenAIResponses: 'OpenAI Responses',
```

在 `en.pages.settings.codex` 和 `zh.pages.settings.codex` 中分别添加：

```typescript
baseUrl: 'Base URL',
apiKey: 'API Key',
```

- [ ] **Step 2: 验证 TypeScript 编译**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/messages.ts
git commit -m "feat: add i18n keys for openai-responses provider format and codex baseUrl/apiKey"
```

---

## Task 4: 更新 SettingsPage — agent-sdk 区域过滤 anthropic provider

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: 修改 agent-sdk 区域的 provider 下拉框**

找到 `taskConfiguration.defaultExecutionEngineId === 'agent-sdk'` 区域的 "从 Provider 填充" Select，将 options 过滤为只显示 `format === 'anthropic'` 的 provider：

```tsx
{settingsContext.settings.llmProviders
  .filter((p) => p.format === 'anthropic')
  .map((provider) => (
    <option key={provider.id} value={provider.id}>
      {provider.name}
    </option>
  ))}
```

- [ ] **Step 2: 验证 TypeScript 编译**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: filter agent-sdk provider dropdown to anthropic-only providers"
```

---

## Task 5: 更新 SettingsPage — codex 区域添加 provider 填充和输入框

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: 在 codex 区域添加 "从 Provider 填充" 下拉框**

在 `taskConfiguration.defaultExecutionEngineId === 'codex-app-server'` 区域的开头，添加 provider 填充下拉框：

```tsx
<div className="flex items-end gap-2">
  <div className="flex-1">
    <FormField label={t('pages.settings.llmProviders.fillFromProvider')}>
      <Select
        aria-label={t('pages.settings.llmProviders.fillFromProvider')}
        value=""
        onChange={(event) => {
          const providerId = event.target.value;
          if (!providerId) return;
          const provider = settingsContext.settings.llmProviders.find((p) => p.id === providerId);
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
        {settingsContext.settings.llmProviders
          .filter((p) => p.format === 'openai-responses')
          .map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.name}
            </option>
          ))}
      </Select>
    </FormField>
  </div>
</div>
```

- [ ] **Step 2: 在 codex 区域添加 codexBaseUrl 和 codexApiKey 输入框**

在 codex 区域的 grid 中（model/command/approval 之前或之后）添加：

```tsx
<div className="grid gap-4 sm:grid-cols-2">
  <FormField label={t('pages.settings.codex.baseUrl')}>
    <Input
      aria-label={t('pages.settings.codex.baseUrl')}
      value={profileDraft.codexBaseUrl}
      onChange={(event) =>
        setProfileDraft((current) => ({ ...current, codexBaseUrl: event.target.value }))
      }
      placeholder="https://api.openai.com/"
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
      placeholder="sk-..."
    />
  </FormField>
</div>
```

- [ ] **Step 3: 验证 TypeScript 编译**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: add provider fill and baseUrl/apiKey inputs for codex-app-server"
```

---

## Task 6: 后端 — claude-code 引擎注入 ANTHROPIC_* 环境变量

**Files:**
- Modify: `src/ainrf/task_harness/engines/claude_code.py`

- [ ] **Step 1: 在 `start()` 方法中注入环境变量**

在 `async def start(self, context: EngineContext, emit) -> None:` 方法开头，在 `command` 定义之后添加环境变量构建逻辑：

```python
import os

env = os.environ.copy()
profile = context.agent_profile
if profile.api_base_url:
    env["ANTHROPIC_BASE_URL"] = profile.api_base_url
if profile.api_key:
    env["ANTHROPIC_API_KEY"] = profile.api_key
    env["ANTHROPIC_AUTH_TOKEN"] = profile.api_key
if profile.default_opus_model:
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = profile.default_opus_model
if profile.default_sonnet_model:
    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = profile.default_sonnet_model
if profile.default_haiku_model:
    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = profile.default_haiku_model
if profile.env_overrides:
    for key, value in profile.env_overrides.items():
        env[key] = value
```

然后将 `asyncio.create_subprocess_exec` 调用添加 `env=env` 参数。

- [ ] **Step 2: 运行 Python 语法检查**

Run: `python -m py_compile src/ainrf/task_harness/engines/claude_code.py`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/task_harness/engines/claude_code.py
git commit -m "feat: claude-code engine injects ANTHROPIC_* env vars from profile"
```

---

## Task 7: 后端 — codex-app-server 引擎注入 OPENAI_* 环境变量

**Files:**
- Modify: `src/ainrf/task_harness/engines/codex_app_server.py`

- [ ] **Step 1: 在 `_ensure_connection()` 中注入环境变量**

找到 `_ensure_connection` 方法中 `env = None` 和 `if context.codex_home_path is not None:` 之间的区域，修改为：

```python
env = os.environ.copy()
profile = context.agent_profile
if profile.codex_base_url:
    env["OPENAI_BASE_URL"] = profile.codex_base_url
if profile.codex_api_key:
    env["OPENAI_API_KEY"] = profile.codex_api_key
if context.codex_home_path is not None:
    env["CODEX_HOME"] = context.codex_home_path
```

注意：需要在文件顶部确认 `import os` 已存在（当前已有 `import asyncio, contextlib, json, logging, shlex`），如果没有则添加。

- [ ] **Step 2: 运行 Python 语法检查**

Run: `python -m py_compile src/ainrf/task_harness/engines/codex_app_server.py`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/task_harness/engines/codex_app_server.py
git commit -m "feat: codex-app-server engine injects OPENAI_* env vars from profile"
```

---

## Task 8: 添加 provider 迁移测试

**Files:**
- Create: `tests/test_llm_provider_migration.py`

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

import pytest


def test_normalize_llm_providers_migrates_old_openai_format() -> None:
    """Old 'openai' format should be migrated to 'openai-chat'."""
    from ainrf.settings.storage import normalizeLlmProviders

    raw = [
        {
            "id": "p1",
            "name": "Old OpenAI",
            "format": "openai",
            "baseUrl": "https://api.openai.com/",
            "apiKey": "sk-old",
        }
    ]
    result = normalizeLlmProviders(raw)
    assert len(result) == 1
    assert result[0]["format"] == "openai-chat"


def test_normalize_llm_providers_accepts_new_formats() -> None:
    from ainrf.settings.storage import normalizeLlmProviders

    raw = [
        {
            "id": "p1",
            "name": "Anthropic",
            "format": "anthropic",
            "baseUrl": "https://api.anthropic.com/",
            "apiKey": "sk-ant",
        },
        {
            "id": "p2",
            "name": "OpenAI Chat",
            "format": "openai-chat",
            "baseUrl": "https://api.openai.com/",
            "apiKey": "sk-chat",
        },
        {
            "id": "p3",
            "name": "OpenAI Responses",
            "format": "openai-responses",
            "baseUrl": "https://api.openai.com/",
            "apiKey": "sk-resp",
        },
    ]
    result = normalizeLlmProviders(raw)
    assert len(result) == 3
    assert result[0]["format"] == "anthropic"
    assert result[1]["format"] == "openai-chat"
    assert result[2]["format"] == "openai-responses"


def test_normalize_llm_providers_rejects_invalid_format() -> None:
    from ainrf.settings.storage import normalizeLlmProviders

    raw = [
        {
            "id": "p1",
            "name": "Invalid",
            "format": "unknown",
            "baseUrl": "https://example.com/",
            "apiKey": "sk-invalid",
        }
    ]
    result = normalizeLlmProviders(raw)
    assert len(result) == 0
```

注意：这个测试文件路径是前端的 `frontend/src/settings/storage.ts`，但测试放在 Python 的 `tests/` 目录下。实际上 `normalizeLlmProviders` 是 TypeScript 函数，不能用 Python 测试。需要改为前端测试或手动验证。

改为：不创建这个测试文件，改为在 Task 9 中通过前端类型检查和功能测试验证。

- [ ] **Step 2: Commit（跳过，合并到 Task 9）**

---

## Task 9: 最终验证

**Files:**
- Modify: 如有需要

- [ ] **Step 1: 前端类型检查**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: 无错误

- [ ] **Step 2: 前端测试**

Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Expected: 所有测试通过

- [ ] **Step 3: Python lint**

Run: `uv run ruff check src/ainrf/task_harness/engines/claude_code.py src/ainrf/task_harness/engines/codex_app_server.py`
Expected: 无错误

- [ ] **Step 4: Python 类型检查**

Run: `uv run ty check`
Expected: 无错误（或只有已有错误）

- [ ] **Step 5: 运行全部测试**

Run: `uv run pytest tests/ -q`
Expected: 通过（允许已有失败的测试）

- [ ] **Step 6: 最终 review checklist**

- [ ] `LlmProviderFormat` 包含 `'anthropic' | 'openai-chat' | 'openai-responses'`
- [ ] `normalizeLlmProviders()` 将旧 `'openai'` 迁移为 `'openai-chat'`
- [ ] `LlmProviderEditDialog` 支持三种格式，条件显示模型字段
- [ ] i18n 包含 `formatOpenAIChat`、`formatOpenAIResponses`、`baseUrl`、`apiKey`
- [ ] agent-sdk 区域的 provider 下拉框只显示 `format === 'anthropic'`
- [ ] codex 区域有 provider 下拉框（只显示 `format === 'openai-responses'`）和 `codexBaseUrl`/`codexApiKey` 输入框
- [ ] claude-code 引擎注入 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`、模型环境变量
- [ ] codex-app-server 引擎注入 `OPENAI_BASE_URL`、`OPENAI_API_KEY`
- [ ] 未指定 provider 时（字段为空），引擎不注入环境变量

- [ ] **Step 7: Commit（如有修改）**

```bash
git add -A
git commit -m "chore: final polish on provider format redesign"
```

---

## Self-Review Checklist

### Spec Coverage
- [x] 扩展 `LlmProviderFormat` — Task 1
- [x] 旧 `'openai'` 迁移为 `'openai-chat'` — Task 1
- [x] `LlmProviderEditDialog` 支持三种格式 — Task 2
- [x] i18n 翻译 — Task 3
- [x] agent-sdk 区域过滤 anthropic provider — Task 4
- [x] codex 区域 provider 填充和 baseUrl/apiKey 输入框 — Task 5
- [x] claude-code 引擎注入 ANTHROPIC_* — Task 6
- [x] codex-app-server 引擎注入 OPENAI_* — Task 7
- [x] 未指定 provider 时不注入环境变量 — Task 6, 7（条件判断）

### Placeholder Scan
- [x] 无 "TBD"/"TODO"
- [x] 所有代码块包含完整代码
- [x] 所有命令包含预期输出

### Type Consistency
- [x] `LlmProviderFormat` 值在 types.ts、storage.ts、LlmProviderEditDialog.tsx 中一致
- [x] 环境变量名在 claude_code.py、agent_sdk.py 中一致
- [x] `codexBaseUrl`/`codexApiKey` 在 SettingsPage.tsx 和 codex_app_server.py 中一致
