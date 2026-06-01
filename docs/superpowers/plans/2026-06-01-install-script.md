# AINRF Install Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重写 `scripts/install.sh`，实现 rustup-init 风格的自包含安装脚本，自动检测并安装 uv 和 fnm+Node LTS，同步项目依赖，并可选启动服务。

**Architecture:** 单文件 Bash 脚本，分阶段执行：环境检测 → 工具安装（交互式/自动）→ 依赖同步 → 服务启动。支持 `-y` 非交互模式和 `--no-start` 标志。

**Tech Stack:** Bash, curl, uv, fnm, Node.js LTS, npm

---

## File Structure

| 文件 | 职责 |
|------|------|
| `scripts/install.sh` | 主安装脚本（完全重写现有文件） |
| `tests/test_install_script.py` | 安装脚本的单元测试（检测逻辑、版本解析） |

---

## Task 1: 重写 scripts/install.sh — 核心框架与参数解析

**Files:**
- Modify: `scripts/install.sh`（完全重写）

- [ ] **Step 1: 编写脚本头部和参数解析**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "${BLUE}[STEP]${NC}  $*"; }

# ── Defaults ─────────────────────────────────────────────────────────
AUTO_YES=false
NO_START=false

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [OPTIONS]

Install AINRF development environment automatically.
Detects and installs uv, fnm, and Node.js LTS if missing.

Options:
  -y, --yes        Non-interactive mode: auto-install all missing tools
  --no-start       Do not start AINRF services after installation
  -h, --help       Show this help message

Examples:
  scripts/install.sh              # Interactive installation
  scripts/install.sh -y           # Auto-install everything
  scripts/install.sh -y --no-start # Auto-install but don't start services
EOF
}

while (($# > 0)); do
  case "$1" in
    -y|--yes)
      AUTO_YES=true
      ;;
    --no-start)
      NO_START=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      error "Unknown option: $1"
      usage >&2
      exit 1
      ;;
  esac
  shift
done
```

- [ ] **Step 2: 添加帮助函数（重试下载、检测命令）**

在参数解析之后添加：

```bash
# ── Helpers ──────────────────────────────────────────────────────────

download_with_retry() {
  local url="$1"
  local output="${2:-/dev/stdout}"
  local max_retries=3
  local attempt=1

  while [[ $attempt -le $max_retries ]]; do
    if curl -fsSL "$url" -o "$output" 2>/dev/null; then
      return 0
    fi
    warn "Download failed (attempt $attempt/$max_retries), retrying in 2s..."
    sleep 2
    ((attempt++)) || true
  done

  error "Failed to download after $max_retries attempts: $url"
  return 1
}

check_command() {
  command -v "$1" &>/dev/null
}
```

- [ ] **Step 3: 验证脚本可执行**

Run: `bash -n scripts/install.sh`
Expected: 无输出（语法检查通过）

- [ ] **Step 4: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: install script core framework and argument parsing"
```

---

## Task 2: 添加操作系统和 Python 检测

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: 添加 OS 和架构检测**

```bash
# ── OS / Architecture Detection ──────────────────────────────────────

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)
    OS_TYPE="linux"
    ;;
  Darwin)
    OS_TYPE="macos"
    ;;
  *)
    error "Unsupported operating system: $OS"
    error "AINRF install script only supports Linux and macOS."
    exit 1
    ;;
esac

case "$ARCH" in
  x86_64)
    ARCH_TYPE="x86_64"
    ;;
  aarch64|arm64)
    ARCH_TYPE="aarch64"
    ;;
  *)
    error "Unsupported architecture: $ARCH"
    error "Supported architectures: x86_64, aarch64/arm64"
    exit 1
    ;;
esac

info "Detected platform: $OS_TYPE ($ARCH_TYPE)"
```

- [ ] **Step 2: 添加 Python 版本检测**

