# AINRF Skill 注入系统设计

## 背景

AINRF 当前 skill 系统仅将 skill ID 作为文本列在 prompt 中（"Enabled skills: web-search, code-analysis"），没有真正的运行时能力注入。本设计实现跨任务、跨环境的 skill 管理和深度注入机制。

## 核心约束

- **不修改 Claude Code 源码**：只能通过 `settings.json`、命令行参数、`CLAUDE.md` 等外部配置注入
- **AINRF 是一等公民**：工作目录由 AINRF 管理，用户在 AINRF 之后介入
- **与本地 Claude Code 解耦**：不依赖 `~/.claude/skills/`，AINRF 自建 skill 仓库
- **聚焦 Claude Code**：当前仅支持 Claude Code，架构预留扩展点

---

## 1. 架构概述

### 核心原则

1. **`.ainrf/` 是源（Source of Truth）**，由 AINRF 完全拥有和管理
2. **`.claude/` 是派生（Derived）**，通过同步机制从 `.ainrf/` 生成
3. **同步发生在任务启动前**，确保 Claude Code 启动时看到一致性状态

### 目录结构

```
<workdir>/
  .ainrf/                           # AINRF 主目录（一等公民）
    skills/                         # Skill 定义仓库
      <skill-id>/
        skill.json                  # AINRF 元数据
        SKILL.md                    # Claude Code 格式指令
        scripts/                    # 可执行脚本
        hooks/                      # Claude Code hooks
        mcp/                        # MCP server 配置
    settings.json                   # 生成的 CC settings
    tool-manifest.json              # 工具清单（供前端展示）
    CLAUDE.md                       # 项目级上下文（可选）

  .claude/                          # CC 兼容目录（派生）
    skills/ -> ../.ainrf/skills     # 符号链接（本地）或硬拷贝
    settings.json                   # 从 .ainrf/settings.json 同步
    .ainrf-managed                  # 标记文件，表明由 AINRF 管理
```

### 注入分层

| 层级 | 内容 | 通道 | 生效方式 |
|-----|------|------|---------|
| **指令层** | SKILL.md | `.ainrf/skills/` → `.claude/skills/` | CC 自动发现并加载 skill 指令 |
| **配置层** | settings-fragment | 合并 → `.ainrf/settings.json` | `--settings .ainrf/settings.json` |
| **工具层** | scripts/ + mcp/ | 随 skill 目录同步 | CC 通过 MCP / hooks / Bash 调用 |

---

## 2. Skill 仓库格式

AINRF Skill 采用**扩展的 Claude Code Skill 格式**，在标准 `SKILL.md` 基础上增加元数据、脚本和配置层。

### 单 Skill 目录结构

```
.ainrf/skills/<skill-id>/
  skill.json              # AINRF 元数据（必需）
  SKILL.md                # CC 格式指令（必需）
  scripts/                # 可执行脚本（可选）
  hooks/                  # Claude Code hooks（可选）
  mcp/
    server-config.json    # MCP server 配置（可选）
    server.py             # MCP server 实现（可选）
  setup.sh                # 依赖安装脚本（可选）
  requirements.txt        # Python 依赖（可选）
```

### `skill.json` 元数据格式

```json
{
  "skill_id": "web-search",
  "label": "Web Search",
  "description": "Search the web for academic and general information",
  "version": "1.0.0",
  "author": "ainrf",
  "dependencies": [],
  "inject_mode": "auto",
  "settings_fragment": {
    "env": {
      "SEARCH_API_KEY": "${SEARCH_API_KEY}"
    }
  },
  "mcp_servers": ["web-search-mcp"],
  "hooks": ["session-start"],
  "allowed_agents": ["claude-code"]
}
```

字段说明：

