#!/usr/bin/env bash
# ==============================================================================
# Synchronize Agent.md, AGENTS.md, SDLC skills, and lifecycle hooks to working repositories.
# Enforces that updates are ONLY applied on the 'main' branch of working projects.
#
# Usage:
#   ./sync.sh --all
#   ./sync.sh ../du-an-moi
#   ./sync.sh ../du-an-moi --link
# ==============================================================================

set -euo pipefail

TARGET="${1:-}"
EXTRA="${2:-}"
FORCE="${FORCE:-false}"

# Verify branch is main if target has .git
if [ -n "$TARGET" ] && [ "$TARGET" != "--all" ] && [ -d "$TARGET/.git" ]; then
    CURRENT_BRANCH="$(git -C "$TARGET" branch --show-current 2>/dev/null || true)"
    if [ -n "$CURRENT_BRANCH" ] && [ "$CURRENT_BRANCH" != "main" ] && [ "$CURRENT_BRANCH" != "master" ] && [ "$FORCE" != "true" ]; then
        echo "[TỪ CHỐI] Dự án '$TARGET' đang ở nhánh '$CURRENT_BRANCH'!"
        echo "QUY TẮC: Chỉ được phép update quy chuẩn & skills trên nhánh 'main' để tránh gây xung đột code tính năng."
        echo "Hướng dẫn:"
        echo "  1. Chuyển về nhánh main: cd '$TARGET' && git checkout main"
        echo "  2. Chạy lại lệnh sync từ harness_agent"
        echo "  3. Merge main vào nhánh tính năng của bạn: git checkout $CURRENT_BRANCH && git merge main"
        exit 1
    fi
fi

ARGS=()
if [ "$TARGET" = "--all" ]; then
    ARGS+=("--all")
elif [ -n "$TARGET" ]; then
    ARGS+=("$TARGET")
else
    ARGS+=("--all")
fi

if [ "$EXTRA" = "--link" ] || [ "$TARGET" = "--link" ]; then
    ARGS+=("--link")
fi

echo "Đang thực hiện đồng bộ (Kiểm tra an toàn nhánh 'main')..."
conda run -n pytorch harness-agent sync "${ARGS[@]}"
