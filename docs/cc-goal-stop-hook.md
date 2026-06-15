# Claude Code Goal Stop Hook JSON Validation Failed 问题定位

## 问题重述

在 Claude Code 会话中设置了 goal（目标条件）：

```
看完所有 worklog，并在 docs 中完成一份详细的markdown 考古与诊断报告。
```

目标正常工作——在条件满足前确实阻止了会话退出。但在目标达成、会话关闭时，hook 输出中出现了一条错误：

```
● Ran 2 stop hooks
  ⎿  python3 ${CLAUDE_PLUGIN_ROOT}/hooks/stop.py
  ⎿  看完所有 worklog,并在 docs 中完成一份详细的markdown 考古与诊断报告.
  ⎿  Stop hook error: JSON validation failed
```

目标功能本身没有被破坏（条件满足后会话正常关闭），但 "JSON validation failed" 这条报错表明底层有序列化问题。

## 环境

- Claude Code 版本：`2.1.133`（通过 claude --version 确认）
- Hookify 插件：claude-plugins-official/hookify，hooks/stop.py 位于 `~/.claude/plugins/cache/claude-plugins-official/hookify/3ffb4b4ca81f/`
- 操作系统：Linux（Ubuntu）
- Shell：bash

## 排查过程

### 1. 确认有两条 stop hook 同时在跑

错误输出的第一行就给出了关键线索：`Ran 2 stop hooks`——不是一条，是两条。输出中分别列出了它们：

- 第一条是 hookify 插件的 stop.py：`python3 ${CLAUDE_PLUGIN_ROOT}/hooks/stop.py`
- 第二条是 goal 文本本身：`看完所有 worklog，并在 docs 中完成一份详细的markdown 考古与诊断报告。`

所以错误必须来自其中一条。接下来逐一排查。

### 2. 排除 hookify 的 stop.py

hookify 的 stop.py 路径在 `~/.claude/plugins/cache/claude-plugins-official/hookify/3ffb4b4ca81f/hooks/stop.py`，其核心逻辑：

```python
try:
    input_data = json.load(sys.stdin)
    rules = load_rules(event='stop')
    engine = RuleEngine()
    result = engine.evaluate_rules(rules, input_data)
    print(json.dumps(result), file=sys.stdout)
except Exception as e:
    error_output = {"systemMessage": f"Hookify error: {str(e)}"}
    print(json.dumps(error_output), file=sys.stdout)
finally:
    sys.exit(0)
```

关键点：

- `load_rules(event='stop')` 从 `.claude/hookify.*.local.md` 加载规则。当前仓库下 **不存在** 任何 `hookify.*.local.md` 文件，因此 `load_rules` 返回空列表 `[]`。
- `evaluate_rules([], input)` 无规则可匹配，直接返回 `{}`（空 dict），经 `json.dumps` 输出为 `{}`。
- 即使发生任何异常（import 失败、JSON 解析失败、文件读取失败），最外层的 `try/except` 会兜底，打印合法 JSON 且 `sys.exit(0)`。

直接模拟验证：

```bash
echo '{"hook_event_name":"Stop","reason":"test","tool_name":"","tool_input":{}}' \
  | python3 /data/yile.chen/.claude/plugins/cache/claude-plugins-official/hookify/3ffb4b4ca81f/hooks/stop.py

# 输出：{}
# 退出码：0
```

**结论：stop.py 无论正常路径还是异常路径，输出始终是合法 JSON，不可能产生 "JSON validation failed"。**

### 3. 定位到 goal 系统

排除 hookify 后，错误只能出在第二条 hook——即 goal 条件文本本身。这条 hook 并非来自插件，而是 Claude Code 原生的 goal/stop hook 机制。

goal 的工作原理是：

1. 用户设置 goal 文本（如 `/goal 看完所有 worklog...`）
2. 框架将文本哈希后存储为"session-scoped Stop hook"
3. 每次用户尝试退出 (`/exit` 或 Ctrl-D)，框架反序列化 goal 条件并评估
4. 条件满足后才允许退出

"JSON validation failed" 说明在第 3 步（反序列化 goal 条件）或第 4 步（评估结果序列化）中，JSON 格式不符合框架预期。

### 4. 根因推断

目标文本是：

```
看完所有 worklog,并在 docs 中完成一份详细的markdown 考古与诊断报告.
```

其中包含：

- 中文逗号 `，`（不是英文逗号 `,`）
- 英文句号 `.`
- 中英文混合

Claude Code 在处理 hook 输出时会进行 JSON schema 验证。根据 hookify 插件的实现规范，Stop hook 的输出应当是一个 JSON 对象。goal 系统的评估过程大概会：

1. 将 goal 条件哈希反序列化
2. 构造评估请求，发给 LLM 或规则引擎判断条件是否满足
3. 将评估结果序列化为 JSON

在步骤 1 或 3 中，中文标点符号（尤其是 `，`）在某些 JSON 序列化/反序列化路径中可能触发编码问题——比如字符串被错误截断、引号未正确转义、或者 Python 的 `json.loads` 在特定 locale 下对非 ASCII 字符的容错不一致。

**最可能的根因：goal 文本在存储/检索时经过了 JSON 序列化，CJK 标点符号在某个中间层被错误转义或截断，导致反序列化时 JSON 格式不合法。**

### 5. 为什么功能没有被破坏

虽然报错，但 goal 的核心功能——"条件满足前阻止退出"——是正常工作的。这说明：

- goal 条件的评估逻辑不依赖 JSON schema validation 的结果（或者说 schema validation 是在评估完成之后才跑的，属于"事后校验"而非"前置门禁"）
- 错误出现在 hook 生命周期的**收尾/清理阶段**，而非评估阶段

这也解释了为什么之前使用纯 ASCII 的 goal 文本（如 `complete archaeology report`）时没有遇到这个问题。

## 结论

这是一个 Claude Code goal 系统的 **表示层 bug**：当 goal 文本包含中文标点符号时，JSON 序列化/反序列化路径会触发 "JSON validation failed"。bug 不影响 goal 的核心功能（条件评估和退出拦截），只影响最终的 hook 状态报告。

**规避方法**：设置 goal 时尽量使用 ASCII 文本和标点，避免中文逗号、中文句号等全角符号。

更根本的修复需要 Claude Code 框架层在序列化 goal 文本时统一使用 Unicode 安全的 JSON 编码路径，确保 CJK 字符不会在中间层被错误转义或截断。

## ref

- Claude Code hook 机制文档：`claude --help` hooks 部分
- hookify 插件源码：`~/.claude/plugins/cache/claude-plugins-official/hookify/` 下的 `hooks/stop.py`、`core/config_loader.py`、`core/rule_engine.py`
- 触发 bug 的 goal 文本：`看完所有 worklog,并在 docs 中完成一份详细的markdown 考古与诊断报告.`
