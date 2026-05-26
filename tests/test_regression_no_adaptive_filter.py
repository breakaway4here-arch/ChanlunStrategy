"""防止 adaptive_filter / hard_threshold / top_n=20 等旧补丁逻辑回来。"""
import unittest
import os
import re


FORBIDDEN_PATTERNS = [
    "adaptive_filter",
    "hard_threshold",
    r"top_n\s*=\s*20",
    r">\s*75\s*分",
    "不足20",
    "补齐",
]


class NoAdaptiveFilterRegression(unittest.TestCase):
    def test_no_adaptive_filter_in_source(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        targets = ["run.py", "chanlun", "tests", "scripts"]
        found = []

        for target in targets:
            target_path = os.path.join(project_root, target)
            if not os.path.exists(target_path):
                continue

            if os.path.isfile(target_path):
                files = [target_path]
            else:
                files = []
                for root, _dirs, fnames in os.walk(target_path):
                    for fn in fnames:
                        if fn.endswith(".py"):
                            files.append(os.path.join(root, fn))

            for fp in files:
                with open(fp, "r", encoding="utf-8") as f:
                    for lineno, line in enumerate(f, 1):
                        for pat in FORBIDDEN_PATTERNS:
                            if re.search(pat, line):
                                # 允许在 test 文件自身中出现，因为我们在测试防止回归
                                if "test_regression_no_adaptive_filter" in fp:
                                    continue
                                found.append(f"{fp}:{lineno}: {pat} -> {line.strip()}")

        if found:
            self.fail("Found forbidden patterns:\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
