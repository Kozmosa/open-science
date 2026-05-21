# Literature Tracking Page Design

## 目标

为 AINRF 新增文献追踪页面（`/literature`），用户可订阅研究领域关键词和 arXiv 分类，系统定时检索新论文并经 Claude AI 提炼摘要，以卡片流展示。支持将感兴趣的论文一键转为 research task。

## 页面架构

```
frontend/src/pages/LiteraturePage.tsx
├── SubscriptionSidebar       # 左侧：订阅管理
│   ├── SubscriptionList      #   已订阅主题列表
│   ├── SubscriptionForm      #   添加订阅（关键词 + arXiv 分类 + 频率）
│   └── SeedPaperInput        #   种子论文扩散入口
├── PaperFeed                  # 右侧：论文卡片流
│   ├── PaperCard             #   单篇论文卡片
│   │   ├── FieldBadge        #     领域标签
│   │   ├── TitleRow          #     中英文标题
│   │   ├── JournalMeta       #     期刊/会议 + 日期
│   │   ├── AIInsightBlock    #     AI 提炼（实践提醒 + 重点概要）
│   │   └── ActionBar         #     "查看原文" + "转为 Task" + "标记已读"
│   └── FeedControls          #   排序/筛选/刷新
└── TaskConvertModal           # 转为 Task 的弹窗
```

## 后端数据模型

新增 `src/ainrf/literature/` 模块，使用独立 SQLite 数据库 `literature.sqlite3`。

### LiteratureSubscription

```python
class LiteratureSubscription:
    subscription_id: str       # UUID
    user_id: str               # 订阅者
    keywords: list[str]        # 检索关键词组
    arxiv_categories: list[str]# arXiv 分类 (cs.AI, cs.CL, ...)
    seed_paper_ids: list[str]  # 可选：种子论文 arxiv ID
    frequency: str             # "daily" | "twice_daily" | "weekly"
    is_active: bool
    created_at: str
    last_fetched_at: str | None
```

### LiteraturePaper

```python
class LiteraturePaper:
    paper_id: str              # arxiv ID 或 DOI（唯一键）
    subscription_id: str
    title: str
    title_zh: str | None       # AI 翻译中文标题
    authors: list[str]
    abstract: str
    journal: str | None
    published_at: str
    arxiv_category: str
    ai_summary: str | None      # AI 提炼 3 bullet points
    ai_practice_note: str | None# AI 提炼 1 句实践提醒
    is_read: bool
    is_converted_to_task: bool
    task_id: str | None
    created_at: str
```

## API Endpoints

```
GET    /literature/subscriptions          # 列出我的订阅
POST   /literature/subscriptions          # 创建订阅
PATCH  /literature/subscriptions/{id}     # 更新订阅（暂停/修改频率）
DELETE /literature/subscriptions/{id}     # 删除订阅
GET    /literature/papers                 # 列出论文（支持 ?subscription_id=&unread_only=&limit=）
POST   /literature/papers/{id}/read      # 标记已读
POST   /literature/papers/{id}/convert   # 转为 task（创建 task 并关联 task_id）
POST   /literature/subscriptions/{id}/fetch  # 手动触发检索
```

## 检索与提炼 Pipeline

```
定时调度 (apscheduler)
  │
  ▼
LiteratureFetchTask
  │
  ├─ 1. arXiv API 检索（关键词 + 分类）
  ├─ 2. Semantic Scholar API 补充元数据
  ├─ 3. 去重（排除已收录 paper_id）
  ├─ 4. Claude 提炼（每批 5 篇，使用现有 task 引擎）
  │     ├─ title_zh: 中文标题翻译
  │     ├─ ai_summary: 3 bullet points
  │     └─ ai_practice_note: 1 句实践提醒
  ├─ 5. 存入 literature_papers
  └─ 6. 更新 subscription.last_fetched_at
```

### 提炼 Prompt

```
你是一个学术文献摘要助手。请对以下论文做提炼：

1. 将标题翻译为中文（简洁准确，不超过 40 字）
2. 写 3 条"重点概要"（每条 1 句话，分别覆盖核心发现、方法创新、实践意义）
3. 写 1 条"实践提醒"（面向研究者的一句话行动建议，以"可以"开头）

论文标题: {title}
摘要: {abstract}
作者: {authors}
```

## 新增依赖

- `apscheduler` — 轻量级定时任务调度
- `arxiv` — arXiv API 客户端

## 前端组件

| 组件 | 说明 |
|------|------|
| `LiteraturePage.tsx` | 页面主组件，SplitPane 布局 |
| `SubscriptionSidebar.tsx` | 左侧订阅管理面板 |
| `SubscriptionForm.tsx` | 新增/编辑订阅表单 |
| `PaperFeed.tsx` | 右侧论文卡片流 |
| `PaperCard.tsx` | 单篇论文卡片 |
| `TaskConvertModal.tsx` | 复用现有 TaskCreateForm 逻辑 |

## 验证

1. `cd frontend && node_modules/.bin/tsc -b` — 类型检查
2. `cd frontend && npx vitest run` — 前端测试
3. `uv run pytest tests/` — 后端测试
4. 手动：创建订阅 → 手动触发 fetch → 论文卡片渲染 → 转为 task
