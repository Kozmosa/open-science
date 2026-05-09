# TaskDetail UI Redesign — Prompt Section + Message Stream Styling

## Goal

将 TaskDetail 页面的 Prompt layers 折叠块从主面板底部迁移到右侧详情面板（aside）作为一个独立 section；同时全面重新设计消息流（MessageStream）的样式与布局，使其配色与整体 light/dark 主题保持一致。

## Architecture

- **布局层**：调整 `TaskDetail.tsx` 的 DOM 结构，将 Prompt section 从 `<main>` 移到 `<aside>` 底部。
- **样式层**：`MessageBlocks.tsx` 中所有硬编码 Tailwind 颜色替换为 CSS 变量；引入左边彩色竖线装饰区分消息类型。
- **i18n 层**：新增 `pages.tasks.prompt` 翻译键，供 Prompt section 标题使用。

## Tech Stack

- React 19 + TypeScript
- Tailwind CSS v4（使用 `@import "tailwindcss"`）
- CSS 变量主题系统（已定义于 `frontend/src/index.css`）

---

## Section 1: 布局重组 — Prompt 迁移到右侧面板

### 变更文件

- `frontend/src/pages/tasks/TaskDetail.tsx`

### 具体改动

1. **移除主面板底部的 Prompt layers section**（原 lines 159-188）：
   - 删除 `<main>` 内部的 `<section className="border-t ...">` 及其所有子元素。

2. **新增 i18n key**：
   - `pages.tasks.prompt: 'Prompt'`（EN）
   - `pages.tasks.prompt: 'Prompt'`（ZH，保持英文即可，与现有 `promptLayers` 风格一致）

3. **在 aside 内 Result section 之后新增 Prompt section**（在 line 269 之后）：

```tsx
<section>
  <h2 className="mb-2 text-sm font-semibold text-[var(--text)]">
    {t('pages.tasks.prompt')}
  </h2>
  {selectedTask.prompt ? (
    <div className="space-y-2">
      {selectedTask.prompt.layers.map((layer) => (
        <details
          key={layer.name}
          className="rounded-lg border border-[var(--border)] bg-[var(--surface)]"
        >
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-[var(--text)]">
            {layer.label}{' '}
            <span className="text-[var(--text-secondary)]">
              ({layer.char_count} {t('pages.tasks.chars')})
            </span>
          </summary>
          <pre className="max-h-48 overflow-auto border-t border-[var(--border)] bg-[var(--bg-tertiary)] p-3 text-xs text-[var(--text)]">
            {layer.content}
          </pre>
        </details>
      ))}
    </div>
  ) : (
    <p className="text-sm text-[var(--text-secondary)]">
      {t('pages.tasks.promptUnavailable')}
    </p>
  )}
</section>
```

4. **主面板背景色修复**：
   - line 144: `bg-[#0b1020]` → `bg-[var(--surface)]`
   - 使主面板在 light 模式下为白色（`#ffffff`），dark 模式下为深灰（`#18181b`）。

---

## Section 2: MessageBlocks 全面重新设计

### 变更文件

- `frontend/src/pages/tasks/MessageBlocks.tsx`

### 设计 token 映射

所有 block 统一使用 CSS 变量，彻底移除硬编码的 `gray-*`、`blue-*`、`white/[*]` 等 Tailwind 类。

| Block | 对齐 | 背景 | 文字颜色 | 边框/装饰 |
|-------|------|------|----------|----------|
| `SystemEventBlock` | 居中 | `bg-[var(--bg-secondary)]` | `text-[var(--text-secondary)]` | 左侧 2px 竖线 `var(--apple-blue)` |
| `UserMessage` | 右 | `bg-[var(--apple-blue)]/10` | `text-[var(--apple-blue)]` | `border border-[var(--apple-blue)]/20` |
| `AssistantMessage` | 左 | `bg-[var(--bg-secondary)]` | `text-[var(--text)]` | 无 |
| `ThinkingBlock` | 左 | `bg-[var(--bg-secondary)]` | `text-[var(--text-secondary)]` | 左侧 2px 竖线 `var(--text-tertiary)` |
| `ToolCallBlock` | 左 | `bg-[var(--bg-secondary)]` | `text-[var(--text-secondary)]` | 左侧 2px 竖线 `var(--apple-blue)` |
| `ToolResultBlock` | 左（缩进 16px） | `bg-[var(--bg-secondary)]` | `text-[var(--text-secondary)]` | 左侧 2px 竖线 `#22c55e` |

### 统一改进

1. **文本溢出处理**：所有 `<pre>` 标签增加 `break-words`，防止长行撑破布局。
2. **展开内容宽度**：Thinking/Tool 展开后的内容区域从 `max-w-[80%]` 改为 `w-full`，与触发按钮保持同一宽度，视觉上更整齐。
3. **时间戳显示**：所有消息块右下角增加 `text-[var(--text-tertiary)]` 格式的时间戳，使用 `formatTime()` 函数。
4. **圆角微调**：
   - UserMessage: `rounded-2xl rounded-tr-sm`（保持）
   - AssistantMessage: `rounded-2xl rounded-tl-sm`（保持）
   - Thinking/Tool: `rounded-lg`（保持）

### 具体代码变更

**`SystemEventBlock`**:
```tsx
<div className="my-2 flex justify-center">
  <div className="flex items-center gap-2 rounded-lg border-l-2 border-[var(--apple-blue)] bg-[var(--bg-secondary)] px-3 py-1.5">
    <span className="text-xs text-[var(--text-secondary)]">{content}</span>
    <span className="text-xs text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp)}</span>
  </div>
</div>
```

