#!/usr/bin/env bash
# ==============================================================================
# Harness Agent Scaffolding Script
# Copies AGENTS.md, SDLC skills, and workflow templates to a target repository.
#
# Usage:
#   ./install.sh
#   ./install.sh [PROJECT_NAME]
#   ./install.sh [PROJECT_NAME] [TARGET_DIR]
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="${1:-}"
TARGET_DIR="${2:-}"
FORCE="${FORCE:-false}"

CURRENT_DIR="$(pwd)"

# 1. Ask for project name or target directory if not provided
if [ -z "$PROJECT_NAME" ] && [ -z "$TARGET_DIR" ]; then
    if [ "$CURRENT_DIR" != "$SCRIPT_DIR" ]; then
        TARGET_DIR="$CURRENT_DIR"
        echo "Phát hiện đang chạy từ thư mục dự án: $TARGET_DIR"
    else
        echo "=== THIẾT LẬP REPO MỚI CHO HARNESS AGENT ==="
        read -rp "Nhập tên dự án của bạn (ví dụ: my-awesome-project): " PROJECT_NAME
        while [ -z "$PROJECT_NAME" ]; do
            read -rp "Tên dự án không được để trống. Vui lòng nhập lại: " PROJECT_NAME
        done
        TARGET_DIR="../$PROJECT_NAME"
    fi
elif [ -z "$TARGET_DIR" ] && [ -n "$PROJECT_NAME" ]; then
    TARGET_DIR="../$PROJECT_NAME"
fi