```bash
# ── Python Detection ─────────────────────────────────────────────────

find_python() {
  local py_cmd
  for py_cmd in python3 python; do
    if check_command "$py_cmd"; then
      echo "$py_cmd"
      return 0
    fi
  done
  return 1
}

check_python_version() {
  local py_cmd="$1"
  local version
  version="$($py_cmd --version 2>&1 | awk '{print $2}')"
  local major minor
  major="$(echo "$version" | cut -d. -f1)"
  minor="$(echo "$version" | cut -d. -f2)"

  if [[ "$major" -gt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -ge 13 ]]; }; then
    echo "$version"
    return 0
  fi
  return 1
}

step "Checking Python ..."
PYTHON_CMD=""
if ! PYTHON_CMD="$(find_python)"; then
  error "Python is not installed or not on PATH."
  error "AINRF requires Python 3.13 or later."
  error "Please install Python 3.13+ and re-run this script."
  exit 1
fi

PYTHON_VERSION=""
if ! PYTHON_VERSION="$(check_python_version "$PYTHON_CMD")"; then
  local current_version
  current_version="$($PYTHON_CMD --version 2>&1 | awk '{print $2}')"
  error "Python $current_version is too old."
  error "AINRF requires Python 3.13 or later."
  error "Please upgrade Python and re-run this script."
  exit 1
fi

info "Found Python $PYTHON_VERSION ($PYTHON_CMD)"
```

- [ ] **Step 3: 验证脚本可执行**

Run: `bash -n scripts/install.sh`
Expected: 无输出

- [ ] **Step 4: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: add OS/arch and Python version detection to install script"
```

---

## Task 3: 添加 uv 检测与自动安装

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: 添加交互式提示函数**

```bash
# ── Interactive Prompts ──────────────────────────────────────────────

prompt_choice() {
  local message="$1"
  local option1="$2"
  local option2="$3"
  local option3="$4"
  local choice

  if [[ "$AUTO_YES" == true ]]; then
    echo "3"
    return 0
  fi

  echo ""
  error "$message"
  echo ""
  echo "Options:"
  echo "  1) $option1"
  echo "  2) $option2"
  echo "  3) $option3"
  echo ""

  while true; do
    read -rp "Enter your choice [1/2/3]: " choice
    case "$choice" in
      1|2|3)
        echo "$choice"
        return 0
        ;;
      *)
        warn "Invalid choice. Please enter 1, 2, or 3."
        ;;
    esac
  done
}
```

- [ ] **Step 2: 添加 uv 安装函数**

```bash
# ── UV Installation ──────────────────────────────────────────────────

install_uv() {
  step "Installing uv ..."

  local install_script
  install_script="$(mktemp)"
  trap 'rm -f "$install_script"' RETURN

  if ! download_with_retry "https://astral.sh/uv/install.sh" "$install_script"; then
    error "Failed to download uv installer."
    return 1
  fi

  if ! bash "$install_script"; then
    error "uv installation failed."
    return 1
  fi

  # Refresh PATH to include uv
  export PATH="$HOME/.local/bin:$PATH"

  if ! check_command uv; then
    error "uv was installed but is not on PATH."
    error "Please restart your shell or run: export PATH=\"$HOME/.local/bin:\$PATH\""
    return 1
  fi

  info "uv installed successfully: $(uv --version)"
}
```

- [ ] **Step 3: 添加 uv 检测与处理逻辑**

```bash
# ── UV Detection & Installation ──────────────────────────────────────

step "Checking uv ..."
UV_INSTALLED=false

while true; do
  if check_command uv; then
    UV_INSTALLED=true
    info "Found uv: $(uv --version)"
    break
  fi

  local choice
  choice="$(prompt_choice \
    "uv is not installed or not on PATH." \
    "Exit and install uv manually (https://docs.astral.sh/uv/getting-started/installation/)" \
    "Retry detection after manual installation" \
    "Let the script install uv automatically")"

  case "$choice" in
    1)
      error "Exiting. Please install uv manually and re-run."
      exit 1
      ;;
    2)
      # Retry loop will check again
      continue
      ;;
    3)
      if ! install_uv; then
        error "Failed to install uv automatically."
        error "Please install uv manually and re-run."
        exit 1
      fi
      break
      ;;
  esac
done
```

- [ ] **Step 4: 验证脚本可执行**

Run: `bash -n scripts/install.sh`
Expected: 无输出

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: add uv detection and auto-installation to install script"
```

---

## Task 4: 添加 Node.js/npm 检测与 fnm 自动安装

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: 添加 Node.js 版本检测函数**

