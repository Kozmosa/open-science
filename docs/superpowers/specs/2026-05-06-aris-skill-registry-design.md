# AINRF 默认技能库（ARIS）集成设计

## 背景

AINRF 当前支持用户手动导入技能（git 或本地路径），但缺少对社区主流技能仓库的一键集成能力。ARIS（Auto-claude-code-research-in-sleep）是研究场景下最成熟的技能集合之一，包含 76 个可组合 skill。本设计实现 AINRF 对 ARIS 的默认集成，并为未来支持更多社区技能仓库预留扩展性。

## 核心约束

- **不修改现有 SkillLoader**：`SkillLoader` 是 skills 系统的核心，要求 `skill.json` + `SKILL.md` 的约束保持不变
- **git 工作区与装载目录解耦**：git 同步在独立工作区进行，skill 装载目录不直接暴露 git 状态
- **单向同步**：从 git 工作区到装载目录单向更新，装载目录的 skill.json 由同步服务生成
- **配置驱动**：架构支持多个推荐技能库，但当前仅预配置 ARIS

---

## 1. 架构概述

### 目录结构

```
workspace/default/
├── skills/                        # 技能装载目录（SkillsDiscoveryService 扫描此处）
│   ├── arxiv/
│   │   ├── skill.json             # 由同步服务生成
│   │   └── SKILL.md               # 从 aris-git-sync 复制
│   ├── research-lit/
│   │   ├── skill.json
│   │   └── SKILL.md
│   └── ...                        # 其他 ARIS skills + 用户手动导入的 skills
│
├── aris-git-sync/                 # ARIS git 工作区（不作为 scan root）
│   ├── .git/
│   ├── skills/
│   │   ├── arxiv/SKILL.md
│   │   ├── research-lit/SKILL.md
│   │   └── ...                    # 76 个 skill 目录
│   └── ...
│
└── .ainrf/                        # AINRF 运行时数据
    ├── skill_registries.json      # 注册表配置持久化（SQLite 或 JSON）
    └── ...
```

### 核心组件

| 组件 | 职责 | 位置 |
|-----|------|------|
| **SkillRegistryConfig** | 定义推荐技能库的元数据（名称、URL、核心子集） | `src/ainrf/skills/registry.py` |
| **SkillRegistrySyncService** | 管理 git 工作区、检测更新、执行同步 | `src/ainrf/skills/registry_sync.py` |
| **SkillRegistryAPI** | 暴露安装/更新/状态查询端点 | `src/ainrf/api/routes/skill_registries.py` |
| **SkillJsonGenerator** | 从 SKILL.md frontmatter 生成 skill.json | `src/ainrf/skills/json_generator.py` |

---

## 2. 数据模型

### 2.1 SkillRegistryConfig（配置模型）

```python
class SkillRegistryConfig:
    registry_id: str              # 唯一标识，如 "aris"
    display_name: str             # 展示名称，如 "ARIS"
    git_url: str                  # Git 仓库地址
    git_ref: str                  # 分支或 tag，默认 "main"
    source_skills_path: str       # 仓库内 skills 根目录相对路径，如 "skills"
    core_skill_ids: list[str]     # 核心子集 skill_id 列表
    install_mode: str             # "copy" 或 "symlink"（预留）
    enabled: bool                 # 是否在前端展示
```

**当前预配置（仅 ARIS）：**

```python
DEFAULT_REGISTRIES = [
    SkillRegistryConfig(
        registry_id="aris",
        display_name="ARIS",
        git_url="https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git",
        git_ref="main",
        source_skills_path="skills",
        core_skill_ids=[
            "research-lit",
            "arxiv",
            "semantic-scholar",
            "deepxiv",
            "openalex",
            "exa-search",
            "gemini-search",
        ],
        install_mode="copy",
        enabled=True,
    )
]
```

### 2.2 SkillRegistryStatus（运行时状态）

```python
class SkillRegistryStatus:
    registry_id: str
    installed: bool               # 是否已安装到装载目录
    installed_count: int          # 已同步的 skill 数量
    last_sync_at: datetime | None
    remote_commit: str | None     # 远程最新 commit hash
    local_commit: str | None      # 本地 git 工作区 commit hash
    has_update: bool              # 远程是否有更新
    is_dirty: bool                # git 工作区是否有未提交修改
    sync_in_progress: bool        # 是否正在同步中
```

---

## 3. 同步服务（SkillRegistrySyncService）

