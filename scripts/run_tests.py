from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    for path in (project_root, project_root / "backend"):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    try:
        import pytest
    except ImportError:
        print("pytest is required. Install with: pip install -r requirements-test.txt")
        return 1

    return pytest.main(
        [
            str(project_root / "tests" / "interface"),
            str(project_root / "tests" / "engine"),
            str(project_root / "tests" / "storage"),
            "-v",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
