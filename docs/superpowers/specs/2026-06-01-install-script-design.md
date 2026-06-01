# AINRF Self-Contained Install Script Design

## 目标

提供一个模仿 rustup-init 风格的单文件 Bash 安装脚本，让新开发者和服务器部署都能一键完成环境配置和启动。

## 脚本位置

- `scripts/install.sh`
- 调用方式：`./scripts/install.sh` 或 `curl -sSL ... | bash`

## CLI 参数

| 参数 | 说明 |
|------|------|
| `--help` / `-h` | 显示帮助信息 |
| `-y` | 非交互模式：自动安装所有缺失工具并启动服务 |
| `--no-start` | 安装完成后不启动服务（可与 `-y` 联用） |

## 执行流程

```
1. 解析命令行参数
2. 检测操作系统（仅支持 Linux/macOS，Windows 报错退出）
3. 检测 Python >= 3.13（不满足则报错退出，不自动安装 Python）
4. 检测 uv
   └─ 不存在 → 交互式询问（退出 / 自行安装后重试 / 脚本自动安装）
5. 检测 node >= 22 LTS 且 npm 存在
   └─ 不存在 → 交互式询问（退出 / 自行安装后重试 / 脚本自动安装 fnm + Node LTS）
6. 运行 uv sync（安装 Python 依赖）
7. 运行 npm ci（安装前端依赖）
8. 交互式询问是否启动 AINRF 服务
   └─ 是 → 执行 scripts/webui.sh
   └─ 否 → 打印后续命令提示
```

## 各阶段详细设计

### 阶段 1：前置检测

- 检测 `python3` 或 `python`，验证版本 `>= 3.13`
- 检测操作系统（`uname -s`）和架构（`uname -m`）
- 仅支持 Linux 和 macOS，x86_64 和 aarch64

### 阶段 2：uv 安装

- 使用官方安装脚本：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- 安装后刷新 PATH：`export PATH="$HOME/.local/bin:$PATH"`
- 验证 `uv --version` 成功

### 阶段 3：fnm + Node LTS 安装

- 安装 fnm：`curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell`
- 激活 fnm：`eval "$(fnm env --shell bash)"`
- 安装并使用 Node LTS：`fnm install --lts && fnm use --lts`
- 验证 `node --version >= 22` 且 `npm --version` 成功

### 阶段 4：项目依赖同步

- `uv sync` — 安装 Python 依赖（使用 lockfile）
- `cd frontend && npm ci` — 安装前端依赖（使用 package-lock.json）

### 阶段 5：服务启动

- 交互式询问："是否现在启动 AINRF 服务？"
- 是 → 执行 `scripts/webui.sh`
- 否 → 打印提示：`Run "scripts/webui.sh" to start the AINRF backend and frontend.`

## 交互式提示格式

当检测到缺失工具时，输出：

```
[ERROR] uv is not installed or not on PATH.

AINRF requires uv to manage Python dependencies.

Options:
  1) Exit and install uv manually (https://docs.astral.sh/uv/getting-started/installation/)
  2) Retry detection after manual installation
  3) Let the script install uv automatically

Enter your choice [1/2/3]:
```

## 错误处理

- 每个阶段失败都立即退出，返回非零状态码
- 使用彩色输出：`[INFO]` 绿色，`[WARN]` 黄色，`[ERROR]` 红色
- 网络下载失败重试 3 次，每次间隔 2 秒
- 安装过程中使用临时目录，失败时清理

## 非交互模式

`-y` 标志下：
- 自动选择选项 3（脚本自动安装）所有缺失工具
- 自动回答"是"启动服务
- `--no-start` 可覆盖最后一步，不启动服务

## 与现有脚本的协作

- 安装完成后，用户通过 `scripts/webui.sh` 启动服务
- 不修改现有 `scripts/install.sh` 的行为，而是完全重写它
- 保持与 `scripts/webui.sh`、`scripts/build.sh` 等脚本的风格一致
