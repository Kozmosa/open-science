# Frontend i18n Coverage Fix Design

## 目标

修复 22 个文件中 60+ 个未国际化的用户可见字符串，确保全部用户可见文本通过 `useT()` 渲染，覆盖 EN/ZH。

## 文件分组

### Group 1: 添加 `useT` 导入 + 替换 (8 文件)

| 文件 | 新增 i18n Key 前缀 |
|------|-------------------|
| `UsersTab.tsx` | `pages.settings.users.*` |
| `GanttChart.tsx` | `pages.timeline.*` |
| `AttemptSegment.tsx` | `pages.timeline.*` |
| `MessageStream.tsx` | `pages.tasks.*` |
| `PromptEditor.tsx` | `common.loading` (已有) |
| `FileTree.tsx` | `pages.fileBrowser.*` |
| `FileViewer.tsx` | `pages.fileBrowser.*` |
| `Button.tsx` | `common.loading` (已有) |

### Group 2: 补充遗漏字符串 (14 文件)

| 文件 | 遗漏区域 | 新增 Key 前缀 |
|------|---------|-------------|
| `SettingsPage.tsx` | Codex 区、安装按钮、弹窗 | `pages.settings.*` |
| `Layout.tsx` | 登出弹窗、footer、title | `common.*` |
| `CollaboratorsTab.tsx` | Loading/error | `common.*` |
| `SectionCard.tsx` | aria-label | 组件级 key |
| `SkillToggleGroup.tsx` | 未分组/mixed | 组件级 key |
| `TokenFlowBar.tsx` | Token 标签 | `components.token.*` |
| `CpuRing.tsx` | CPU label | `components.resources.*` |
| `GpuBar.tsx` | No GPU | `components.resources.*` |
| `MemoryBar.tsx` | Memory label | `components.resources.*` |
| `CardGrid.tsx` | Drag title | 组件级 key |
| `DraggableResourceCard.tsx` | Drag title | 组件级 key |
| `FileBrowserPage.tsx` | 空状态等 | `pages.fileBrowser.*` |
| `App.tsx` | Loading | `common.loading` (已有) |

## i18n 新增 Keys

EN keys to be added to `frontend/src/i18n/messages.ts`:

```typescript
// Common
'common.collapse': 'Collapse',
'common.expand': 'Expand',
'common.dragToReorder': 'Drag to reorder',
'common.confirmLogout': 'Confirm Logout',
'common.confirmLogoutMessage': 'Are you sure you want to log out?',
'common.logOut': 'Log out',
'common.cancel': 'Cancel',
'common.builtBy': 'Built by Kozmosa with ❤️',
'common.noMessages': 'No messages yet',

// Pages - Settings - Users
'pages.settings.users.title': 'Users',
'pages.settings.users.approve': 'Approve',
'pages.settings.users.disable': 'Disable',
'pages.settings.users.reEnable': 'Re-enable',
'pages.settings.users.resetPassword': 'Reset Password',
'pages.settings.users.newPassword': 'New password:',
'pages.settings.users.enterNewPassword': 'Enter new password',
'pages.settings.users.set': 'Set',
'pages.settings.users.count': '{count} users',

// Pages - Timeline
'pages.timeline.loading': 'Loading timeline...',
'pages.timeline.noSessions': 'No sessions in this time range',
'pages.timeline.session': 'Session',
'pages.timeline.attempt': 'Attempt #',
'pages.timeline.status': 'Status:',
'pages.timeline.duration': 'Duration:',
'pages.timeline.reason': 'Reason:',

// Pages - File Browser
'pages.fileBrowser.loading': 'Loading files...',
'pages.fileBrowser.files': 'Files',
'pages.fileBrowser.noFileSelected': 'No file selected',
'pages.fileBrowser.selectFile': 'Select a file to view its contents',
'pages.fileBrowser.binaryFile': 'Binary file',
'pages.fileBrowser.loadingFile': 'Loading file...',
'pages.fileBrowser.emptyDirectory': 'Empty directory',
'pages.fileBrowser.noFiles': 'No files',
'pages.fileBrowser.selectEnv': 'Select an environment to browse files',
'pages.fileBrowser.refresh': 'Refresh',

// Components - Token
'components.token.tokens': 'Tokens',
'components.token.total': 'Total:',
'components.token.input': 'Input',
'components.token.cache': 'Cache',
'components.token.output': 'Output',
'components.token.think': 'Think',

// Components - Resources
'components.resources.cpu': 'CPU Usage',
'components.resources.cores': 'cores',
'components.resources.noGpu': 'No GPU detected',
'components.resources.memory': 'Memory',

// Components - Skills
'components.skills.ungrouped': 'Ungrouped',
'components.skills.mixed': 'Mixed',

// Pages - Settings Codex
'pages.settings.codexModel': 'Codex Model',
'pages.settings.codexCommand': 'App Server Command',
'pages.settings.codexApproval': 'Approval Policy',
'pages.settings.codexConfig': 'Codex config.toml',
'pages.settings.codexAuth': 'Codex auth.json',
'pages.settings.codexEngine': 'Codex App Server',
'pages.settings.codexInstalling': '{name} installing...',
'pages.settings.codexInstall': 'Install {name}',
'pages.settings.codexUpdating': 'Updating...',
'pages.settings.codexUpdate': 'Update {name}',
'pages.settings.codexInstalled': '{name} Installed',
'pages.settings.codexForceUpdate': 'Force Update',
```
