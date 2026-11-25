#!/usr/bin/env python3
"""检查页面内联 JS 的语法（需要 node；没有 node 时跳过）。

用法:
    python3 check_syntax.py assets/*.html
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.S)


def main(paths):
    node = shutil.which("node")
    if not node:
        print("! 未安装 node，跳过 JS 语法检查")
        return 0
    failed = 0
    for p in paths:
        src = Path(p).read_text(encoding="utf-8")
        blocks = SCRIPT_RE.findall(src)
        if not blocks:
            print(f"! {p}: 没有找到内联 script")
            failed += 1
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(blocks[-1])
            tmp = f.name
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"✓ {p}: JS 语法正常")
        else:
            print(f"✗ {p}: JS 语法错误")
            print(r.stderr.strip()[:800])
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: python3 check_syntax.py <html> [html...]")
    sys.exit(main(sys.argv[1:]))