### 3.1 安装流程（首次）

1. 验证目标目录不存在或为空
2. `git clone --depth 1 <url> <aris-git-sync>/`
3. 遍历 `aris-git-sync/<source_skills_path>/` 下的所有子目录
4. 对每个包含 `SKILL.md` 的目录：
   a. 解析 `SKILL.md` frontmatter（YAML）
   b. 生成 `skill.json`
   c. 复制 `SKILL.md` 到装载目录对应位置
   d. 写入生成的 `skill.json`
5. 持久化安装状态到 `skill_registries.json`
6. 触发 skills discovery 刷新

### 3.2 更新检测流程

```python
def check_update(self, registry_id: str) -> SkillRegistryStatus:
    # 1. 获取远程最新 commit hash
    remote_commit = git_ls_remote(registry.git_url, registry.git_ref)
    # 2. 读取本地 git 工作区 HEAD
    local_commit = git_rev_parse(git_dir)
    # 3. 检查工作区 dirty 状态
    is_dirty = git_status_porcelain(git_dir) != ""
    # 4. 对比 commit hash
    has_update = remote_commit != local_commit
```

### 3.3 更新执行流程

1. **检查 dirty 状态**
   - 干净 → 继续第 2 步
   - dirty → 抛出 `DirtyWorktreeError`，由 API 层返回 409 Conflict，前端弹窗要求用户确认
2. **执行 `git pull`**（在 `aris-git-sync/` 工作区中）
3. **增量同步到装载目录**
   - 对比 git 工作区和装载目录的 skill 列表
   - 新增 skill：生成 skill.json 并复制 SKILL.md
   - 更新 skill：重新生成 skill.json 并复制 SKILL.md（覆盖）
   - 删除 skill：从装载目录移除（如果该 skill 属于 ARIS 且未被用户手动修改）
4. **刷新 discovery**

### 3.4 skill.json 生成规则

从 `SKILL.md` 的 YAML frontmatter 提取：

```yaml
---
name: idea-discovery
description: "Workflow 1: Full idea discovery pipeline..."
argument-hint: [research-direction]
allowed-tools: Bash(*), Read, Write, ...
---
```

映射到 skill.json：

```json
{
  "skill_id": "<目录名（如 idea-discovery）>",
  "label": "<frontmatter.name 或目录名>",
  "description": "<frontmatter.description>",
  "version": "0.0.0",
  "author": "ARIS",
  "inject_mode": "<core_skill_ids 包含 ? 'auto' : 'disabled'>",
  "dependencies": [],
  "settings_fragment": {},
  "mcp_servers": [],
  "hooks": [],
  "allowed_agents": []
}
```

**特殊处理：**
- `skills-codex/` 是嵌套目录（位于 `skills/skills-codex/` 下），同步服务需要递归扫描 `source_skills_path` 下的所有子目录（不仅直接子目录），但跳过不含 `SKILL.md` 的目录
- 目录名中的空格或特殊字符需做 slugify 处理作为 `skill_id`
- `allowed-tools` 和 `argument-hint` 不写入 skill.json（当前 schema 不消费），但可保留在扩展字段中

---

## 4. 后端 API

新增路由 `/skill-registries`。

### 4.1 列出所有注册表

```
GET /skill-registries
```

返回预配置的注册表列表及其安装状态：

```json
{
  "items": [
    {
      "registry_id": "aris",
      "display_name": "ARIS",
      "git_url": "https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git",
      "installed": true,
      "installed_count": 76,
      "has_update": false,
      "is_dirty": false,
      "last_sync_at": "2026-05-06T14:30:00Z"
    }
  ]
}
```

### 4.2 安装注册表

```
POST /skill-registries/{registry_id}/install
```

**成功（200）：** 返回同步的 skill 数量和列表  
**失败（400）：** 已安装  
**失败（500）：** git clone 失败或同步出错

### 4.3 更新注册表

```
POST /skill-registries/{registry_id}/update
Body: { "force": false }
```

- `force=false`（默认）：dirty 时返回 409，前端弹窗确认
- `force=true`：dirty 时强制执行 `git reset --hard && git pull`，不提示

**成功（200）：** 返回变更统计（新增/更新/删除数量）  
**失败（409）：** 工作区 dirty 且未 force  
**失败（500）：** git 或同步出错

### 4.4 获取注册表状态

```
GET /skill-registries/{registry_id}/status
```

