# Appearance / Font Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Appearance card to SettingsPage that lets users switch the global font family between sans-serif and serif.

**Architecture:** Extend `WebUiSettingsDocument.general` with an `appearance` field holding `fontFamily: 'sans-serif' | 'serif'`. `SettingsProvider` drives the global CSS variables `--font-text` and `--font-display` via JS. The body rule `font-family: var(--font-text)` already exists in `index.css`, so all UI text switches automatically.

**Tech Stack:** React 19, Tailwind CSS v4, CSS Variables, localStorage

---

### File Mapping

| File | Responsibility |
|------|---------------|
| `frontend/src/settings/types.ts` | `AppearanceSettings` interface and updated `WebUiSettingsDocument` |
| `frontend/src/settings/defaults.ts` | Default `appearance` value in `createDefaultWebUiSettings()` |
| `frontend/src/settings/storage.ts` | Normalize missing `appearance` on load; no version bump needed |
| `frontend/src/settings/context.tsx` | Sanitize `appearance`, update CSS variables in `useEffect`, expose `saveAppearanceSettings` / `resetAppearanceSettings` |
| `frontend/src/pages/SettingsPage.tsx` | New `AppearanceSection` SectionCard with Select control |
| `frontend/src/i18n/messages.ts` | Translation keys for the new UI labels |

---

### Task 1: Type Definition

**Files:**
- Modify: `frontend/src/settings/types.ts`

- [ ] **Step 1: Add `AppearanceSettings` interface**

```ts
export interface AppearanceSettings {
  fontFamily: 'sans-serif' | 'serif';
}
```

- [ ] **Step 2: Extend `WebUiSettingsDocument.general`**

Add `appearance: AppearanceSettings` to the `general` object:

```ts
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
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/settings/types.ts
git commit -m "types: add AppearanceSettings to WebUiSettingsDocument"
```

---

### Task 2: Default Values

**Files:**
- Modify: `frontend/src/settings/defaults.ts`

- [ ] **Step 1: Update `createDefaultWebUiSettings`**

Add `appearance` to the returned `general` object:

```ts
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
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/settings/defaults.ts
git commit -m "defaults: add appearance default to createDefaultWebUiSettings"
```

---

### Task 3: Storage Normalization

**Files:**
- Modify: `frontend/src/settings/storage.ts`

- [ ] **Step 1: Normalize `appearance` in `readStoredSettings`**

Inside `readStoredSettings`, after reading `editorSettings`, read and normalize `appearanceSettings`:

```ts
const appearanceSettings = isRecord(general.appearance) ? general.appearance : null;
const fontFamily =
  appearanceSettings?.fontFamily === 'serif' ? 'serif' : 'sans-serif';

const missingAppearanceSettings = appearanceSettings === null;
```

Add `missingAppearanceSettings` to the recovery-reason chain at the end of the function.

- [ ] **Step 2: Include `appearance` in the returned settings object**

```ts
general: {
  defaultRoute,
  terminal: {
    fontSize: terminalFontSize,
  },
  editor: {
    fontSize: editorFontSize,
    fontFamily: editorFontFamily,
  },
  appearance: {
    fontFamily,
  },
},
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/settings/storage.ts
git commit -m "storage: normalize appearance.fontFamily on settings load"
```

---

### Task 4: Settings Context — Sanitize + CSS Variable Effect

**Files:**
- Modify: `frontend/src/settings/context.tsx`

- [ ] **Step 1: Sanitize `appearance` in `sanitizeSettings`**

Add after the `editor` sanitization block:

```ts
const appearanceFontFamily =
  settings.general.appearance?.fontFamily === 'serif' ? 'serif' : 'sans-serif';
```

Then include it in the returned `general`:

```ts
general: {
  defaultRoute: isDefaultRoute(settings.general.defaultRoute)
    ? settings.general.defaultRoute
    : 'terminal',
  terminal: {
    fontSize: clampTerminalFontSize(settings.general.terminal.fontSize),
  },
  editor: {
    fontSize: editorFontSize,
    fontFamily: editorFontFamily,
  },
  appearance: {
    fontFamily: appearanceFontFamily,
  },
},
```

- [ ] **Step 2: Add CSS-variable `useEffect` in `SettingsProvider`**

Add after the existing `useEffect` (the one that fetches codex defaults), before the `value` memo:

```ts
const sansStack =
  'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const serifStack =
  'Georgia, "Noto Serif", "Times New Roman", "Songti SC", "STSong", serif';

useEffect(() => {
  const fontStack =
    state.settings.general.appearance.fontFamily === 'serif'
      ? serifStack
      : sansStack;
  document.documentElement.style.setProperty('--font-text', fontStack);
  document.documentElement.style.setProperty('--font-display', fontStack);
}, [state.settings.general.appearance.fontFamily]);
```

- [ ] **Step 3: Expose `saveAppearanceSettings` and `resetAppearanceSettings`**

Add to the `SettingsContextValue` interface:

```ts
saveAppearanceSettings: (appearance: AppearanceSettings) => void;
resetAppearanceSettings: () => void;
```

Add to the `value` object inside `useMemo`:

