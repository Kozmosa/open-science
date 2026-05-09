# Message Collapsing + Prompt Monaco Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse consecutive non-chat messages into foldable groups and replace Prompt pre blocks with lazy-loaded Monaco Editor.

**Architecture:** Three independent frontend changes: (1) add `DisplayMessageItem` type and `useMessageGroups` hook, (2) wire group rendering into `MessageStream`/`MessageBlocks`, (3) add Monaco theme hook + `PromptEditor` and integrate into `TaskDetail`.

**Tech Stack:** React 19 + TypeScript, Tailwind CSS v4, `@monaco-editor/react`

---

### Task 1: Add DisplayMessageItem type and useMessageGroups hook

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/pages/tasks/useMessageGroups.ts`

- [ ] **Step 1: Add DisplayMessageItem type**

In `frontend/src/types/index.ts`, after `MessageItem` (around line 635), add:

```ts
export type DisplayMessageItem =
  | { kind: 'single'; message: MessageItem }
  | { kind: 'group'; id: string; messages: MessageItem[]; collapsed: boolean };
```

- [ ] **Step 2: Create useMessageGroups hook**

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

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd /home/xuyang/code/scholar-agent/.claude/worktrees/feat+agent-sdk-engine/frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/pages/tasks/useMessageGroups.ts
git commit -m "feat(ui): add DisplayMessageItem type and useMessageGroups hook"
```

---

### Task 2: Wire group rendering into MessageStream and MessageBlocks

**Files:**
- Modify: `frontend/src/pages/tasks/MessageStream.tsx`
- Modify: `frontend/src/pages/tasks/MessageBlocks.tsx`

- [ ] **Step 1: Update MessageStream to use useMessageGroups**

Replace `frontend/src/pages/tasks/MessageStream.tsx` with:

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

- [ ] **Step 2: Add CollapsedGroupBlock to MessageBlocks**

In `frontend/src/pages/tasks/MessageBlocks.tsx`, add the following before `MessageBlock` (after `ToolResultBlock`):

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

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /home/xuyang/code/scholar-agent/.claude/worktrees/feat+agent-sdk-engine/frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/tasks/MessageStream.tsx frontend/src/pages/tasks/MessageBlocks.tsx
git commit -m "feat(ui): collapse consecutive non-chat messages into foldable groups"
```

---

### Task 3: Monaco Editor for Prompt blocks

**Files:**
- Create: `frontend/src/hooks/useMonacoTheme.ts`
- Create: `frontend/src/pages/tasks/PromptEditor.tsx`
- Modify: `frontend/src/pages/tasks/TaskDetail.tsx`

- [ ] **Step 1: Create useMonacoTheme hook**

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

- [ ] **Step 2: Create PromptEditor component**

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

- [ ] **Step 3: Replace pre with PromptEditor in TaskDetail**

In `frontend/src/pages/tasks/TaskDetail.tsx`:

Add import at the top:
```tsx
import PromptEditor from './PromptEditor';
```

Find the Prompt layers map block (inside `selectedTask.prompt.layers.map`), and replace the entire `details` element:

From:
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

To:
```tsx
                    <PromptLayerItem key={layer.name} layer={layer} />
```

Then add the `PromptLayerItem` sub-component inside `TaskDetail.tsx` (before the main export or as a separate function in the same file):

```tsx
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

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /home/xuyang/code/scholar-agent/.claude/worktrees/feat+agent-sdk-engine/frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useMonacoTheme.ts frontend/src/pages/tasks/PromptEditor.tsx frontend/src/pages/tasks/TaskDetail.tsx
git commit -m "feat(ui): replace prompt pre blocks with lazy-loaded Monaco Editor"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run full frontend type check**

```bash
cd /home/xuyang/code/scholar-agent/.claude/worktrees/feat+agent-sdk-engine/frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 2: Verify file list**

```bash
git diff --stat HEAD~3..HEAD
```

Expected: Only the planned files changed.

---

## Self-Review

**1. Spec coverage:**
- DisplayMessageItem type → Task 1 Step 1
- useMessageGroups hook → Task 1 Step 2
- MessageStream integration → Task 2 Step 1
- CollapsedGroupBlock → Task 2 Step 2
- useMonacoTheme → Task 3 Step 1
- PromptEditor → Task 3 Step 2
- TaskDetail integration → Task 3 Step 3

**2. Placeholder scan:** No TBD, TODO, or vague instructions found.

**3. Type consistency:** `PromptLayerItem` layer prop matches `selectedTask.prompt.layers` element type. `DisplayMessageItem` used consistently across hook and MessageStream.
