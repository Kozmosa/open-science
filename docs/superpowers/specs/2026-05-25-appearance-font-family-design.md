# Appearance / Font Family 设计文档

> **目标：** 在设置页面新增 Appearance 卡片，允许用户切换全局字体为衬线体或非衬线体。

**架构：** 通过 `WebUiSettingsDocument.general.appearance.fontFamily` 持久化用户选择，`SettingsProvider` 在初始化及变化时通过 JS 更新根元素 CSS variable `--font-text` 和 `--font-display`，全局 `body { font-family: var(--font-text); }` 自动生效，无需逐个组件修改。

**技术栈：** React + Tailwind CSS v4 + CSS Variables + localStorage

---

## 数据模型

在 `WebUiSettingsDocument.general` 下新增 `appearance` 字段（向后兼容，不升级 version）：

```ts
interface AppearanceSettings {
  fontFamily: 'sans-serif' | 'serif';
}
```

默认值：
- `sans-serif`: `Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- `serif`: `Georgia, "Noto Serif", "Times New Roman", "Songti SC", "STSong", serif`

## 持久化

- 存储位置：`localStorage['scholar-agent:webui-settings']`
- 读取：`readStoredSettings()` 在 normalize 时若旧数据缺少 `general.appearance`，自动回退到 `sans-serif`
- 写入：`SettingsProvider.commitSettings()` 自动序列化

## CSS 生效机制

`index.css` 中已有：
```css
body {
  font-family: var(--font-text);
}
```

`SettingsProvider` 在 `useEffect` 中监听 `settings.general.appearance.fontFamily`：
- `'sans-serif'` → `document.documentElement.style.setProperty('--font-text', sansStack)`
- `'serif'` → `document.documentElement.style.setProperty('--font-text', serifStack)`

同时更新 `--font-display`（标题字体），保持与正文字体一致。

## UI

在 SettingsPage 的 General Tab 中新增一个独立的 `AppearanceSection` SectionCard：
- 标题："Appearance" / "外观"
- 描述："Global font family preference" / "全局字体偏好"
- 控件：Select 下拉框，选项 "Sans-serif（非衬线体）" 和 "Serif（衬线体）"
- 保存/重置按钮跟随现有 patterns

## 文件变更

| 文件 | 动作 | 说明 |
|------|------|------|
| `frontend/src/settings/types.ts` | 修改 | `WebUiSettingsDocument.general` 新增 `appearance: AppearanceSettings` |
| `frontend/src/settings/defaults.ts` | 修改 | `createDefaultWebUiSettings()` 中 `general` 新增 `appearance` 默认值 |
| `frontend/src/settings/storage.ts` | 修改 | `readStoredSettings()` normalize 时处理缺失的 `appearance` 字段 |
| `frontend/src/settings/context.tsx` | 修改 | `sanitizeSettings` 清洗 `appearance`；`SettingsProvider` 添加 `useEffect` 更新 CSS variable；暴露 `saveAppearanceSettings` |
| `frontend/src/pages/SettingsPage.tsx` | 修改 | General Tab 中新增 `AppearanceSection` SectionCard |
| `frontend/src/i18n/messages.ts` | 修改 | 新增 appearance 相关翻译键 |