# 2. Check if project directory already exists
if [ -d "$TARGET_DIR" ]; then
    TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
    if [ -n "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]; then
        echo ""
        echo "[THÔNG TIN] Thư mục '$TARGET_DIR' đã chứa dữ liệu/code hiện có."
        if [ "$FORCE" != "true" ]; then
            echo "Chọn hành động:"
            echo "  [1] Cập nhật / Bổ sung quy chuẩn (AGENTS.md, skills, .ai/plans) vào dự án hiện có (Không xóa code cũ)"
            echo "  [2] Hủy thao tác (Abort)"
            read -rp "Lựa chọn của bạn [1/2] (Mặc định: 1): " choice
            choice="${choice:-1}"
            if [ "$choice" = "2" ]; then
                echo "Đã hủy quá trình thiết lập."
                exit 0
            fi
        fi
        echo "--> Tiến hành bổ sung / cập nhật quy chuẩn vào: $TARGET_DIR"
    fi
else
    mkdir -p "$TARGET_DIR"
    TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
    echo "--> Đã tạo thư mục mới: $TARGET_DIR"
fi

echo "==> Đang sao chép quy tắc Harness Agent, SDLC Skills & cấu hình agy-cli vào: $TARGET_DIR"

# 1. Copy compliance and rule files
if [ -f "$SCRIPT_DIR/AGENTS.md" ]; then
    cp "$SCRIPT_DIR/AGENTS.md" "$TARGET_DIR/AGENTS.md"
    echo "  [✓] Created AGENTS.md"
fi
if [ -f "$TARGET_DIR/Agent.md" ]; then
    rm -f "$TARGET_DIR/Agent.md"
fi

# 2. Copy or update pre-commit config (ensuring branch protection hooks)
if [ -f "$SCRIPT_DIR/.pre-commit-config.yaml" ]; then
    if [ ! -f "$TARGET_DIR/.pre-commit-config.yaml" ]; then
        cp "$SCRIPT_DIR/.pre-commit-config.yaml" "$TARGET_DIR/.pre-commit-config.yaml"
        echo "  [✓] Created .pre-commit-config.yaml (Branch protection active)"
    elif ! grep -q "no-commit-to-branch" "$TARGET_DIR/.pre-commit-config.yaml" 2>/dev/null; then
        cat << 'EOF' >> "$TARGET_DIR/.pre-commit-config.yaml"


  # Harness Agent Branch Protection Hook
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: no-commit-to-branch
        args: [--branch, main, --branch, master, --branch, dev, --branch, develop]
EOF
        echo "  [✓] Appended no-commit-to-branch hook to existing .pre-commit-config.yaml"
    else
        echo "  [✓] Existing .pre-commit-config.yaml preserved"
    fi
fi

# 3. Copy sample orchestrator plan
mkdir -p "$TARGET_DIR/examples"
if [ ! -f "$TARGET_DIR/examples/orchestrator_plan.yaml" ] && [ -f "$SCRIPT_DIR/examples/orchestrator_plan.yaml" ]; then
    cp "$SCRIPT_DIR/examples/orchestrator_plan.yaml" "$TARGET_DIR/examples/orchestrator_plan.yaml"
    echo "  [✓] Created examples/orchestrator_plan.yaml"
fi

# 4. Copy SDLC Agent Skills
if [ -d "$SCRIPT_DIR/.agents" ]; then
    mkdir -p "$TARGET_DIR/.agents"
    cp -r "$SCRIPT_DIR/.agents"/* "$TARGET_DIR/.agents/"
    echo "  [✓] Copied SDLC Skills to .agents/skills/"
fi

# 4a. Copy Lifecycle Hooks Configuration
if [ -f "$SCRIPT_DIR/.agents/hooks.json" ]; then
    mkdir -p "$TARGET_DIR/.agents"
    cp "$SCRIPT_DIR/.agents/hooks.json" "$TARGET_DIR/.agents/hooks.json"
    echo "  [✓] Created .agents/hooks.json (Lifecycle Hooks config)"
fi

# 4b. Copy Orchestrator Hooks Script to .agents/hooks/
SOURCE_HOOKS_DIR="$SCRIPT_DIR/.agents/hooks"
if [ ! -d "$SOURCE_HOOKS_DIR" ]; then
    SOURCE_HOOKS_DIR="$SCRIPT_DIR/src/harness_agent/hooks"
fi
if [ -d "$SOURCE_HOOKS_DIR" ]; then
    mkdir -p "$TARGET_DIR/.agents/hooks"
    cp -r "$SOURCE_HOOKS_DIR"/* "$TARGET_DIR/.agents/hooks/"
    echo "  [✓] Copied Orchestrator hook script to .agents/hooks/"
fi

# Clean up legacy src/harness_agent if exists
if [ -d "$TARGET_DIR/src/harness_agent" ]; then
    rm -rf "$TARGET_DIR/src/harness_agent/hooks"
    if [ -z "$(ls -A "$TARGET_DIR/src/harness_agent" 2>/dev/null)" ]; then
        rm -rf "$TARGET_DIR/src/harness_agent"
    fi
fi
if [ -d "$TARGET_DIR/src" ] && [ -z "$(ls -A "$TARGET_DIR/src" 2>/dev/null)" ]; then
    rmdir "$TARGET_DIR/src" 2>/dev/null || true
fi

# 4c. Copy GitHub Templates
if [ -d "$SCRIPT_DIR/.github" ]; then
    mkdir -p "$TARGET_DIR/.github"
    cp -r "$SCRIPT_DIR/.github"/* "$TARGET_DIR/.github/"
    echo "  [✓] Copied GitHub templates to .github/"
fi

# 5. Initialize 3-tier planning directories
mkdir -p "$TARGET_DIR/.runs"
mkdir -p "$TARGET_DIR/.ai/plans/main"
mkdir -p "$TARGET_DIR/.ai/plans/subtasks"
mkdir -p "$TARGET_DIR/.ai/decisions"
mkdir -p "$TARGET_DIR/.ai/context"
echo "  [✓] Initialized planning directories (.runs/, .ai/plans/main/, .ai/plans/subtasks/, .ai/decisions/, .ai/context/)"

# 6. Ensure .gitignore
GITIGNORE_FILE="$TARGET_DIR/.gitignore"
if [ ! -f "$GITIGNORE_FILE" ]; then
    cat << 'EOF' > "$GITIGNORE_FILE"
# Harness Agent & AI Orchestration
.agents/
.runs/
.ai/
.worktrees/
AGENTS.md
EOF
    echo "  [✓] Created .gitignore"
else
    for entry in ".agents/" ".runs/" ".ai/" ".worktrees/" "AGENTS.md"; do
        if ! grep -qxF "$entry" "$GITIGNORE_FILE"; then
            echo "$entry" >> "$GITIGNORE_FILE"
        fi
    done
    echo "  [✓] Updated .gitignore with AI rules"
fi

# 7. Register project in ~/.harness/projects.json if python is available
python3 -c "
import json, os, sys
if len(sys.argv) > 1 and sys.argv[1]:
    harness_dir = os.path.expanduser('~/.harness')
    os.makedirs(harness_dir, exist_ok=True)
    reg_file = os.path.join(harness_dir, 'projects.json')
    projects = set()
    if os.path.exists(reg_file):
        try:
            with open(reg_file, 'r') as f:
                projects = set(json.load(f))
        except Exception:
            pass
    projects.add(sys.argv[1])
    with open(reg_file, 'w') as f:
        json.dump(sorted(list(projects)), f, indent=2)
" "$TARGET_DIR" 2>/dev/null || true

# 7b. Auto-trust target project and .worktrees in agy-cli settings.json
python3 -c "
import json, os, sys
if len(sys.argv) > 1 and sys.argv[1]:
    target = os.path.abspath(sys.argv[1])
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
    candidates = [
        target,
        os.path.join(target, '.worktrees'),
        os.path.join(target, '.worktrees', 'agent')
    ]
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
" "$TARGET_DIR" 2>/dev/null || true

# 8. Install Git Pre-commit Hooks in target if it is a Git repo
if [ -d "$TARGET_DIR/.git" ] && command -v pre-commit >/dev/null 2>&1; then
    (cd "$TARGET_DIR" && pre-commit install >/dev/null 2>&1 || true)
    echo "  [✓] Activated Git pre-commit hooks (Protected branches: main, dev)"
fi

echo ""
echo "========================================================================"
echo " Thiết lập hoàn tất! agy-cli đã sẵn sàng trong: $TARGET_DIR"
echo "========================================================================"
echo ""
echo "Các bước tiếp theo trong dự án của bạn:"
echo "  1. cd \"$TARGET_DIR\""
echo "  2. Chạy agy: agy \"Đọc file AGENTS.md và bắt đầu nhiệm vụ\""
echo "  3. Thao tác Git qua agy: agy \"Tạo branch feat/init và commit\""
echo ""