返回完整的 `SkillRegistryStatus`。

### 4.5 卸载注册表（预留）

```
POST /skill-registries/{registry_id}/uninstall
```

移除所有属于该注册表的 skills（通过 `.ainrf-managed` 标记文件识别）。

---

## 5. 前端 UI

### 5.1 SettingsPage — SkillRepositorySection 改造

在现有"Import Skill"按钮区域新增注册表操作区：

```
┌─────────────────────────────────────────┐
│  Import Skill          [Install ARIS ▼] │
│                       （已安装/有更新/变灰）│
├─────────────────────────────────────────┤
│  [Skill list]        [Skill detail]     │
│  - arxiv              label: arxiv      │
│  - research-lit       inject_mode: auto │
│  - paper-writing      ...               │
│  ...                                    │
└─────────────────────────────────────────┘
```

**按钮状态逻辑：**

| 状态 | 按钮显示 | 行为 |
|-----|---------|------|
| 未安装 | "安装 ARIS" | 点击调用 POST /install，显示 loading |
| 已安装，无更新 | "ARIS 已安装"（disabled） | 不可点击 |
| 已安装，有更新 | "更新 ARIS" | 点击调用 POST /update |
| 更新中 | 转圈 loading | 禁止重复点击 |

### 5.2 Dirty 确认对话框

当更新 API 返回 409 时，弹出确认对话框：

```
┌────────────────────────────────────────┐
│  更新 ARIS                             │
│                                        │
│  本地工作区有未提交的修改。              │
│  继续更新将丢弃这些修改并从远程拉取最新   │
│  代码。                                │
│                                        │
│  [取消]              [强制更新]        │
└────────────────────────────────────────┘
```

用户点击"强制更新"后，前端调用 POST /update?force=true。

### 5.3 状态指示

在 skill 列表中为 ARIS skills 添加来源标记（小标签 "ARIS"），与手动导入的 skills 区分。

---

## 6. 错误处理

| 场景 | 后端行为 | 前端行为 |
|-----|---------|---------|
| git clone 失败 | 500 + 错误详情 | Toast 错误提示 |
| 已安装再次安装 | 400 "Already installed" | Toast 提示已安装 |
| dirty + 未 force | 409 + dirty files 列表 | 弹出确认对话框 |
| git pull 冲突 | 500 + git stderr | Toast 错误提示 |
| SKILL.md 解析失败 | 跳过该 skill，记录 warning | 同步完成提示中有 warning 计数 |
| 网络超时 | 500 + timeout 详情 | Toast 提示重试 |

---

## 7. 测试策略

### 7.1 单元测试

- `SkillJsonGenerator`：各种 frontmatter 格式（有/无 name、有/无 description、特殊字符）
- `SkillRegistrySyncService.check_update()`：remote/local commit 对比逻辑
- 增量同步算法：新增/更新/删除/未变更的判定

### 7.2 集成测试

- 安装流程：mock git clone，验证装载目录生成正确
- 更新流程：mock git pull，验证增量同步正确
- dirty 场景：验证 409 返回和 force 行为

### 7.3 端到端测试

- 前端按钮状态流转：未安装 → 安装中 → 已安装 → 有更新 → 更新中 → 已安装
- 确认对话框：dirty 时弹出，force 后成功更新

---

## 8. 未来扩展（预留）

- **多注册表支持**：`skill_registries.json` 中可配置多个注册表，前端循环渲染多个安装按钮
- **版本锁定**：支持 `git_ref` 指向特定 tag/commit，而非总是 main
- **自定义核心子集**：用户在安装后可通过 UI 调整哪些 skills 启用
- **社区注册表**：提供注册表市场页面，展示多个社区技能仓库

---

## 附录：方案对比（设计阶段已讨论）

| 维度 | 本方案（生成 skill.json） | 替代方案（修改 Loader） |
|---|---|---|
| 对现有代码影响 | 小 — 新增模块，不改动 loader | 中 — 需修改 loader、discovery |
| 风险 | 低 | 中 — loader 是核心组件 |
| 可维护性 | 高 — 装载目录自描述 | 中 — 运行时解析有复杂度 |
| 性能 | 同步时一次性生成，无运行时开销 | 每次 discovery 都解析 frontmatter |
| 核心子集确定 | 配置化，可控 | 静态分析，可能漏/错 |

本方案被选中，因为它在不改动现有核心组件的前提下实现了需求，且为后续扩展预留了清晰的路径。