```bash
# ── Node.js Detection ────────────────────────────────────────────────

check_node_version() {
  local node_cmd="$1"
  local version
  version="$($node_cmd --version 2>/dev/null | sed 's/^v//')"
  local major
  major="$(echo "$version" | cut -d. -f1)"

  if [[ -n "$major" ]] && [[ "$major" -ge 22 ]]; then
    echo "$version"
    return 0
  fi
  return 1
}
```

- [ ] **Step 2: 添加 fnm + Node LTS 安装函数**

```bash
# ── fnm + Node LTS Installation ──────────────────────────────────────

install_fnm_and_node() {
  step "Installing fnm (Fast Node Manager) ..."

  local install_script
  install_script="$(mktemp)"
  trap 'rm -f "$install_script"' RETURN

  if ! download_with_retry "https://fnm.vercel.app/install" "$install_script"; then
    error "Failed to download fnm installer."
    return 1
  fi

  # Install fnm to ~/.local/share/fnm
  if ! bash "$install_script" --skip-shell; then
    error "fnm installation failed."
    return 1
  fi

  # Set up fnm environment
  export PATH="$HOME/.local/share/fnm:$PATH"
  eval "$(fnm env --shell bash)"

  if ! check_command fnm; then
    error "fnm was installed but is not on PATH."
    return 1
  fi

  info "fnm installed: $(fnm --version)"

  step "Installing Node.js LTS ..."

  if ! fnm install --lts; then
    error "Failed to install Node.js LTS."
    return 1
  fi

  if ! fnm use --lts; then
    error "Failed to activate Node.js LTS."
    return 1
  fi

  if ! check_command node; then
    error "Node.js was installed but is not on PATH."
    return 1
  fi

  local node_version
  node_version="$(node --version | sed 's/^v//')"
  info "Node.js LTS installed: v$node_version"

  if ! check_command npm; then
    error "npm is not available after Node.js installation."
    return 1
  fi

  info "npm installed: $(npm --version)"
}
```

- [ ] **Step 3: 添加 Node.js/npm 检测与处理逻辑**

```bash
# ── Node.js/npm Detection & Installation ─────────────────────────────

step "Checking Node.js and npm ..."
NODE_INSTALLED=false

while true; do
  if check_command node; then
    local node_version
    if node_version="$(check_node_version node)"; then
      if check_command npm; then
        NODE_INSTALLED=true
        info "Found Node.js v$node_version and npm $(npm --version)"
        break
      fi
    fi
  fi

  local choice
  choice="$(prompt_choice \
    "Node.js 22+ LTS and npm are required but not found." \
    "Exit and install Node.js manually (https://nodejs.org/)" \
    "Retry detection after manual installation" \
    "Let the script install fnm and Node.js LTS automatically")"

  case "$choice" in
    1)
      error "Exiting. Please install Node.js 22+ LTS manually and re-run."
      exit 1
      ;;
    2)
      continue
      ;;
    3)
      if ! install_fnm_and_node; then
        error "Failed to install Node.js automatically."
        error "Please install Node.js 22+ LTS manually and re-run."
        exit 1
      fi
      break
      ;;
  esac
done
```

- [ ] **Step 4: 验证脚本可执行**

Run: `bash -n scripts/install.sh`
Expected: 无输出

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: add Node.js/npm detection and fnm auto-installation"
```

---

## Task 5: 添加项目依赖同步和服务启动

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: 添加依赖同步逻辑**

```bash
# ── Project Dependencies ─────────────────────────────────────────────

step "Installing Python dependencies (uv sync) ..."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
(cd "$REPO_ROOT" && uv sync)
info "Python dependencies installed."

step "Installing frontend dependencies (npm ci) ..."
(cd "$REPO_ROOT/frontend" && npm ci)
info "Frontend dependencies installed."
```

- [ ] **Step 2: 添加服务启动询问逻辑**

```bash
# ── Service Startup ──────────────────────────────────────────────────

if [[ "$NO_START" == true ]]; then
  echo ""
  info "Installation complete!"
  info "To start AINRF services, run: scripts/webui.sh"
  exit 0
fi

if [[ "$AUTO_YES" == true ]]; then
  step "Starting AINRF services ..."
  exec "$REPO_ROOT/scripts/webui.sh"
fi

echo ""
info "Installation complete!"
echo ""