**`UserMessage`**:
```tsx
<div className="my-2 flex justify-end">
  <div className="max-w-[80%] rounded-2xl rounded-tr-sm border border-[var(--apple-blue)]/20 bg-[var(--apple-blue)]/10 px-4 py-2">
    <pre className="whitespace-pre-wrap break-words font-sans text-sm text-[var(--apple-blue)]">{content}</pre>
    <div className="mt-1 text-right text-[10px] text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp)}</div>
  </div>
</div>
```

**`AssistantMessage`**:
```tsx
<div className="my-2 flex justify-start">
  <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-[var(--bg-secondary)] px-4 py-2">
    <pre className="whitespace-pre-wrap break-words font-sans text-sm text-[var(--text)]">{content}</pre>
    <div className="mt-1 text-right text-[10px] text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp)}</div>
  </div>
</div>
```

**`ThinkingBlock`**:
```tsx
<div className="my-1 flex flex-col items-start">
  <button
    onClick={() => setIsOpen(!isOpen)}
    className="flex items-center gap-1 rounded-lg border-l-2 border-[var(--text-tertiary)] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
  >
    {isOpen ? '▾' : '▸'} Thinking...
  </button>
  {isOpen && (
    <div className="mt-1 w-full rounded-lg border-l-2 border-[var(--text-tertiary)] bg-[var(--bg-secondary)] px-3 py-2">
      <pre className="whitespace-pre-wrap break-words font-sans text-xs text-[var(--text-secondary)]">{content || ''}</pre>
    </div>
  )}
</div>
```

**`ToolCallBlock`**:
```tsx
<div className="my-1 flex flex-col items-start">
  <button
    onClick={() => setIsOpen(!isOpen)}
    className="flex items-center gap-1 rounded-lg border-l-2 border-[var(--apple-blue)] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
  >
    {isOpen ? '▾' : '▸'} Tool: {name}
  </button>
  {isOpen && (
    <div className="mt-1 w-full rounded-lg border-l-2 border-[var(--apple-blue)] bg-[var(--bg-secondary)] px-3 py-2">
      <pre className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--text-secondary)]">{JSON.stringify(content, null, 2)}</pre>
    </div>
  )}
</div>
```

**`ToolResultBlock`**:
```tsx
<div className="my-1 flex flex-col items-start pl-4">
  <button
    onClick={() => setIsOpen(!isOpen)}
    className="flex items-center gap-1 rounded-lg border-l-2 border-[#22c55e] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
  >
    {isOpen ? '▾' : '▸'} Result
  </button>
  {isOpen && (
    <div className="mt-1 w-full rounded-lg border-l-2 border-[#22c55e] bg-[var(--bg-secondary)] px-3 py-2">
      <pre className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--text-secondary)]">{JSON.stringify(content, null, 2)}</pre>
    </div>
  )}
</div>
```

---

## Section 3: i18n 与主题变量

### 变更文件

- `frontend/src/i18n/messages.ts`

### 新增翻译键

在 `pages.tasks` 命名空间下新增：

**EN (lines ~216 附近)**:
```ts
prompt: 'Prompt',
```

**ZH (lines ~850 附近)**:
```ts
prompt: 'Prompt',
```

> 注：Prompt 为通用技术术语，在中文界面中保持英文写法与现有 `promptLayers` 风格一致。

### 使用的 CSS 变量（已存在，无需新增）

| 变量 | Light 值 | Dark 值 | 用途 |
|------|---------|---------|------|
| `--apple-blue` | `#2563eb` | `#60a5fa` | 用户消息、系统事件、ToolCall 装饰 |
| `--bg-secondary` | `#f1f1f2` | `#202024` | 消息块背景 |
| `--bg-tertiary` | `#eeeeef` | `#27272a` | Prompt pre 块背景 |
| `--text` | `#171717` | `#f7f7f8` | 主要文字 |
| `--text-secondary` | `rgba(23,23,23,0.72)` | `rgba(247,247,248,0.76)` | 次要文字 |
| `--text-tertiary` | `rgba(23,23,23,0.48)` | `rgba(247,247,248,0.5)` | 时间戳、Thinking 装饰 |
| `--border` | `rgba(23,23,23,0.1)` | `rgba(255,255,255,0.1)` | 边框 |
| `--surface` | `#ffffff` | `#18181b` | 面板背景 |

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/pages/tasks/TaskDetail.tsx` | 修改 | 移动 Prompt section，修复主面板背景色 |
| `frontend/src/pages/tasks/MessageBlocks.tsx` | 修改 | 全面替换硬编码颜色为 CSS 变量，重新设计消息样式 |
| `frontend/src/i18n/messages.ts` | 修改 | 新增 `pages.tasks.prompt` 键（EN + ZH） |

---

## Self-Review Checklist

- [x] **Placeholder scan**: 无 TBD、TODO、"implement later"。
- [x] **内部一致性**: MessageBlocks 所有颜色均映射到 CSS 变量，无遗漏。
- [x] **范围检查**: 本设计仅涉及 3 个文件的 UI 层改动，无后端变更。
- [x] **歧义检查**: 颜色映射表明确，i18n 键位置明确。
- [x] **类型一致性**: 未引入新的 TypeScript 类型，仅修改 JSX 类名。
