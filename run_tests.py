"""Minimal dependency-free test runner for the REZE suite (pytest-compatible subset)."""
import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import tests.support  # noqa: E402,F401  - prepares the environment first

def main(patterns=None):
    files = sorted((ROOT / "tests").glob("test_*.py"))
    if patterns:
        files = [f for f in files if any(p in f.name for p in patterns)]
    passed = failed = skipped = 0
    failures = []
    for path in files:
        module = importlib.import_module(f"tests.{path.stem}")
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            fn = getattr(module, name)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
            except Exception:
                failed += 1
                failures.append((path.name, name, traceback.format_exc()))
    print(f"\n{passed} passed, {failed} failed, {len(files)} files")
    for file, name, tb in failures:
        print(f"\nFAIL {file}::{name}\n{tb}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
