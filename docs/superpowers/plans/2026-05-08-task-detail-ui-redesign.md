# TaskDetail UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Prompt layers section from main panel to right aside panel and redesign MessageBlocks styling to use CSS variables matching the light/dark theme.

**Architecture:** Three focused frontend changes in sequence: i18n key addition first, then MessageBlocks color redesign, finally TaskDetail layout migration. Each task is self-contained and verifiable via TypeScript compilation.

**Tech Stack:** React 19 + TypeScript, Tailwind CSS v4, CSS variables (defined in `frontend/src/index.css`)

---

### Task 1: Add `prompt` i18n key

**Files:**
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Add EN key after `promptLayers`**

In `frontend/src/i18n/messages.ts`, find `promptLayers: 'Prompt layers'` (around line 216) and add `prompt: 'Prompt'` on the next line:

```ts
        promptLayers: 'Prompt layers',
        prompt: 'Prompt',
        chars: 'chars',
```

- [ ] **Step 2: Add ZH key after `promptLayers`**

Find the Chinese `promptLayers` entry (around line 853) and add `prompt: 'Prompt'` on the next line:

```ts
        promptLayers: 'Prompt 分层',
        prompt: 'Prompt',
        chars: '字符',
```

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/messages.ts
git commit -m "feat(i18n): add prompt section title key"
```

---

### Task 2: Redesign MessageBlocks with CSS variables

**Files:**
- Modify: `frontend/src/pages/tasks/MessageBlocks.tsx`

- [ ] **Step 1: Rewrite `SystemEventBlock`**

Replace the existing `SystemEventBlock` component (lines 9-17):

```tsx
export function SystemEventBlock({ message }: { message: MessageItem }) {
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-center">
      <div className="flex items-center gap-2 rounded-lg border-l-2 border-[var(--apple-blue)] bg-[var(--bg-secondary)] px-3 py-1.5">
        <span className="text-xs text-[var(--text-secondary)]">{content}</span>
        <span className="text-xs text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `UserMessage`**

Replace lines 19-28:

```tsx
export function UserMessage({ message }: { message: MessageItem }) {
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-tr-sm border border-[var(--apple-blue)]/20 bg-[var(--apple-blue)]/10 px-4 py-2">
        <pre className="whitespace-pre-wrap break-words font-sans text-sm text-[var(--apple-blue)]">{content}</pre>
        <div className="mt-1 text-right text-[10px] text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp)}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite `AssistantMessage`**

Replace lines 30-39:

```tsx
export function AssistantMessage({ message }: { message: MessageItem }) {
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-[var(--bg-secondary)] px-4 py-2">
        <pre className="whitespace-pre-wrap break-words font-sans text-sm text-[var(--text)]">{content}</pre>
        <div className="mt-1 text-right text-[10px] text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp)}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Rewrite `ThinkingBlock`**

Replace lines 41-59:

```tsx
export function ThinkingBlock({ message }: { message: MessageItem }) {
  const [isOpen, setIsOpen] = useState(false);
  const content = typeof message.content === 'string' ? message.content : '';
  return (
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
  );
}
```

- [ ] **Step 5: Rewrite `ToolCallBlock`**

Replace lines 61-80:

```tsx
export function ToolCallBlock({ message }: { message: MessageItem }) {
  const [isOpen, setIsOpen] = useState(false);
  const content = typeof message.content === 'object' ? message.content : {};
  const name = String((content as Record<string, unknown>).name || 'unknown');
  return (
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
  );
}
```

- [ ] **Step 6: Rewrite `ToolResultBlock`**

Replace lines 82-100:

```tsx
export function ToolResultBlock({ message }: { message: MessageItem }) {
  const [isOpen, setIsOpen] = useState(false);
  const content = typeof message.content === 'object' ? message.content : {};
  return (
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
  );
}
```

- [ ] **Step 7: Verify TypeScript compiles**

Run:
```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/tasks/MessageBlocks.tsx
git commit -m "feat(ui): redesign MessageBlocks with CSS variables and left border accents"
```

---

### Task 3: Migrate Prompt section and fix main panel background

**Files:**
- Modify: `frontend/src/pages/tasks/TaskDetail.tsx`

- [ ] **Step 1: Remove Prompt layers from main panel**

In `frontend/src/pages/tasks/TaskDetail.tsx`, find and delete the entire Prompt layers section inside `<main>` (lines 159-188, from `<section className="border-t border-[var(--border)] p-5">` to its closing `</section>`).

The `<main>` should now end immediately after the `TaskInputBar` conditional block (closing `)}` then `</main>`).

- [ ] **Step 2: Fix main panel background**

Change line 144 from:
```tsx
<main className="min-h-0 flex flex-col bg-[#0b1020]">
```
to:
```tsx
<main className="min-h-0 flex flex-col bg-[var(--surface)]">
```

- [ ] **Step 3: Add Prompt section to aside panel**

Inside `<aside>` (after the Result section, before the closing `</div>` of the `space-y-5` container at line 270), add:

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

- [ ] **Step 4: Verify TypeScript compiles**

Run:
```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/tasks/TaskDetail.tsx
git commit -m "feat(ui): move Prompt section to aside panel and fix main panel background"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run full frontend type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 2: Verify no hardcoded theme colors remain**

Search for leftover hardcoded colors in modified files:

```bash
grep -n 'gray-\|blue-\|white/\|#0b1020' frontend/src/pages/tasks/MessageBlocks.tsx frontend/src/pages/tasks/TaskDetail.tsx || echo "No hardcoded theme colors found"
```

Expected: Output should be "No hardcoded theme colors found" (the `#22c55e` green in ToolResultBlock is intentional and does not match the search pattern).

- [ ] **Step 3: Commit final verification (optional, or mark as done)**

If all checks pass, the implementation is complete. No additional commit needed if the three prior commits are clean.

---

## Self-Review

**1. Spec coverage:**
- Prompt migration to aside panel → Task 3
- MessageBlocks CSS variable redesign → Task 2
- Main panel background fix → Task 3 Step 2
- i18n key addition → Task 1
- Left border accents on message blocks → Task 2 Steps 4-6
- `break-words` overflow fix → Task 2 (all `pre` tags include it)
- Timestamp on all messages → Task 2 Steps 1-3

**2. Placeholder scan:** No TBD, TODO, or vague instructions found.

**3. Type consistency:** No new types introduced. `MessageItem` and `TaskRecord` types unchanged.
