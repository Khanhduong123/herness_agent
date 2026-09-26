#!/usr/bin/env bash
# ==============================================================================
# Harness Agent Scaffolding Script
# Copies Agent.md, AGENTS.md, SDLC skills, and workflow templates to a target repository.
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

# 1. Ask for project name if not provided
if [ -z "$PROJECT_NAME" ] && [ -z "$TARGET_DIR" ]; then
    echo "=== THIẾT LẬP REPO MỚI CHO HARNESS AGENT ==="
    read -rp "Nhập tên dự án của bạn (ví dụ: my-awesome-project): " PROJECT_NAME
    while [ -z "$PROJECT_NAME" ]; do
        read -rp "Tên dự án không được để trống. Vui lòng nhập lại: " PROJECT_NAME
    done
fi

# Determine target directory
if [ -z "$TARGET_DIR" ]; then
    TARGET_DIR="../$PROJECT_NAME"
fi

# 2. Check if project directory already exists
if [ -d "$TARGET_DIR" ]; then
    TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
    echo ""
    echo "[CẢNH BÁO] Thư mục dự án '$TARGET_DIR' ĐÃ TỒN TẠI trên máy!"
    if [ "$FORCE" != "true" ]; then
        echo "Chọn hành động:"
        echo "  [1] Cập nhật / Bổ sung quy chuẩn (Agent.md, skills) vào dự án hiện có (Không xóa code cũ)"
        echo "  [2] Hủy thao tác (Abort)"
        read -rp "Lựa chọn của bạn [1/2] (Mặc định: 1): " choice
        choice="${choice:-1}"
        if [ "$choice" = "2" ]; then
            echo "Đã hủy quá trình thiết lập."
            exit 0
        fi
    fi
    echo "--> Tiến hành bổ sung / cập nhật quy chuẩn vào dự án: $TARGET_DIR"
else
    mkdir -p "$TARGET_DIR"
    TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
    echo "--> Đã tạo thư mục mới: $TARGET_DIR"
fi

echo "==> Đang sao chép quy tắc Harness Agent, SDLC Skills & cấu hình agy-cli vào: $TARGET_DIR"

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

# 4. Copy SDLC Agent Skills
if [ -d "$SCRIPT_DIR/.agents" ]; then
    mkdir -p "$TARGET_DIR/.agents"
    cp -r "$SCRIPT_DIR/.agents"/* "$TARGET_DIR/.agents/"
    echo "  [✓] Copied SDLC Skills to .agents/skills/"
fi

echo ""
echo "========================================================================"
echo " Thiết lập hoàn tất! agy-cli đã sẵn sàng trong: $TARGET_DIR"
echo "========================================================================"
echo ""
echo "Các bước tiếp theo trong dự án mới của bạn:"
echo "  1. cd \"$TARGET_DIR\""
echo "  2. Chạy agy: agy \"Đọc file AGENTS.md và tóm tắt quy tắc dự án này\""
echo "  3. Thao tác Git qua agy: agy \"Tạo branch feat/init và commit\""
echo ""
