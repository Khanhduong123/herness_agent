import os
import sys
import runpy

if len(sys.argv) > 1:
    hook_name = sys.argv[1]
    candidates = [
        f"hooks/{hook_name}",
        f".agents/hooks/{hook_name}",
        f"src/harness_agent/hooks/{hook_name}",
    ]
    for p in candidates:
        if os.path.exists(p):
            runpy.run_path(p, run_name="__main__")
            sys.exit(0)
    sys.stderr.write(f"Hook {hook_name} not found in {candidates}\n")
    sys.exit(1)
