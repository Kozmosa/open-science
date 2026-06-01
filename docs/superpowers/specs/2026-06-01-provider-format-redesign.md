# Provider Format Redesign Design Spec

## 目标

统一并扩展 LLM Provider 的格式定义，让三种执行引擎（claude-code、agent-sdk、codex-app-server）都能通过前端配置的 Provider 切换 API 端点，同时保持向后兼容。

## Provider 格式扩展

将 `LlmProviderFormat` 从 `'openai' | 'anthropic'` 扩展为：

```
'type LlmProviderFormat = 'anthropic' | 'openai-chat' | 'openai-responses';
```

| 格式 | 说明 | 适用引擎 |
|------|------|----------|
| `anthropic` | Anthropic Messages API 兼容格式 | claude-code, agent-sdk |
| `openai-chat` | OpenAI Chat Completions API 格式 | —（预留） |
| `openai-responses` | OpenAI Responses API 格式（Codex 使用） | codex-app-server |

### Provider 模型字段

```typescript
interface LlmProvider {
  id: string;
  name: string;
  format: LlmProviderFormat;
  baseUrl: string;
  apiKey: string;
  // anthropic 格式专用
  opusModel?: string;
  sonnetModel?: string;
  haikuModel?: string;
  // openai-chat / openai-responses 格式专用
  defaultModel?: string;
}
```

## 引擎与 Provider 的映射

| 引擎 | 接受格式 | 注入的环境变量 / 配置文件 |
|------|----------|--------------------------|
| `claude-code` | `anthropic` | `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_DEFAULT_*_MODEL` |
| `agent-sdk` | `anthropic` | `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_DEFAULT_*_MODEL` |
| `codex-app-server` | `openai-responses` | `OPENAI_BASE_URL`, `OPENAI_API_KEY` |

## Research Agent Profile 字段保留策略

保留现有字段不变：
- `apiBaseUrl` / `apiKey` / `defaultOpusModel` / `defaultSonnetModel` / `defaultHaikuModel` — 用于 anthropic 格式
- `codexBaseUrl` / `codexApiKey` / `codexModel` — 用于 openai-responses 格式
- `envOverrides` — 兜底覆盖

**填充规则**：从 Provider 下拉框选择时，根据 provider 的 `format` 决定填充哪组字段：
- `format === 'anthropic'` → 填充 `apiBaseUrl`, `apiKey`, `defaultOpusModel`, `defaultSonnetModel`, `defaultHaikuModel`
- `format === 'openai-responses'` → 填充 `codexBaseUrl`, `codexApiKey`, `codexModel`
- `format === 'openai-chat'` → 预留，暂不填充任何字段

## 默认配置行为

### 前端
- 当 profile 的 `apiBaseUrl` / `codexBaseUrl` 为空时，显示 "使用服务器默认配置"
- Provider 下拉框始终可用，选择后填充对应字段
- 清除 provider 选择后，对应字段清空，回到 "使用服务器默认配置" 状态

### 后端
- 引擎启动时，如果 `api_base_url` / `codex_base_url` 为 `None` 或空字符串，**不注入任何环境变量**
- 不注入环境变量时，CLI 使用自己的默认配置（`~/.claude/config.json`、`~/.codex/config.toml` 或系统环境变量）

## 后端引擎改动

### claude-code 引擎
在 `claude_code.py` 的 `start()` 方法中，读取 `context.agent_profile.api_base_url` / `api_key` / `default_*_model`，注入子进程环境变量：
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_DEFAULT_OPUS_MODEL`
- `ANTHROPIC_DEFAULT_SONNET_MODEL`
- `ANTHROPIC_DEFAULT_HAIKU_MODEL`

### codex-app-server 引擎
在 `codex_app_server.py` 的 `_ensure_connection()` 中，读取 `context.agent_profile.codex_base_url` / `codex_api_key`，注入子进程环境变量：
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`

### agent-sdk 引擎
已有 `_provider_env()` 方法，无需改动。

## 前端 UI 改动

### SettingsPage — Research Agent Profile 编辑

#### agent-sdk / claude-code 引擎区域（已有）
- 保留现有的 "从 Provider 填充" 下拉框
- 下拉框只显示 `format === 'anthropic'` 的 provider
- 选择后填充 `apiBaseUrl`, `apiKey`, `defaultOpusModel`, `defaultSonnetModel`, `defaultHaikuModel`

#### codex-app-server 引擎区域（新增）
- 在 codex 配置区域上方添加 "从 Provider 填充" 下拉框
- 下拉框只显示 `format === 'openai-responses'` 的 provider
- 选择后填充 `codexBaseUrl`, `codexApiKey`, `codexModel`
- 添加 `codexBaseUrl` 和 `codexApiKey` 输入框（目前 UI 上缺失）

### LlmProviderEditDialog
- `format` 下拉框增加 `openai-responses` 选项
- 选择 `openai-responses` 时显示 `defaultModel` 输入框（而非 anthropic 的三个模型字段）

### i18n
新增/更新翻译键：
- `pages.settings.llmProviders.formatOpenAIResponses`: "OpenAI Responses"
- `pages.settings.llmProviders.formatOpenAIResponses`: "OpenAI Responses"
- `pages.settings.codex.baseUrl`: "Base URL"
- `pages.settings.codex.apiKey`: "API Key"

## 数据迁移

现有 `format === 'openai'` 的 provider 在读取时自动迁移为 `openai-chat`（因为旧的 `openai` 格式没有明确语义）。

在 `normalizeLlmProviders()` 中添加迁移逻辑：
```typescript
if (item.format === 'openai') {
  // 旧数据迁移：openai → openai-chat
  item.format = 'openai-chat';
}
```

## 文件改动清单

| 文件 | 改动 |
|------|------|
| `frontend/src/settings/types.ts` | 扩展 `LlmProviderFormat` |
| `frontend/src/settings/storage.ts` | `normalizeLlmProviders()` 添加 openai → openai-chat 迁移 |
| `frontend/src/pages/settings/LlmProviderEditDialog.tsx` | 支持 `openai-responses` 格式，条件显示模型字段 |
| `frontend/src/pages/SettingsPage.tsx` | codex 区域添加 provider 填充下拉框和 baseUrl/apiKey 输入框；agent-sdk 区域过滤 anthropic provider |
| `frontend/src/i18n/messages.ts` | 新增翻译键 |
| `src/ainrf/task_harness/engines/claude_code.py` | 注入 ANTHROPIC_* 环境变量 |
| `src/ainrf/task_harness/engines/codex_app_server.py` | 注入 OPENAI_* 环境变量 |
