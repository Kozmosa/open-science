# EnvAccess & Collaborators UI Polish Design

## 目标

将 Settings 页面的 EnvAccessTab 和 CollaboratorsTab 的 UI 质量对齐到 UsersTab 的标准：CSS 变量替代硬编码颜色、完整的 i18n 国际化、loading/empty/error 状态、抽取通用组件减少重复。

## 组件架构

```
frontend/src/components/settings/
├── AccessGrantPanel.tsx    # Grant 表单（用户选择 + 额外字段 + 按钮）
└── AccessItemRow.tsx       # 已授权项行（信息 + Remove 按钮）
```

### AccessGrantPanel

```tsx
interface AccessGrantPanelProps {
  users: AdminUserResponse[]            // 可选用户列表（过滤 active）
  selectedUserId: string
  onUserChange: (id: string) => void
  onGrant: () => void
  disabled?: boolean                    // grantMutation.isPending
  extraField?: React.ReactNode          // maxTasks input (EnvAccess) 或 role select (Collaborators)
}
```

Props-driven，不耦合具体业务逻辑。渲染虚线边框的 grant 表单区域。

### AccessItemRow

```tsx
interface AccessItemRowProps {
  label: string                         // 用户名
  sublabel?: string                     // display_name
  meta?: React.ReactNode                // maxTasks 或 role badge
  onRemove: () => void
  disabled?: boolean
}
```

渲染带 CSS 变量的行，左侧 label+sublabel，右侧 meta+Remove 按钮。

## EnvAccessTab 重写

- 使用 `<SectionHeader>` 替代裸 `<h3>`
- 环境选择器 `Select` 组件
- 已授权用户列表使用 `AccessItemRow`
- Grant 表单使用 `AccessGrantPanel`，extraField 为 maxTasks 输入框
- 加载态：查询中显示 LoadingSpinner
- 空状态："No environment selected" 或 "No access grants"
- 错误态：提取 mutation.error 显示
- 全部硬编码颜色替换为 CSS 变量
- 全部英文文本替换为 i18n key

## CollaboratorsTab 重写

- 项目选择器 `Select` 组件
- 协作者列表使用 `AccessItemRow`，meta 为 role badge（member/viewer）
- Grant 表单使用 `AccessGrantPanel`，extraField 为 role select
- 加载态/空状态/错误态同上
- 全部硬编码颜色替换为 CSS 变量
- 全部英文文本替换为 i18n key

## i18n Keys (messages.ts)

EN:
```typescript
'pages.settings.envAccess': 'Environment Access',
'pages.settings.envAccess.selectEnv': 'Select environment...',
'pages.settings.envAccess.maxTasks': 'Max tasks',
'pages.settings.envAccess.unlimited': 'unlimited',
'pages.settings.envAccess.grant': 'Grant',
'pages.settings.envAccess.remove': 'Remove',
'pages.settings.envAccess.grantTo': 'Grant to...',
'pages.settings.envAccess.noEnvSelected': 'Select an environment to manage access.',
'pages.settings.envAccess.noAccess': 'No access grants yet.',
'pages.settings.collaborators': 'Project Collaborators',
'pages.settings.collaborators.selectProject': 'Select project...',
'pages.settings.collaborators.add': 'Add',
'pages.settings.collaborators.addUser': 'Add user...',
'pages.settings.collaborators.remove': 'Remove',
'pages.settings.collaborators.role.member': 'Member',
'pages.settings.collaborators.role.viewer': 'Viewer',
'pages.settings.collaborators.noProjectSelected': 'Select a project to manage collaborators.',
'pages.settings.collaborators.noCollaborators': 'No collaborators yet.',
```

ZH:
```typescript
'pages.settings.envAccess': '环境授权',
'pages.settings.envAccess.selectEnv': '选择环境...',
'pages.settings.envAccess.maxTasks': '最大任务数',
'pages.settings.envAccess.unlimited': '无限制',
'pages.settings.envAccess.grant': '授权',
'pages.settings.envAccess.remove': '移除',
'pages.settings.envAccess.grantTo': '授权给...',
'pages.settings.envAccess.noEnvSelected': '选择一个环境以管理访问权限。',
'pages.settings.envAccess.noAccess': '暂无授权记录。',
'pages.settings.collaborators': '项目协作者',
'pages.settings.collaborators.selectProject': '选择项目...',
'pages.settings.collaborators.add': '添加',
'pages.settings.collaborators.addUser': '添加用户...',
'pages.settings.collaborators.remove': '移除',
'pages.settings.collaborators.role.member': '成员',
'pages.settings.collaborators.role.viewer': '观察者',
'pages.settings.collaborators.noProjectSelected': '选择一个项目以管理协作者。',
'pages.settings.collaborators.noCollaborators': '暂无协作者。',
```

## 验证

1. `cd frontend && node_modules/.bin/tsc -b` — 类型检查通过
2. `cd frontend && npx vitest run` — 133 测试通过
3. 手动：Settings 页面 EnvAccess tab 和 Collaborators tab 切换中英文，颜色跟随亮暗模式
