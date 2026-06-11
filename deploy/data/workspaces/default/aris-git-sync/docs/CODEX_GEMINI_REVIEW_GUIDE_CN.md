# Codex + Gemini 审稿人指南

使用：

- **Codex** 作为主执行者
- **Gemini** 作为审稿人
- 本地 `gemini-review` MCP bridge 作为传输层
- **direct Gemini API** 作为默认 reviewer backend

这份指南是对上游 `skills/skills-codex/` 的**叠加方案**，不是替换。

## 架构

- 基础 skill 集：`skills/skills-codex/`
- 审稿覆盖层：`skills/skills-codex-gemini-review/`
- 审稿 bridge：`mcp-servers/gemini-review/`

安装顺序很重要：

1. 先安装 `skills/skills-codex/*`
2. 再安装 `skills/skills-codex-gemini-review/*`
3. 最后注册 `gemini-review` MCP

## 安装

```bash
git clone https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git
cd Auto-claude-code-research-in-sleep

mkdir -p ~/.codex/skills
cp -a skills/skills-codex/* ~/.codex/skills/
cp -a skills/skills-codex-gemini-review/* ~/.codex/skills/

mkdir -p ~/.codex/mcp-servers/gemini-review
cp mcp-servers/gemini-review/server.py ~/.codex/mcp-servers/gemini-review/server.py
cp mcp-servers/gemini-review/README.md ~/.codex/mcp-servers/gemini-review/README.md
codex mcp add gemini-review --env GEMINI_REVIEW_BACKEND=api -- python3 ~/.codex/mcp-servers/gemini-review/server.py
```

推荐凭证文件：

```bash
mkdir -p ~/.gemini
cat > ~/.gemini/.env <<'EOF'
GEMINI_API_KEY="your-key"
EOF
chmod 600 ~/.gemini/.env
```

如果存在，bridge 会自动加载 `~/.gemini/.env`。

## 为什么默认走 direct API

- 这条路径的目标是：**最大化复用原始 ARIS 的 reviewer-aware skills，同时最少改 skill**。
- `gemini-review` bridge 保留了与 Claude-review overlay 相同的 `review` / `review_reply` / `review_start` / `review_reply_start` / `review_status` 契约。
- 直接走 Gemini API 可以去掉本地 CLI 这一跳，让 reviewer 路径更接近 ARIS 里已有的 API 型集成方式。

## 接入边界说明

- Google AI Studio / Gemini API 在支持地区提供免费层；这**不要求**你先订阅 Gemini Advanced / Google One AI Premium。
- 免费层可用模型、速率限制和配额会变化，不应把某个固定额度或旧模型示例写成长期承诺。
- 免费层下的 prompt / response 处理条款与付费层不同；如果涉及敏感数据，必须先核对官方当前条款。
- 官方入口与定价说明：
  - API key / AI Studio：<https://aistudio.google.com/apikey>
  - Gemini API 定价与免费层：<https://ai.google.dev/gemini-api/docs/pricing>

## 可选 CLI fallback

这份指南的预期路径是 direct API。  
如果你明确想切到 Gemini CLI，可改成：

```bash
codex mcp remove gemini-review
codex mcp add gemini-review --env GEMINI_REVIEW_BACKEND=cli -- python3 ~/.codex/mcp-servers/gemini-review/server.py
```

但这不是本指南的主路径。

## 验证

1. 检查 MCP 是否注册成功：

```bash
codex mcp list
```

2. 检查本地 Gemini 凭证文件是否存在：

```bash
test -f ~/.gemini/.env && echo "Gemini env file found"
```

3. 在你的项目里启动 Codex：

```bash
codex -C /path/to/your/project
```

## 排障

如果默认 API 模型在你当前的免费层时间窗口里返回临时 `429`，不要改 bridge 结构，只需要覆盖 reviewer model：

```bash
codex mcp remove gemini-review
codex mcp add gemini-review --env GEMINI_REVIEW_BACKEND=api --env GEMINI_REVIEW_MODEL=gemini-flash-latest -- python3 ~/.codex/mcp-servers/gemini-review/server.py
```

这不会改变 ARIS 的 reviewer 契约，也不会改变 skill overlay 的组织方式，只是让同一个本地 `gemini-review` bridge 在底层改用另一个 Gemini API 模型。

## 验证结果摘要

这条路径做了两层验证：

- **全量 overlay 覆盖检查**：`skills/skills-codex-gemini-review/` 覆盖的 `15` 个预定义 reviewer-aware Codex skill 都逐一核对过，确认已经指向 `gemini-review`，不再依赖旧的 reviewer transport。
- **bridge 运行时验证**：本地 `gemini-review` MCP bridge 实测覆盖了：
  - `review`
  - `review_reply`
  - `review_start`
  - `review_reply_start`
  - `review_status`
  - 基于本地图像的 `imagePaths` 多模态审查
- **代表性 Codex 侧 smoke test**：我们在一个私有、未公开的研究仓库上实跑了这套 overlay，确认真实的 Codex 执行能够进入 Gemini reviewer 路径，覆盖了研究审稿、idea 生成、论文规划这几类代表性工作流。

已经验证通过的点：

