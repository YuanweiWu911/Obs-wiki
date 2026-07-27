"""
兼容入口：强制使用 OCR 方式处理 PDF。

主逻辑已经合并到 pdf2markdown.py 中。
这个脚本保留为旧命令的兼容包装器。
"""

from __future__ import annotations

from pdf2markdown import main


if __name__ == "__main__":
    raise SystemExit(main(force_ocr_default=True))
