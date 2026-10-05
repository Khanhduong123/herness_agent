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

# Auto-trust project and .worktrees in agy-cli settings.json
python3 -c "
import json, os, sys
target_arg = sys.argv[1] if len(sys.argv) > 1 else ''
targets = []
if target_arg and target_arg != '--all' and target_arg != '--link':
    targets.append(os.path.abspath(target_arg))
else:
    reg_file = os.path.expanduser('~/.harness/projects.json')
    if os.path.exists(reg_file):
        try:
            with open(reg_file, 'r', encoding='utf-8') as f:
                targets = [os.path.abspath(p) for p in json.load(f)]
        except Exception:
            pass

if targets:
    settings_dir = os.path.expanduser('~/.gemini/antigravity-cli')
    os.makedirs(settings_dir, exist_ok=True)
    settings_file = os.path.join(settings_dir, 'settings.json')
    data = {}
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    trusted = data.get('trustedWorkspaces')
    if not isinstance(trusted, list):
        trusted = []

    for t in targets:
        candidates = [t, os.path.join(t, '.worktrees'), os.path.join(t, '.worktrees', 'agent')]
        for c in candidates:
            norm_c = os.path.abspath(c)
            if not any(os.path.abspath(existing) == norm_c for existing in trusted if isinstance(existing, str)):
                trusted.append(norm_c)
    data['trustedWorkspaces'] = trusted
    try:
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print('  [✓] Auto-trusted project and .worktrees in agy-cli settings.json')
    except Exception:
        pass
" "$TARGET" 2>/dev/null || true