while true; do
  read -rp "Start AINRF services now? [Y/n]: " start_choice
  start_choice="${start_choice:-Y}"
  case "${start_choice,,}" in
    y|yes)
      step "Starting AINRF services ..."
      exec "$REPO_ROOT/scripts/webui.sh"
      ;;
    n|no)
      info "Skipped. To start services later, run: scripts/webui.sh"
      exit 0
      ;;
    *)
      warn "Please answer Y or n."
      ;;
  esac
done
```

- [ ] **Step 3: 验证完整脚本可执行**

Run: `bash -n scripts/install.sh`
Expected: 无输出

- [ ] **Step 4: 给脚本添加执行权限**

Run: `chmod +x scripts/install.sh`

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: add dependency sync and service startup to install script"
```

---

## Task 6: 添加安装脚本测试

**Files:**
- Create: `tests/test_install_script.py`

- [ ] **Step 1: 编写测试文件**

```python
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "install.sh"


def test_install_script_exists() -> None:
    assert SCRIPT_PATH.exists(), f"install.sh not found at {SCRIPT_PATH}"


def test_install_script_is_executable() -> None:
    assert SCRIPT_PATH.stat().st_mode & 0o111, "install.sh is not executable"


def test_install_script_help() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--yes" in result.stdout
    assert "--no-start" in result.stdout


def test_install_script_syntax_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"


def test_install_script_unknown_flag() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--unknown"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Unknown option" in result.stderr
```

- [ ] **Step 2: 运行测试**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/test_install_script.py -v`
Expected: 所有 5 个测试通过

- [ ] **Step 3: Commit**

```bash
git add tests/test_install_script.py
git commit -m "test: add install script unit tests"
```

---

## Task 7: 最终验证与清理

**Files:**
- Modify: `scripts/install.sh`（如有需要）

- [ ] **Step 1: 运行全部测试**

Run: `uv run pytest tests/ -v`
Expected: 所有测试通过（包括新添加的 install script 测试）

- [ ] **Step 2: 运行 lint 检查**

Run: `uv run ruff check src tests`
Expected: 无错误

- [ ] **Step 3: 运行类型检查**

Run: `uv run ty check`
Expected: 无错误

- [ ] **Step 4: 最终 review 脚本内容**

确认 `scripts/install.sh` 包含：
- [ ] 参数解析（`-y`, `--no-start`, `--help`）
- [ ] OS/架构检测（Linux/macOS, x86_64/aarch64）
- [ ] Python >= 3.13 检测
- [ ] uv 检测 + 交互式提示 + 自动安装
- [ ] Node.js >= 22 + npm 检测 + 交互式提示 + fnm 自动安装
- [ ] `uv sync` 和 `npm ci` 自动执行
- [ ] 交互式询问启动服务（或 `-y` 自动启动 / `--no-start` 跳过）
- [ ] 彩色输出和错误处理
- [ ] 下载重试机制

- [ ] **Step 5: Commit（如有修改）**

```bash
git add scripts/install.sh
git commit -m "chore: final polish on install script"
```

---

## Self-Review Checklist

### Spec Coverage
- [x] 单文件 Bash 脚本 — Task 1-5
- [x] 参数解析（`--help`, `-y`, `--no-start`）— Task 1
- [x] OS/架构检测 — Task 2
- [x] Python >= 3.13 检测 — Task 2
- [x] uv 检测 + 交互式提示 + 自动安装 — Task 3
- [x] Node.js/npm 检测 + fnm 自动安装 — Task 4
- [x] `uv sync` + `npm ci` — Task 5
- [x] 服务启动询问 — Task 5
- [x] 彩色输出和错误处理 — 贯穿所有 Task
- [x] 下载重试 — Task 3, 4
- [x] 测试 — Task 6

### Placeholder Scan
- [x] 无 "TBD"/"TODO"
- [x] 所有代码块包含完整代码
- [x] 所有命令包含预期输出
- [x] 无 "similar to Task N" 引用

### Type Consistency
- [x] 函数名一致：`check_command`, `check_python_version`, `check_node_version`
- [x] 变量名一致：`AUTO_YES`, `NO_START`, `REPO_ROOT`
- [x] 颜色变量一致：`RED`, `GREEN`, `YELLOW`, `BLUE`, `NC`
