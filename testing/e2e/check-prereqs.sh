#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# AINRF E2E Prerequisites Check
# ═══════════════════════════════════════════════════════════════
# Verifies that all tools needed for agent-driven E2E testing
# are available and functional.
#
# Usage: testing/e2e/check-prereqs.sh
#
# Exit code 0 = all good, non-zero = missing dependencies.
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

PASS=0
FAIL=0
WARN=0

green()  { printf "\033[32m✓ %s\033[0m\n" "$1"; PASS=$((PASS + 1)); }
red()    { printf "\033[31m✗ %s\033[0m\n" "$1"; FAIL=$((FAIL + 1)); }
yellow() { printf "\033[33m⚠ %s\033[0m\n" "$1"; WARN=$((WARN + 1)); }
header() { printf "\n── %s ──\n" "$1"; }

# ── Docker ──────────────────────────────────────────────────────
header "Docker"

if command -v docker &>/dev/null; then
    green "docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
    if docker info &>/dev/null 2>&1; then
        green "Docker daemon is running"
    else
        red "Docker daemon is NOT running (or no permission)"
    fi
else
    red "docker not found in PATH"
fi

if command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
    green "docker compose available"
else
    red "docker compose not available"
fi

# ── Node.js / npm ──────────────────────────────────────────────
header "Node.js / npm"

if command -v node &>/dev/null; then
    NODE_VER=$(node --version)
    green "node $NODE_VER"
else
    red "node not found (need >= 18 for Playwright MCP)"
fi

if command -v npx &>/dev/null; then
    green "npx available"
else
    red "npx not found"
fi

# ── Playwright MCP ─────────────────────────────────────────────
header "Playwright MCP"

# Check if @playwright/mcp is resolvable
if command -v npx &>/dev/null; then
    if npx --yes @playwright/mcp@latest --help &>/dev/null 2>&1; then
        green "@playwright/mcp runs successfully"
    else
        yellow "@playwright/mcp may need first-time install (npx will fetch it)"
    fi
fi

# Check if Playwright browsers are installed
# Playwright MCP uses its own Chromium; check the common install paths
if [ -d "$HOME/.cache/ms-playwright" ]; then
    BROWSER_COUNT=$(find "$HOME/.cache/ms-playwright" -maxdepth 1 -type d | wc -l)
    green "Playwright browsers cached ($((BROWSER_COUNT - 1)) found)"
else
    yellow "No Playwright browsers cached (MCP will install on first use)"
fi

# ── Chromium for Playwright ─────────────────────────────────────
header "Browser Runtime"

# Check system Chromium (optional — Playwright MCP bundles its own)
if command -v chromium &>/dev/null || command -v chromium-browser &>/dev/null; then
    green "System Chromium available"
else
    yellow "No system Chromium (Playwright MCP bundles its own — this is fine)"
fi

# Check if headless Chrome can run (critical for CI)
if command -v node &>/dev/null; then
    TEST_SCRIPT=$(cat << 'EOF'
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.setContent('<h1>OK</h1>');
  const text = await page.textContent('h1');
  await browser.close();
  if (text !== 'OK') process.exit(1);
  console.log('headless-ok');
})().catch(e => { console.error(e.message); process.exit(1); });
EOF
    )
    # Only test if playwright package is available
    if node -e "require('playwright')" &>/dev/null 2>&1; then
        RESULT=$(echo "$TEST_SCRIPT" | node 2>&1) && green "Headless Chromium works ($RESULT)" || red "Headless Chromium failed: $RESULT"
    else
        yellow "Playwright package not installed globally (MCP has its own — this is fine)"
    fi
fi

# ── curl / jq (for API testing) ────────────────────────────────
header "API Testing Tools"

if command -v curl &>/dev/null; then
    green "curl available"
else
    red "curl not found"
fi

if command -v jq &>/dev/null; then
    green "jq available"
else
    yellow "jq not found (recommended for API response parsing)"
fi

# ── Python (for seed script) ───────────────────────────────────
header "Python"

if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    green "$PY_VER"
else
    red "python3 not found"
fi

# ── Summary ─────────────────────────────────────────────────────
header "Summary"
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "  Warnings: $WARN"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  ⚠ Fix failures above before running E2E tests."
    exit 1
else
    echo ""
    echo "  All prerequisites met. Run: testing/e2e/run.sh up"
    exit 0
fi
