# 全局 LLM Provider 配置管理设计

## 目标

在 WebUI 设置中新增独立的 LLM Provider 管理模块，将分散在 agent profile 中的 API endpoint、key、模型名等配置抽取为全局可复用的 Provider 条目。agent profile 通过「选择 Provider」实现一键回填，达到配置与使用场景的轻度解耦。

## 架构

纯前端实现，零后端改动。Provider 数据存储在 `WebUiSettingsDocument` 的新增字段中，与现有 `taskConfiguration.researchAgentProfiles` 并列。Provider 选择器作为 profile 编辑表单的快捷填充工具，回填后 profile 独立保存实际数据，运行时完全不依赖 provider 引用。

## Tech Stack

- React + TypeScript（前端）
- Tailwind CSS（样式）
- localStorage（持久化）

---

## 数据模型

### `LlmProviderFormat`

```typescript
type LlmProviderFormat = 'openai' | 'anthropic';
```

### `LlmProvider`

```typescript
interface LlmProvider {
  id: string;           // 唯一标识，uuid 或 url-safe 随机字符串
  name: string;         // 显示名称，如 "Kimi Coding"、"OpenAI Official"
  format: LlmProviderFormat;
  baseUrl: string;      // API base URL，如 "https://api.kimi.com/coding/"
  apiKey: string;       // API key

  // Anthropic 格式：三档模型
  opusModel?: string;
  sonnetModel?: string;
  haikuModel?: string;

  // OpenAI 格式：单一默认模型
  defaultModel?: string;
}
```

### `WebUiSettingsDocument` 扩展

在现有 `WebUiSettingsDocument` 中新增字段：

```typescript
interface WebUiSettingsDocument {
  version: 3;
  general: { /* ... */ };
  taskConfiguration: { /* ... */ };
  projectDefaults: { /* ... */ };
  llmProviders: LlmProvider[];  // 新增
}
```

向后兼容：读取旧版本 settings 时，`llmProviders` 缺失则默认为空数组 `[]`。

---

## UI 设计

### 1. SettingsPage 新增「LLM Providers」Tab

在现有 tabs 数组中新增一项：

```typescript
const tabs = [
  { key: 'general', label: 'General' },
  { key: 'llmProviders', label: 'LLM Providers' },  // 新增
  // admin tabs...
];
```

#### LLMProvidersTab 布局

- **Provider 列表**：卡片/表格形式展示所有 provider，每行显示 name、format badge、baseUrl（脱敏）、操作按钮（编辑/删除）
- **新增按钮**：「Add Provider」打开创建表单
- **空状态**：无 provider 时显示提示文本 + 新增按钮

#### Provider 编辑表单（Dialog 或 inline）

字段从上到下：

1. **Name** — 文本输入
2. **Format** — Select 下拉：`anthropic` / `openai`
3. **Base URL** — 文本输入（placeholder 根据 format 提示典型值）
4. **API Key** — password 类型输入，支持显示/隐藏切换
5. **模型字段（条件渲染）**
   - `format === 'anthropic'` 时显示三行：Opus Model / Sonnet Model / Haiku Model
   - `format === 'openai'` 时显示一行：Default Model

表单验证：name、format、baseUrl 为必填；apiKey 允许为空（某些本地部署无需 key）。

### 2. TaskConfiguration Profile 编辑区新增 Provider 选择器

在现有 profile 编辑表单中，**API Configuration** 区块的顶部新增一行：

```
Fill from Provider: [请选择 Provider ▼]  [Fill]
```

- 下拉框选项：所有已创建 provider 的 `name` + 「Custom（不填充）」
- 选择 provider 后**立即自动填充**（无需额外点击），填充前不二次确认
- 填充行为：把 provider 的 `baseUrl` → `apiBaseUrl`，`apiKey` → `apiKey`，模型字段按 format 映射到 profile 的 `defaultOpusModel`/`defaultSonnetModel`/`defaultHaikuModel`
- 填充后用户仍可手动修改任何字段

> **模型映射规则**：
> - OpenAI provider → Anthropic profile：`defaultModel` 同时填入 `defaultOpusModel`、`defaultSonnetModel`、`defaultHaikuModel`
> - Anthropic provider → OpenAI profile：优先取 `sonnetModel`，不存在时依次 fallback 到 `opusModel`、`haikuModel`，填入 profile 的对应字段（如果 profile 表单是 OpenAI 格式则只填一个）
> - 同 format 之间：字段一一对应

---

## 数据流

### Provider CRUD

- **Create**：用户点击「Add Provider」→ 填写表单 → 调用 `settingsContext.saveLlmProvider(provider)` → 追加到 `llmProviders` 数组 → 持久化到 localStorage
- **Update**：用户点击「Edit」→ 修改表单 → 调用 `settingsContext.updateLlmProvider(provider)` → 按 `id` 替换数组中的条目
- **Delete**：用户点击「Delete」→ 确认后调用 `settingsContext.deleteLlmProvider(id)` → 从数组中移除
- **Read**：`LLMProvidersTab` 通过 `useSettings()` 读取 `settings.llmProviders` 渲染列表

### 回填到 Profile

- 用户在 TaskConfiguration 的 profile 编辑区选择 provider
- 调用 `settingsContext.fillProfileFromProvider(profileId, providerId)`
- 内部逻辑：查找 provider → 按 format 映射字段 → 更新对应 profile → 持久化
- 不回填 `envOverrides`、`settingsJson` 等其他字段

---

## 错误处理

- **Provider ID 冲突**：创建/更新时检查 `id` 唯一性，冲突时 toast 错误
- **删除被引用 provider**：允许删除，因为 profile 是独立存储的，删除 provider 不影响已有 profile 的数据
- **格式不匹配回填**：OpenAI → Anthropic 或反向回填时，模型字段做合理兜底映射（如统一填到 sonnet，或全部填同一值）

---

## 测试要点

1. 旧版本 settings（无 `llmProviders` 字段）加载后默认空数组
2. Provider CRUD 后 localStorage 正确持久化
3. 选择 provider 回填后 profile 字段正确更新
4. Format 切换时表单字段正确显示/隐藏
5. 表单验证阻止无效提交

---

## 范围边界

- **不做**：后端 API 改动、server 端 provider 持久化、多用户共享 provider、provider 加密存储
- **不做**：自动检测 provider 可用性、模型列表自动拉取
- **不做**：把 profile 改为引用式（本次保持回填后独立存储）