| 字段 | 类型 | 说明 |
|-----|------|------|
| `skill_id` | string | 唯一标识，与目录名一致 |
| `version` | string | SemVer |
| `dependencies` | string[] | 依赖的其他 skill（按顺序注入） |
| `inject_mode` | "auto" \| "prompt_only" \| "disabled" | auto=完整注入；prompt_only=只拼入 prompt；disabled=不注入 |
| `settings_fragment` | object | 要合并到 settings.json 的片段，支持 `${VAR}` 占位符 |
| `mcp_servers` | string[] | 该 skill 需要的 MCP server 列表 |
| `hooks` | string[] | 该 skill 注册的 hook 列表 |
| `allowed_agents` | string[] | 支持的 agent 类型（当前仅 claude-code） |

### `SKILL.md` 格式（兼容 Claude Code）

沿用 Claude Code 的标准格式：

```markdown
---
name: web-search
description: Search the web for information
argument-hint: [query]
allowed-tools: Bash(*), Read, WebSearch, WebFetch
---

# Web Search

Search the web for academic papers, documentation, and general information.

## When to Use

- User asks about external knowledge
- Need to verify facts or find references

## Workflow

1. Formulate search query
2. Execute search
3. Summarize findings
```

### `scripts/` 目录

可执行脚本，CC 通过 `Bash` 工具调用。脚本需要带有 shebang 和可执行权限。AINRF 在同步时自动 `chmod +x`。

### `hooks/` 目录

Claude Code 的 hook 脚本，与 CC 的 `settings.json` hooks 机制对接。多个 skill 注册同一 hook 时，按 skill 依赖顺序链式调用（生成 wrapper script）。

### `mcp/server-config.json`

标准 MCP server 配置：

```json
{
  "mcpServers": {
    "web-search": {
      "command": "python3",
      "args": [".ainrf/skills/web-search/scripts/mcp-server.py"],
      "env": {
        "API_KEY": "${SEARCH_API_KEY}"
      }
    }
  }
}
```

---

## 3. 同步机制

同步负责将 `.ainrf/` 的内容反映到 `.claude/`，使 Claude Code 能够发现和使用 skill。

### 同步触发时机

同步在**任务启动前**执行，位于 `launcher.py` 的 `build_local_launcher` / `build_remote_launcher` 之前：

```
任务启动流程：
  1. 收集选中 skill 列表
  2. 生成 .ainrf/ 目录内容（skill 内容 + settings.json）
  3. 【同步】.ainrf/ → .claude/
  4. 启动 Claude Code（--settings .ainrf/settings.json）
```

### 本地环境同步策略

| 策略 | 实现 | 适用场景 | 优缺点 |
|-----|------|---------|--------|
| **符号链接**（默认） | `.claude/skills -> .ainrf/skills` | 同文件系统 | 零拷贝、实时同步；但某些文件系统/容器不支持 |
| **硬链接** | `ln .ainrf/skills/*/SKILL.md .claude/skills/*/` | 同分区 | 不占用额外空间；但不能跨文件系统 |
| **全拷贝** | `cp -r .ainrf/skills/ .claude/skills/` | 通用 | 最兼容；但占用磁盘、同步延迟 |

**推荐策略：优先软链接，降级到硬链接，最后全拷贝。**

`settings.json` 不创建链接，而是**拷贝**（因为 CC 会读写该文件）。

### 冲突处理

工作目录可能已有 `.claude/`（用户使用 Claude Code 直接操作过）：

| 冲突场景 | 处理策略 |
|---------|---------|
| `.claude/skills/` 已存在且是目录 | 备份为 `.claude/skills.bak.<timestamp>`，然后创建链接/拷贝 |
| `.claude/skills/` 已是链接 | 检查指向，如果指向 `.ainrf/skills` 则跳过；否则替换 |
| `.claude/settings.json` 已存在 | 备份后覆盖（AINRF 的 settings 优先） |

### 清理策略

- **`.ainrf/` 保留**：作为 AINRF 的配置目录，类似 `.vscode/`
- **`.claude/` 保留但标记**：在 `.claude/.ainrf-managed` 中写入标记，表明由 AINRF 管理
- **备份文件清理**：任务成功启动后删除 `.skills.bak.*` 等临时备份

### 备选路径：CC 自举同步

主路径由 AINRF Python 代码完成同步。备选路径：AINRF 生成 `.ainrf/` 后，调用一次零配置 Claude Code：

