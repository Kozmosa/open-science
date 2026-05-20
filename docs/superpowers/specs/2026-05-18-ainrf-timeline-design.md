# AINRF Timeline — Design Spec

Date: 2026-05-18 | Session: `ainrf-h2` | Status: draft | Depends on: Session Chain, Token Track

## Motivation

Session Chain 提供了 session + attempt 数据模型，Token Track 提供了 cost 数据。Timeline 是 AINRF ← Humanize2 借鉴路线图的第三步：纯前端的 Gantt 图表，可视化所有研究会话的时间分布，展示每次尝试的持续时间、状态和成本，跨项目筛选。

## Design Summary

- **Pure frontend** — 零后端改动。数据完全来自现有 `GET /sessions` + `GET /sessions/{id}` API
- **Gantt-style** — 左侧 session 标签 + 右侧时间轴，每个 attempt 作为一个百分比定位的色块
- **Filterable** — 按 project、日期范围、quick presets 筛选
- **Interactive** — hover tooltip 展示 attempt 详情，点击跳转到关联 task/session

## Page Layout

```
TimelinePage
  └── PageShell
       └── SectionStack(gap=4)
            ├── TimelineControls
            │    ├── ProjectSelect (dropdown)
            │    ├── DateRangePicker (from → to)
            │    ├── QuickPresets (Today / Past 7d / Past 30d)
            │    └── Summary (session count + total cost)
            └── GanttChart
                 ├── GanttHeader (time axis labels, adaptive unit)
                 └── GanttRow[] (one per session)
                      ├── GanttLabel (session title + stats)
                      └── GanttTrack
                           └── AttemptSegment[] (colored bars positioned by %)
```

## Component Details

### TimelinePage

- 路由 `/timeline`
- 使用 `useQuery` 加载 sessions 列表 (`GET /sessions?project_id=&status=`)
- 使用 `useQueries` 批量加载每个 session 的 attempts (`GET /sessions/{id}`)
- 轮询间隔：sessions 15s，session details 30s
- Filter 变化时重新加载

### GanttChart

**时间范围计算：**
```typescript
minTime = Math.min(...allAttempts.map(a => new Date(a.started_at).getTime()))
maxTime = Math.max(...allAttempts.map(a => new Date(a.finished_at || a.started_at).getTime()))
span = maxTime - minTime
```

**Attempt 定位：**
```typescript
left = (startTime - minTime) / span * 100   // percentage
width = Math.max(1, (endTime - startTime) / span * 100)  // min 1% visible
```

**自适应时间轴单位：**
- span ≤ 24h → hour labels
- span ≤ 7 days → day labels
- span > 7 days → week labels

### AttemptSegment

**颜色映射：**
- `completed` → green (`bg-green-300`)
- `running` → blue (`bg-blue-300`)
- `failed` → red (`bg-red-300`)
- `interrupted` → yellow (`bg-yellow-300`)

**Hover tooltip：** attempt # · status · duration · cost · intervention_reason · task link
**Click：** 跳转到 `/tasks/{task_id}`

### GanttLabel

- Session title
- 迷你 stats：attempt count · total cost · total tokens
- Click → 跳转到 `/sessions`（带 selected 参数）

### TimelineControls

- ProjectSelect：从 `GET /projects` 获取项目列表
- DateRangePicker：from / to 日期输入
- QuickPresets：Today / Past 7 days / Past 30 days 按钮
- Summary：当前筛选范围内的 session 数量 + 总 cost

## Data Flow

```
GET /sessions?project_id=X       GET /projects
        |                               |
  sessionsQuery.data              projectsQuery.data
        |                               |
        +--- useQueries batch ----------+
        |   GET /sessions/{id} × N
        |       |
        |   attempt lists
        v       v
  compute GanttRows:
    minTime / maxTime / span
    → AttemptSegment { left%, width% }
        |
        v
  GanttChart render
```

## TypeScript Types

全部复用现有类型，无需新增：

```typescript
// 现有类型
SessionRecord, SessionDetailRecord, AttemptRecord
// 均已定义在 frontend/src/types/index.ts

// 组件内部计算类型（不导出）
interface GanttAttempt { attempt: AttemptRecord; left: number; width: number }
interface GanttRow { session: SessionRecord; attempts: GanttAttempt[] }
```

## Implementation Order

1. TimelinePage + 路由 `/timeline` + i18n + 导航栏（`Timeline` 图标）
2. GanttChart + GanttRow + AttemptSegment 核心渲染
3. TimelineControls（筛选器 + 时间预设）+ Tooltip 交互
4. Frontend tests + Integration verification

## Testing (Vitest)

- TimelineControls：project 筛选触发 API 调用、preset 更新日期、summary 正确
- GanttChart：空态、单 session、多 session 时间轴标签渲染
- AttemptSegment：left/width 计算、min width 1%、status 颜色
- 自适应时间单位：≤24h→hour, ≤7d→day, >7d→week
- Tooltip：hover 显示 attempt 详情卡片

## Visual Companion

Brainstorming 可视化页面：`docs/superpowers/specs/2026-05-18-ainrf-timeline/visual-companion/`
