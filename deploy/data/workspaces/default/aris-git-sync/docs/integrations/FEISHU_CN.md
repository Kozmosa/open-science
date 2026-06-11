# 飞书 / Lark 集成（可选）

> 🇬🇧 English: [FEISHU.md](FEISHU.md)
> 手机收通知 + 在飞书里审批。基于 webhook（推送）和 [feishu-claude-code](https://github.com/joewongjc/feishu-claude-code) 桥接（交互）。

实验跑完、review 出分、checkpoint 等你审批——手机收飞书通知，不用守在终端前。

| 仅推送（群聊卡片） | 双向交互（私聊） |
|:-:|:-:|
| <img src="../../assets/feishu_push.png" width="450" /> | <img src="../../assets/feishu_interactive.jpg" width="450" /> |

## 三种模式，按需选择

| 模式 | 效果 | 你需要 |
|------|------|--------|
| **关闭**（默认） | 什么都不做，纯 CLI 不变 | 什么都不用 |
| **仅推送** | 关键事件发 webhook 通知，手机收推送，不能回复 | 飞书机器人 webhook URL |
| **双向交互** | 全双工：在飞书里审批/拒绝 idea、回复 checkpoint | [feishu-claude-code](https://github.com/joewongjc/feishu-claude-code) 运行中 |

没有 `~/.claude/feishu.json` 文件时，所有 skill 行为完全不变——零开销，零副作用。

---

## 仅推送模式（5 分钟配好）

群通知，彩色富文本卡片——实验跑完、review 出分、流水线结束，手机收推送就行，不需要回复。

### 第 1 步：创建飞书群机器人

1. 打开你的飞书群（或新建一个测试群）
2. 群设置 → 群机器人 → 添加机器人 → **自定义机器人**
3. 起个名字（如 `ARIS Notifications`），复制 **Webhook 地址**
4. 安全设置：添加自定义关键词 `ARIS`（所有通知都包含这个词），或不设限制

### 第 2 步：创建配置文件

```bash
cat > ~/.claude/feishu.json << 'EOF'
{
  "mode": "push",
  "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_WEBHOOK_ID"
}
EOF
```

### 第 3 步：测试

```bash
curl -s -X POST "YOUR_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "msg_type": "interactive",
    "card": {
      "header": {"title": {"tag": "plain_text", "content": "🧪 ARIS Test"}, "template": "blue"},
      "elements": [{"tag": "markdown", "content": "Push mode working! 🎉"}]
    }
  }'
```

群里应该出现一张蓝色卡片。之后 skill 会在关键事件自动推送富文本卡片：

| 事件 | 卡片颜色 | 内容 |
|------|---------|------|
| Review 出分 ≥ 6 | 🟢 绿色 | 分数、结论、主要 weakness |
| Review 出分 < 6 | 🟠 橙色 | 分数、结论、待修复项 |
| 实验完成 | 🟢 绿色 | 结果对比表、delta vs baseline |
| Checkpoint 等待 | 🟡 黄色 | 问题、选项、上下文 |
| 出错 | 🔴 红色 | 错误信息、建议修复方案 |
| 流水线结束 | 🟣 紫色 | 分数进展表、最终交付物 |

---

## 双向交互模式（15 分钟）

推送模式的全部功能 **加上** 通过飞书私聊与 Claude Code 双向对话。审批/拒绝 idea、回复 checkpoint、给自定义指令——全在手机上完成。

**工作方式**：推送卡片发到**群里**（所有人看到状态），交互对话发到**私聊**（你回复，Claude Code 执行）。

### 第 1 步：先完成上面的推送模式配置（两种模式并存）

### 第 2 步：在[飞书开放平台](https://open.feishu.cn/app)创建应用

1. 点击 **创建企业自建应用** → 填名称（如 `ARIS Claude Bot`）→ 创建
2. 左侧菜单 → **添加应用能力** → 勾选 **机器人**
3. 左侧 → **权限管理** → 搜索并开通以下 5 个权限：

| 权限 | Scope | 作用 |
|------|-------|------|
| `im:message` | 获取与发送单聊、群组消息 | 核心消息能力 |
| `im:message:send_as_bot` | 以应用身份发消息 | 机器人回复 |
| `im:message.group_at_msg:readonly` | 接收群聊中@机器人消息 | 群消息 |
| `im:message.p2p_msg:readonly` | **读取用户发给机器人的单聊消息** | ⚠️ **极易遗漏！** 不开这个权限，机器人能连上但永远收不到你的私聊消息 |
| `im:resource` | 获取与上传图片或文件资源 | 图片/文件 |

4. 左侧 → **事件与回调** → 选择 **长连接** 模式 → 添加事件：`im.message.receive_v1` → 保存

> ⚠️ **注意**：长连接页面可能显示"未检测到应用连接信息"——这是正常的。需要先启动桥接服务（第 3 步），再回来保存。

5. 左侧 → **版本管理与发布** → **创建版本** → 填写描述 → **提交审核**

> 个人/测试企业通常秒过审核。

### 第 3 步：部署桥接服务

```bash
git clone https://github.com/joewongjc/feishu-claude-code.git
cd feishu-claude-code
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 配置
cp .env.example .env
```

编辑 `.env`：

```bash
FEISHU_APP_ID=cli_your_app_id          # 凭证与基础信息页面获取
FEISHU_APP_SECRET=your_app_secret      # 凭证与基础信息页面获取
DEFAULT_MODEL=claude-opus-4-6          # ⚠️ 默认是 sonnet——改成 opus 效果好很多
DEFAULT_CWD=/path/to/your/project      # Claude Code 的工作目录
PERMISSION_MODE=bypassPermissions      # 或 "default"（需手动确认敏感操作）
```

> ⚠️ **模型很重要**：默认的 `claude-sonnet-4-6` 能用但可能无法理解复杂项目上下文。实测 `claude-opus-4-6` 首次即正确识别了 18 个 ARIS skills，而 sonnet 反复失败。

启动桥接：

```bash
python main.py
# 预期输出：
# ✅ 连接飞书 WebSocket 长连接（自动重连）...
# [Lark] connected to wss://msg-frontier.feishu.cn/ws/v2?...
```

长期运行丢 screen 里：

```bash
screen -dmS feishu-bridge bash -c 'cd /path/to/feishu-claude-code && source .venv/bin/activate && python main.py'
```

### 第 4 步：保存事件配置

回到飞书开放平台 → 事件与回调 → 长连接应该显示"已检测到连接"→ **保存**。

> 如果在桥接启动前就发布了应用版本，可能需要再创建一个新版本（如 1.0.1）并重新发布。

### 第 5 步：测试私聊

1. 在飞书里搜索机器人名称，打开私聊
2. 发送：`你好`
3. 机器人应通过 Claude Code 回复

**如果机器人不回复**：发 `/new` 重置 session，再试一次。常见问题：

| 症状 | 原因 | 解决 |
|------|------|------|
| 机器人连上了但收不到消息 | 缺少 `im:message.p2p_msg:readonly` 权限 | 开通权限 → 创建新版本 → 发布 |
| 机器人回复但不认识你的项目 | `DEFAULT_CWD` 指向错误目录 | 修改 `.env` → 重启桥接 |
| 机器人回复但不够聪明 | 使用的是 `claude-sonnet-4-6` | 改为 `claude-opus-4-6` → 重启桥接 |
| 旧 session 上下文过时 | 修改配置前的 session 被缓存 | 在聊天中发 `/new` 开始新 session |
| 保存事件时"未检测到连接" | 桥接服务还没启动 | 先启动桥接，再保存事件配置 |

### 第 6 步：更新 ARIS 配置

```bash
cat > ~/.claude/feishu.json << 'EOF'
{
  "mode": "interactive",
  "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_WEBHOOK_ID",
  "interactive": {
    "bridge_url": "http://localhost:5000",
    "timeout_seconds": 300
  }
}
EOF
```

现在 skill 会：
- **推送**富文本卡片到群里（状态通知，所有人可见）
- **私聊**你做决策（checkpoint 审批、继续/停止、自定义指令）

---

## 哪些 skill 会发通知？

| Skill | 事件 | 推送模式 | 交互模式 |
|-------|------|----------|----------|
| `/auto-review-loop` | 每轮出分、循环结束 | 分数 + 结论 | + 等你决定继续/停止 |
| `/auto-paper-improvement-loop` | 每轮出分、全部完成 | 分数进展表 | 分数进展表 |
| `/run-experiment` | 实验已部署 | GPU 分配 + 预计时间 | GPU 分配 + 预计时间 |
| `/vast-gpu` | 实例租用/销毁 | 实例 ID + 成本 | 实例 ID + 成本 |
| `/monitor-experiment` | 结果已收集 | 结果对比表 | 结果对比表 |
| `/idea-discovery` | 阶段切换、最终报告 | 各阶段摘要 | + 审批/拒绝 |
| `/research-pipeline` | 阶段切换、流水线结束 | 阶段摘要 | + 审批/拒绝 |

## 其他 IM 平台

推送模式的 webhook 模式适用于任何支持 incoming webhook 的服务（Slack、Discord、钉钉、企业微信）。只需改 `webhook_url` 和卡片格式。双向交互可参考：

- [cc-connect](https://github.com/chenhg5/cc-connect) —— 多平台桥接
- [clawdbot-feishu](https://github.com/m1heng/clawdbot-feishu) —— 飞书 Claude 机器人替代
- [lark-openapi-mcp](https://github.com/larksuite/lark-openapi-mcp) —— 飞书官方 MCP server

## 相关 skill

- [`/feishu-notify`](../../skills/feishu-notify/SKILL.md) —— 通知 SKILL（推送卡片）
- 所有长跑 skill（review loop、实验、pipeline）在配置后自动发卡片