```bash
claude -p --permission-mode bypassPermissions \
  "Sync .ainrf/skills to .claude/skills, then verify settings.json is valid"
```

此路径在 AINRF 无法创建符号链接（如权限受限环境）时作为 fallback。

---

## 4. Settings 与配置注入

`.ainrf/settings.json` 由三层合并生成：

```
最终 settings.json = Base Settings ⊕ Skill Fragments ⊕ Task Overrides
```

| 层级 | 来源 | 优先级 | 说明 |
|-----|------|--------|------|
| **Base** | AINRF 默认模板 | 最低 | 安全默认值 |
| **Skill Fragments** | 各 skill 的 `skill.json.settings_fragment` | 中 | 按 skill 依赖顺序依次合并 |
| **Task Overrides** | 任务创建时传入的 `settings_json` | 最高 | 用户显式指定的配置 |

### 合并规则

- 字典键：后层覆盖前层
- 列表：追加合并，同 key 后层覆盖
- 嵌套对象：递归合并

### 环境变量解析

Skill 的 `settings_fragment` 中可能包含 `${VAR}` 占位符。AINRF 在生成最终 `settings.json` 时：
- 从 AINRF 的 secret 管理系统读取（如果已实现）
- 从当前进程环境变量读取（fallback）
- 如果变量未解析，保留占位符并在启动前告警

### MCP Server 配置聚合

所有选中 skill 的 `mcp/server-config.json` 被聚合到 `settings.json` 的 `mcpServers` 字段。路径使用**相对路径**（相对于 `workdir`），确保本地和远程通用。

---

## 5. 工具注入层（MCP / Scripts）

### MCP Server 注入

AINRF skill 可以携带 MCP server 实现：

- **标准 MCP**：`mcp/server.py` + `mcp/server-config.json`，CC 启动时自动连接
- **AINRF 原生 MCP Bridge**：统一 MCP server 连接 AINRF API，暴露 `mcp__ainrf__*` 工具给 CC

### 脚本工具注入

轻量级工具直接通过可执行脚本，CC 通过 `Bash` 调用。SKILL.md 中指导 CC 何时调用这些脚本。

### 工具发现机制

AINRF 生成 `.ainrf/tool-manifest.json`，供前端展示"该任务可用的工具"，也用于运行时校验。

### 远程依赖处理

| 依赖类型 | 处理策略 |
|---------|---------|
| Python 脚本 | 依赖 `python3` 已在远程安装；复杂依赖通过 `requirements.txt` 在首次运行时自动安装 |
| Node 脚本 | 类似处理，依赖 `node` 已安装 |
| 系统命令 | SKILL.md 中声明 `required_commands`，启动前校验 |

Skill 可包含 `setup.sh`，AINRF 在同步后、启动前执行。

### 安全边界

- 脚本只能访问 `workdir` 及其子目录
- MCP server 的网络访问遵循 CC 的 `network_access` 设置
- API key 等通过 `settings.json` 的 `env` 注入，不硬编码在脚本中

---

## 6. 本地 vs 远程策略

### 本地执行

```
1. AINRF 服务端生成 .ainrf/ 到 <workdir>/
2. 同步 .ainrf/ → .claude/（软链接优先）
3. launcher 启动 CC：claude -p --settings <workdir>/.ainrf/settings.json "<prompt>"
```

### 远程执行（SSH）

```
1. AINRF 服务端生成 .ainrf/
2. SSH 上传 .ainrf/ 完整内容到远程 <workdir>/.ainrf/
3. SSH 在远程执行同步：.ainrf/ → .claude/（远程使用硬链接或拷贝）
4. 如有 setup.sh，SSH 执行安装依赖
5. 上传 launch.sh，其中 --settings 指向远程 .ainrf/settings.json
6. 启动 CC
```

新增上传内容：`.ainrf/skills/`、`.ainrf/settings.json`、`.ainrf/tool-manifest.json`。

### 本地容器执行（Tmux 免 SSH）

对于 localhost 容器环境（不通过 SSH，而是通过 tmux 终端）：