```ts
saveAppearanceSettings: (appearance) => {
  commitSettings({
    ...state.settings,
    general: {
      ...state.settings.general,
      appearance,
    },
  });
},
resetAppearanceSettings: () => {
  const defaults = createDefaultWebUiSettings();
  commitSettings({
    ...state.settings,
    general: {
      ...state.settings.general,
      appearance: defaults.general.appearance,
    },
  });
},
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/settings/context.tsx
git commit -m "context: sanitize appearance, drive CSS variables, expose save/reset"
```

---

### Task 5: Settings Page UI — Appearance SectionCard

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Read `saveAppearanceSettings` and `resetAppearanceSettings` from `useSettings`**

Add them to the destructured list at the top of `SettingsPage`:

```ts
const {
  settings,
  recoveryReason,
  saveGeneralPreferences,
  resetGeneralPreferences,
  saveTaskConfigurationSettings,
  resetTaskConfigurationSettings,
  saveProjectDefaultEnvironment,
  saveProjectDefaultWorkspace,
  saveProjectEnvironmentDefaults,
  resetProjectEnvironmentDefaults,
  getProjectEnvironmentDefaults,
  saveAppearanceSettings,
  resetAppearanceSettings,
} = useSettings();
```

- [ ] **Step 2: Add `AppearanceSection` component above `SettingsPage`**

```tsx
interface AppearanceSectionProps {
  savedAppearance: WebUiSettingsDocument['general']['appearance'];
  onSave: (appearance: WebUiSettingsDocument['general']['appearance']) => void;
  onReset: () => void;
}

function AppearanceSection({ savedAppearance, onSave, onReset }: AppearanceSectionProps) {
  const t = useT();
  const [draft, setDraft] = useState(savedAppearance);
  const hasChanges = draft.fontFamily !== savedAppearance.fontFamily;

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.appearance.title')}
          description={t('pages.settings.appearance.description')}
        />
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <FormField label={t('pages.settings.appearance.fontFamilyLabel')}>
          <Select
            aria-label={t('pages.settings.appearance.fontFamilyLabel')}
            value={draft.fontFamily}
            onChange={(event) =>
              setDraft({ fontFamily: event.target.value as 'sans-serif' | 'serif' })
            }
          >
            <option value="sans-serif">{t('pages.settings.appearance.sansSerif')}</option>
            <option value="serif">{t('pages.settings.appearance.serif')}</option>
          </Select>
        </FormField>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--bg-secondary)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
        <p>{t('pages.settings.appearance.previewHint')}</p>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={onReset}>
            {t('common.reset')}
          </Button>
          <Button onClick={() => onSave(draft)} disabled={!hasChanges}>
            {t('common.saveChanges')}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}
```

- [ ] **Step 3: Render `AppearanceSection` inside the General Tab**

Place it after `GeneralPreferencesSection` inside the `SectionStack`:

```tsx
<AppearanceSection
  savedAppearance={settings.general.appearance}
  onSave={saveAppearanceSettings}
  onReset={resetAppearanceSettings}
/>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat(settings): add Appearance section card with font-family selector"
```

---

### Task 6: i18n Translations

**Files:**
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Add English keys under `pages.settings`**

```ts
appearance: {
  title: 'Appearance',
  description: 'Global font family preference',
  fontFamilyLabel: 'Font family',
  sansSerif: 'Sans-serif',
  serif: 'Serif',
  previewHint: 'Changes apply immediately across the entire interface.',
},
```

- [ ] **Step 2: Add Chinese keys under `pages.settings`**

```ts
appearance: {
  title: '外观',
  description: '全局字体偏好设置',
  fontFamilyLabel: '字体',
  sansSerif: '非衬线体',
  serif: '衬线体',
  previewHint: '更改将立即应用到整个界面。',
},
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/messages.ts
git commit -m "i18n: add appearance section translations"
```

---

### Task 7: Verification

**Files:** None (verification only)

- [ ] **Step 1: Run TypeScript check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: no errors.

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npm run test:run
```

Expected: all tests pass.

- [ ] **Step 3: Manual check**

1. Open Settings page → General tab
2. Confirm "Appearance" section is visible with "Font family" dropdown
3. Select "Serif" and click Save
4. Confirm all page text switches to serif font
5. Refresh the page
6. Confirm the serif setting persists
7. Click Reset and confirm text returns to sans-serif

- [ ] **Step 4: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix: address type/test issues from appearance feature"
```

---

### Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| `appearance: { fontFamily: 'sans-serif' \| 'serif' }` in `WebUiSettingsDocument.general` | Task 1 |
| Default value `sans-serif` | Task 2 |
| Backward-compatible load (missing `appearance` falls back to default) | Task 3 |
| CSS variable update via `useEffect` | Task 4 |
| Independent SectionCard in SettingsPage General tab | Task 5 |
| Chinese + English i18n | Task 6 |
| Verification (type check, tests, manual) | Task 7 |

No gaps. All requirements are covered.

### Placeholder Scan

No TBD, TODO, "implement later", or vague steps found. Every task includes exact file paths and code.

### Type Consistency

- `AppearanceSettings.fontFamily` is typed `'sans-serif' | 'serif'` consistently across types, defaults, storage, context, and UI.
- `saveAppearanceSettings` accepts `AppearanceSettings` matching the interface.
