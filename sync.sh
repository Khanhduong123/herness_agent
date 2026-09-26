#!/usr/bin/env bash
# ==============================================================================
# Synchronize Agent.md, AGENTS.md, and SDLC skills to working repositories
#
# Usage:
#   ./sync.sh --all
#   ./sync.sh ../du-an-moi
#   ./sync.sh ../du-an-moi --link
# ==============================================================================

set -euo pipefail

TARGET="${1:-}"
EXTRA="${2:-}"

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

conda run -n pytorch harness-agent sync "${ARGS[@]}"