- direct API 审稿可以返回有效 reviewer 文本
- 异步 review job 可以完成，并可通过 `review_status` 恢复状态
- 带 thread 状态的 follow-up review 可以继续多轮对话
- `imagePaths` 本地图像审查可用
- 已实跑的 Codex skill 路径能够正确加载 Gemini overlay，并发出真实的 `gemini-review` tool call

测试中的实际观察：

- Gemini 免费层对这条 reviewer 路径是可用的，但如果在很短时间内集中压测，仍然可能出现临时 `429`
- 速率限制表现和具体模型有关；当前 API 模型面应以 AI Studio / `ListModels` 为准，而不是沿用旧配额表里的模型示例
- 在同一套环境上的后续重试中，把 `GEMINI_REVIEW_MODEL` 覆盖为 `gemini-flash-latest` 后，direct API bridge 已成功跑通同步 review、异步 `review_start` -> `review_status` 以及带 thread 的 `review_reply_start` -> `review_status`
- 这类 `429` 更像是短时间 burst limit，而不是集成本身失效
- 对超长 prompt，宿主侧 MCP tool timeout 仍可能先于同步调用返回，所以长审稿默认仍推荐 `review_start` / `review_reply_start` + `review_status`

这也是为什么 bridge 同时暴露同步和异步工具，而 reviewer-aware skill overlay 默认优先走异步流程。

## 会覆盖哪些 skill

这个 overlay 会替换预定义的 reviewer-aware Codex skills：

- `idea-creator`
- `idea-discovery`
- `idea-discovery-robot`
- `research-review`
- `novelty-check`
- `research-refine`
- `auto-review-loop`
- `grant-proposal`
- `paper-plan`
- `paper-figure`
- `paper-poster-html`
- `paper-slides`
- `paper-write`
- `paper-writing`
- `auto-paper-improvement-loop`

其它能力仍然来自上游 `skills/skills-codex/`。

## 核心 8 个 vs 运行态 15 个

这条路径有两种都成立的描述方式：

- **核心 8 个**：和现有 Claude-review 路径一一对齐的 reviewer overlay 核心集合
- **运行态 15 个**：当前安装后的 Codex skill 集里，实际切到 Gemini reviewer 的完整 reviewer-aware 技能面

其中 **核心 8 个** 是：

- `research-review`
- `novelty-check`
- `research-refine`
- `auto-review-loop`
- `paper-plan`
- `paper-figure`
- `paper-write`
- `auto-paper-improvement-loop`

这 8 个最直接对应早先 Claude-review overlay 的组织方式和 reviewer 契约。

另外扩展进去的 **7 个** reviewer-aware 技能是：

- `idea-creator`
- `idea-discovery`
- `idea-discovery-robot`
- `grant-proposal`
- `paper-writing`
- `paper-slides`
- `paper-poster-html`

所以更准确的理解是：

- **核心机制** 仍然沿用和 Claude 路径相同的 8-skill overlay 形状
- **运行态 reviewer 覆盖面** 则已经扩展到 15 个 skill

这也解释了为什么 diff 更大，但并不意味着 reviewer 契约本身被改乱了。

## 直接消费者 vs wrapper

这 15 个 skill 里又可以分成两类：

- **12 个直接消费者**：自己会直接调用 `mcp__gemini-review__review_start` / `review_reply_start` / `review_status`
  - `research-review`
  - `novelty-check`
  - `research-refine`
  - `auto-review-loop`
  - `paper-plan`
  - `paper-figure`
  - `paper-write`
  - `auto-paper-improvement-loop`
  - `idea-creator`
  - `grant-proposal`
  - `paper-slides`
  - `paper-poster-html`
- **3 个 wrapper**：主要负责串联下游 reviewer-aware 子 skill，并向下传递 `REVIEWER_MODEL=gemini-review`
  - `idea-discovery`
  - `idea-discovery-robot`
  - `paper-writing`

这层分类对验收很重要：不需要把 15 条工作流都完整跑到底，才能证明 reviewer transport 是通的。对于 PR 验收，更合理的做法是：全量结构检查 + bridge 运行时验证 + 少量直接消费者 / wrapper 的代表性 smoke test 组合验证。

## 异步 reviewer 流程

对于长论文 / 长项目审稿，使用：

- `review_start`
- `review_reply_start`
- `review_status`

原因：即便走 direct API，超长同步 reviewer 调用仍然可能撞上宿主侧的 MCP timeout。保留异步 `review*` 流程，才能在**不改原有 reviewer-aware skill 行为**的前提下继续复用它们。

## 项目配置

这条路径不需要额外的项目配置文件。

- 继续使用你现有的 `CLAUDE.md`
- 保持现有项目布局
- 只切换安装的 Codex skill 文件和 MCP 注册

## 维护原则

让这条路径保持足够窄：

- 基础能力继续复用 `skills/skills-codex/*`
- 只在 `skills/skills-codex-gemini-review/*` 里覆盖 reviewer-aware skills
- 让 `mcp-servers/gemini-review/server.py` 只聚焦 `review*` 兼容契约
- 如果某个 skill 需要审查 poster PNG，就通过 direct Gemini API backend 传 `imagePaths`，而不是再发明第二套 bridge
