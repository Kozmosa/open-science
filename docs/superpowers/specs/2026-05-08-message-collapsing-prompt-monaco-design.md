# Message Collapsing + Prompt Monaco Editor Design

## Goal

1. Collapse consecutive non-chat messages (system_event/thinking/tool_call/tool_result) into a foldable group in the message stream.
2. Replace plain-text `pre` blocks in the Prompt section with Monaco Editor (read-only, auto-wrap, theme-aware), lazy-loaded on expand.

## Architecture

- **Message layer**: New `useMessageGroups` hook scans the `messages` array and groups consecutive non-chat messages. `MessageStream` renders either `MessageBlock` (single) or `CollapsedGroupBlock` (group). Collapse state is maintained in a `Set<string>`.
- **Prompt layer**: New `PromptEditor` component wraps `@monaco-editor/react`. A `useMonacoTheme` hook listens to `prefers-color-scheme` to switch between `'vs'` and `'vs-dark'`. The editor is conditionally rendered only when its parent `details` element is open.

## Tech Stack

- React 19 + TypeScript
- Tailwind CSS v4
- `@monaco-editor/react` (already installed)
- CSS variables

---

## Section 1: System Message Collapsing

### 变更文件

- Create: `frontend/src/pages/tasks/useMessageGroups.ts`
- Create: `frontend/src/types/index.ts` — add `DisplayMessageItem` type
- Modify: `frontend/src/pages/tasks/MessageStream.tsx`
- Modify: `frontend/src/pages/tasks/MessageBlocks.tsx`

### 新增类型

In `frontend/src/types/index.ts`, after `MessageItem`:

```ts
export type DisplayMessageItem =
  | { kind: 'single'; message: MessageItem }
  | { kind: 'group'; id: string; messages: MessageItem[]; collapsed: boolean };
```

### useMessageGroups hook

Create `frontend/src/pages/tasks/useMessageGroups.ts`:

```ts
import { useMemo, useState, useCallback } from 'react';
import type { MessageItem, DisplayMessageItem } from '../../types';

const NON_CHAT_TYPES = new Set(['system_event', 'thinking', 'tool_call', 'tool_result']);

function isNonChat(msg: MessageItem): boolean {
  return NON_CHAT_TYPES.has(msg.type);
}

function groupMessages(messages: MessageItem[]): DisplayMessageItem[] {
  const result: DisplayMessageItem[] = [];
  let i = 0;

  while (i < messages.length) {
    if (!isNonChat(messages[i])) {
      result.push({ kind: 'single', message: messages[i] });
      i++;
      continue;
    }

    const groupStart = i;
    while (i < messages.length && isNonChat(messages[i])) i++;
    const groupMessages = messages.slice(groupStart, i);

    if (groupMessages.length >= 2) {
      result.push({
        kind: 'group',
        id: `group-${groupMessages[0].id}`,
        messages: groupMessages,
        collapsed: true,
      });
    } else {
      result.push({ kind: 'single', message: groupMessages[0] });
    }
  }

  return result;
}

export function useMessageGroups(messages: MessageItem[]) {
  const grouped = useMemo(() => groupMessages(messages), [messages]);

  const [collapsedState, setCollapsedState] = useState<Set<string>>(() => {
    return new Set(grouped.filter((g): g is Extract<typeof g, { kind: 'group' }> => g.kind === 'group').map(g => g.id));
  });

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsedState(prev => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }, []);

  const displayItems: DisplayMessageItem[] = useMemo(() => {
    return grouped.map(item => {
      if (item.kind === 'group') {
        return { ...item, collapsed: collapsedState.has(item.id) };
      }
      return item;
    });
  }, [grouped, collapsedState]);

  return { displayItems, toggleGroup };
}
```

### MessageStream 改造

Modify `frontend/src/pages/tasks/MessageStream.tsx`:

```tsx
import { useRef, useEffect, useCallback } from 'react';
import type { MessageItem } from '../../types';
import { MessageBlock, CollapsedGroupBlock } from './MessageBlocks';
import { useMessageGroups } from './useMessageGroups';

interface Props {
  messages: MessageItem[];
}

export default function MessageStream({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldScrollRef = useRef(true);
  const { displayItems, toggleGroup } = useMessageGroups(messages);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const threshold = 80;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldScrollRef.current = distanceFromBottom < threshold;
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  useEffect(() => {
    if (shouldScrollRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
        No messages yet
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex flex-col overflow-auto px-4 py-2">
      {displayItems.map((item) => {
        if (item.kind === 'group') {
          return (
            <CollapsedGroupBlock
              key={item.id}
              item={item}
              onToggle={() => toggleGroup(item.id)}
            />
          );
        }
        return <MessageBlock key={item.message.id} message={item.message} />;
      })}
      <div ref={bottomRef} />
    </div>
  );
}
```

### CollapsedGroupBlock 组件

Add to `frontend/src/pages/tasks/MessageBlocks.tsx`:

```tsx
interface CollapsedGroupItem {
  id: string;
  messages: MessageItem[];
  collapsed: boolean;
}

export function CollapsedGroupBlock({ item, onToggle }: { item: CollapsedGroupItem; onToggle: () => void }) {
  if (!item.collapsed) {
    return (
      <div className="space-y-1">
        {item.messages.map(msg => (
          <MessageBlock key={msg.id} message={msg} />
        ))}
      </div>
    );
  }

  const counts = item.messages.reduce((acc, msg) => {
    acc[msg.type] = (acc[msg.type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const summary = Object.entries(counts)
    .map(([type, count]) => `${count} ${type.replace('_', ' ')}`)
    .join(', ');

  return (
    <div className="my-2 flex justify-center">
      <button
        onClick={onToggle}
        className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
      >
        <span>▸ {summary}</span>
        <span className="text-[var(--text-tertiary)]">({item.messages.length})</span>
      </button>
    </div>
  );
}
```

---

## Section 2: Prompt Monaco Editor

### 变更文件

- Create: `frontend/src/hooks/useMonacoTheme.ts`
- Create: `frontend/src/pages/tasks/PromptEditor.tsx`
- Modify: `frontend/src/pages/tasks/TaskDetail.tsx`

### useMonacoTheme hook

Create `frontend/src/hooks/useMonacoTheme.ts`:

```ts
import { useState, useEffect } from 'react';

export function useMonacoTheme(): 'vs' | 'vs-dark' {
  const [isDark, setIsDark] = useState(() =>
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setIsDark(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  return isDark ? 'vs-dark' : 'vs';
}
```

### PromptEditor component

Create `frontend/src/pages/tasks/PromptEditor.tsx`:

```tsx
import Editor from '@monaco-editor/react';
import { useMonacoTheme } from '../../hooks/useMonacoTheme';

interface Props {
  content: string;
}

export default function PromptEditor({ content }: Props) {
  const theme = useMonacoTheme();

  return (
    <div className="border-t border-[var(--border)]">
      <Editor
        height="300px"
        language="plaintext"
        value={content}
        theme={theme}
        options={{
          readOnly: true,
          wordWrap: 'on',
          minimap: { enabled: false },
          lineNumbers: 'off',
          scrollBeyondLastLine: false,
          fontSize: 12,
          padding: { top: 12, bottom: 12 },
        }}
      />
    </div>
  );
}
```

### TaskDetail Prompt section 改造

In `frontend/src/pages/tasks/TaskDetail.tsx`, modify the Prompt layers `details` rendering (inside the `selectedTask.prompt.layers.map`):

Replace:
```tsx
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
```

With:
```tsx
<PromptLayerItem key={layer.name} layer={layer} />
```

And create a local sub-component (inside `TaskDetail.tsx` or as a separate file):

```tsx
import { useState } from 'react';
import PromptEditor from './PromptEditor';

function PromptLayerItem({ layer }: { layer: { name: string; label: string; char_count: number; content: string } }) {
  const t = useT();
  const [isOpen, setIsOpen] = useState(false);

  return (
    <details
      className="rounded-lg border border-[var(--border)] bg-[var(--surface)]"
      onToggle={(e) => setIsOpen(e.currentTarget.open)}
    >
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-[var(--text)]">
        {layer.label}{' '}
        <span className="text-[var(--text-secondary)]">
          ({layer.char_count} {t('pages.tasks.chars')})
        </span>
      </summary>
      {isOpen && <PromptEditor content={layer.content} />}
    </details>
  );
}
```

**Note**: The `details` element natively manages open/close state; `onToggle` is used only to trigger React re-render so `PromptEditor` mounts lazily.

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/types/index.ts` | 修改 | 新增 `DisplayMessageItem` 类型 |
| `frontend/src/pages/tasks/useMessageGroups.ts` | 创建 | 消息分组 hook |
| `frontend/src/pages/tasks/MessageStream.tsx` | 修改 | 使用 `useMessageGroups`，渲染 `CollapsedGroupBlock` |
| `frontend/src/pages/tasks/MessageBlocks.tsx` | 修改 | 新增 `CollapsedGroupBlock` 组件 |
| `frontend/src/hooks/useMonacoTheme.ts` | 创建 | Monaco 主题跟随 hook |
| `frontend/src/pages/tasks/PromptEditor.tsx` | 创建 | Monaco Editor 包装组件 |
| `frontend/src/pages/tasks/TaskDetail.tsx` | 修改 | Prompt `pre` → `PromptEditor` 懒加载 |

---

## Self-Review Checklist

- [x] **Placeholder scan**: 无 TBD、TODO。
- [x] **内部一致性**: `DisplayMessageItem` 类型在 hook 和 MessageStream 中一致使用；Monaco 主题 'vs'/'vs-dark' 映射明确。
- [x] **范围检查**: 7 个文件的前端改动，无后端变更。
- [x] **歧义检查**: 分组阈值（≥2 条）明确；懒加载条件（`details` open）明确。
- [x] **类型一致性**: `PromptLayerItem` 的 `layer` prop 类型与 `selectedTask.prompt.layers` 元素类型匹配。