- 如果容器与主机共享文件系统（如 Docker volume mount），`.ainrf/` 生成后直接可见
- 如果不共享，通过 tmux 命令发送文件内容到容器内重建 `.ainrf/`
- 同步逻辑与本地相同

### 路径处理

settings.json 和 SKILL.md 中的路径统一使用**相对路径**（相对于 `workdir`）。本地和远程使用完全相同的 `settings.json` 内容，无需路径转换。

### 性能优化

- 只上传选中的 skill（而非整个仓库）
- 远程端缓存 `.ainrf/skills/` 目录，对比 hash 选择性更新
- scripts/ 目录支持排除列表

---

## 7. 前端变更与 API 扩展

### 前端 Skill 管理

**SettingsPage - Skill 仓库管理**：

新增"Skill 仓库"标签页，允许用户：
- 查看 AINRF skill 仓库中的 skill 列表（含版本、inject_mode、工具数）
- 查看 skill 详情和 instruction.md 内容
- 启用/禁用 skill（影响所有新任务）
- 从 Git URL 或本地目录导入自定义 skill

**TaskCreateForm - 任务级 Skill 选择**：

- 显示每个 skill 的 inject_mode
- 显示 skill 依赖关系
- 预览生成的 `.ainrf/settings.json` 片段（高级用户）

### 后端 API 扩展

| 端点 | 方法 | 说明 |
|-----|------|------|
| `/skills` | GET | 扩展：返回完整元数据（版本、inject_mode、依赖） |
| `/skills/{skill_id}` | GET | 【新增】返回 skill 详情（元数据 + instruction.md） |
| `/skills/{skill_id}/preview` | GET | 【新增】预览该 skill 生成的 settings 片段 |
| `/skills/import` | POST | 【新增】从 Git URL 或本地路径导入 skill |

### 数据流变更

```
当前数据流：
  TaskCreateRequest.research_agent_profile.skills: string[]
  → 只用于 prompt 文本拼接

新数据流：
  TaskCreateRequest.research_agent_profile.skills: string[]
  → SkillInjectionService 收集完整 skill 定义
  → 生成 .ainrf/ 目录
  → 同步到 .claude/
  → launcher 启动 CC 时加载
```

---

## 8. 集成文件清单

### 新增文件

| 文件 | 说明 |
|-----|------|
| `src/ainrf/skills/injection.py` | SkillInjectionService：生成 .ainrf/、合并 settings、同步到 .claude/ |
| `src/ainrf/skills/loader.py` | 从 .ainrf/skills/ 加载完整 skill 定义 |

### 修改文件

| 文件 | 变更 |
|-----|------|
| `src/ainrf/skills/models.py` | 扩展 SkillItem，新增 SkillDefinition、SkillManifest dataclass |
| `src/ainrf/skills/discovery.py` | 扩展发现逻辑，读取完整 skill 内容 |
| `src/ainrf/task_harness/launcher.py` | 扩展远程 launcher：上传 .ainrf/、执行远程同步 |
| `src/ainrf/task_harness/prompting.py` | 根据 skill.inject_mode 决定是否拼入 prompt |
| `src/ainrf/api/routes/skills.py` | 新增 skill 详情、预览、导入端点 |
| `frontend/src/pages/SettingsPage.tsx` | 新增 Skill 仓库管理标签页 |
| `frontend/src/pages/tasks/TaskCreateForm.tsx` | 增强 skill 选择 UI |

---

## 9. 风险与后续扩展

### 已知风险

- Claude Code `-p` 模式对 skill 的加载行为未完全文档化，需要实际验证
- 远程环境的 Python/Node 依赖可能缺失，需要完善的错误提示
- `.ainrf/` 目录可能被用户误删，需要检测和重建机制

### 后续扩展

- **Codex 支持**：新增 `allowed_agents: ["codex"]`，生成 `.codex/skills/` 和 `config.toml`
- **Skill Marketplace**：从远程 Git 仓库订阅 skill 集合
- **Skill 版本管理**：支持 skill 升级和回滚
- **运行时 Skill 热切换**：任务运行中动态启用/禁用 skill（需 CC 支持）
