from __future__ import annotations

import sys
import unittest
from pathlib import Path


class FriendlyTestResult(unittest.TextTestResult):
    def getDescription(self, test: unittest.TestCase) -> str:
        method_name = test._testMethodName
        class_name = test.__class__.__name__.replace("Tests", "")
        readable_method = method_name.removeprefix("test_").replace("_", " ")
        readable_class = _split_camel_case(class_name)
        return f"{readable_class}: {readable_method}"

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self.stream.write(f"- {self.getDescription(test)} ... ")
        self.stream.flush()

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self.stream.writeln("PASSED")

    def addFailure(self, test: unittest.TestCase, err) -> None:
        super().addFailure(test, err)
        self.stream.writeln("FAILED")

    def addError(self, test: unittest.TestCase, err) -> None:
        super().addError(test, err)
        self.stream.writeln("FAILED")

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self.stream.writeln(f"SKIPPED ({reason})")


class FriendlyTestRunner(unittest.TextTestRunner):
    resultclass = FriendlyTestResult


def _split_camel_case(value: str) -> str:
    words = []
    current = ""
    for character in value:
        if character.isupper() and current:
            words.append(current)
            current = character
        else:
            current += character
    if current:
        words.append(current)
    return " ".join(words)


def _discover_tests(project_root: Path) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for relative_dir in ("tests/backend", "tests/storage", "tests/frontend"):
        test_dir = project_root / relative_dir
        if test_dir.is_dir():
            suite.addTests(loader.discover(str(test_dir), top_level_dir=str(project_root)))
    return suite


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    for path in (project_root, project_root / "backend"):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    result = FriendlyTestRunner(verbosity=0).run(_discover_tests(project_root))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
