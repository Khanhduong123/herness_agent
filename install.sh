#!/usr/bin/env bash
# ==============================================================================
# Harness Agent Scaffolding Script
# Copies Agent.md, AGENTS.md, and workflow templates to a new target repository.
#
# Usage:
#   ./install.sh [TARGET_DIR]
# Example:
#   ./install.sh ../my-new-project
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-.}"

mkdir -p "$TARGET_DIR"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

echo "==> Setting up Harness Agent & agy-cli rules in: $TARGET_DIR"

# 1. Copy compliance and rule files
cp "$SCRIPT_DIR/Agent.md" "$TARGET_DIR/Agent.md"
cp "$SCRIPT_DIR/AGENTS.md" "$TARGET_DIR/AGENTS.md"
echo "  [✓] Created Agent.md and AGENTS.md"

# 2. Copy pre-commit config if not exists
if [ ! -f "$TARGET_DIR/.pre-commit-config.yaml" ] && [ -f "$SCRIPT_DIR/.pre-commit-config.yaml" ]; then
    cp "$SCRIPT_DIR/.pre-commit-config.yaml" "$TARGET_DIR/.pre-commit-config.yaml"
    echo "  [✓] Created .pre-commit-config.yaml"
fi

# 3. Copy sample orchestrator plan
mkdir -p "$TARGET_DIR/examples"
if [ ! -f "$TARGET_DIR/examples/orchestrator_plan.yaml" ] && [ -f "$SCRIPT_DIR/examples/orchestrator_plan.yaml" ]; then
    cp "$SCRIPT_DIR/examples/orchestrator_plan.yaml" "$TARGET_DIR/examples/orchestrator_plan.yaml"
    echo "  [✓] Created examples/orchestrator_plan.yaml"
fi

echo ""
echo "========================================================================"
echo " Setup complete! agy-cli is now ready in: $TARGET_DIR"
echo "========================================================================"
echo ""
echo "Next steps in your new project:"
echo "  1. cd \"$TARGET_DIR\""
echo "  2. Run agy: agy \"Đọc file AGENTS.md và tóm tắt quy tắc dự án này\""
echo "  3. Use agy directly for Git: agy \"Tạo branch feat/init và commit\""
echo ""
