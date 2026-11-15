"""Run the REZE test suite with the standard library (no pytest required).

Same discovery as CI (``python -m unittest discover -s tests -v``). Reports the
real number of tests and exits non-zero on any failure or error. Pass a
substring to run only matching test modules or cases, for example
``python run_tests.py backup``.

Developer: UnchartedAli · Channel: @yamods
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def main(argv):
    loader = unittest.TestLoader()
    suite = loader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(TESTS))
    if argv:
        wanted = [a.lower() for a in argv]
        selected = [t for t in _flatten(suite) if any(w in t.id().lower() for w in wanted)]
        suite = unittest.TestSuite(selected)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
