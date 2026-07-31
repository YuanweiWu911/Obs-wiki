#!/usr/bin/env python
"""
使用 pdf2htmlEX.exe 将 PDF 转换为 HTML，并生成便于浏览的索引页面。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PDF_DIR = Path("pdf")
HTML_DIR = Path("html")
EXE = Path("../pdf2htmlex/pdf2htmlEX.exe")
INDEX_PATH = Path("out.html")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 pdf2htmlEX 将 PDF 转换为 HTML。")
    parser.add_argument(
        "--input",
        help="指定单个 PDF 文件作为输入。",
    )
    parser.add_argument(
        "--start",
        type=int,
        help="指定起始页码（从 1 开始）。",
    )
    parser.add_argument(
        "--end",
        type=int,
        help="指定结束页码（从 1 开始）。",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        default=False,
        help="即使 HTML 输出已存在，也强制重新转换。",
    )
    return parser.parse_args()


def resolve_inputs(single_input: str | None) -> list[Path]:
    """解析命令行输入，返回待转换 PDF 列表。"""
    if single_input:
        pdf_path = Path(single_input)
        if not pdf_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {pdf_path}")
        return [pdf_path]

    if not PDF_DIR.exists():
        raise FileNotFoundError(f"PDF 目录不存在: {PDF_DIR}")

    return sorted(PDF_DIR.glob("*.pdf"))


def html_output_path(pdf_path: Path) -> Path:
    """根据 PDF 路径计算 HTML 输出路径。"""
    return HTML_DIR / f"{pdf_path.stem}.html"


def validate_page_range(start: int | None, end: int | None) -> tuple[int | None, int | None]:
    """校验页码范围参数。"""
    if start is not None and start < 1:
        raise ValueError("--start 必须大于等于 1。")
    if end is not None and end < 1:
        raise ValueError("--end 必须大于等于 1。")
    if start is not None and end is not None and start > end:
        raise ValueError("--start 不能大于 --end。")
    return start, end


def convert_pdf(
    pdf_path: Path,
    *,
    force: bool = False,
    start_page: int | None = None,
    end_page: int | None = None,
) -> bool:
    """转换单个 PDF，返回是否执行了实际转换。"""
    out_path = html_output_path(pdf_path)
    if out_path.exists() and not force:
        print(f"跳过（已存在）: {out_path.name}")
        return False

    print(f"正在转换: {pdf_path.name}")
    cmd = [
        str(EXE),
        "--no-drm",
        "1",
        "--first-page",
        str(start_page or 1),
        "--last-page",
        str(end_page or 2147483647),
        "--fit-width",
        "1024",
        "--dest-dir",
        str(HTML_DIR),
        str(pdf_path),
    ]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"转换失败: {pdf_path.name}")
    return True


def write_index() -> None:
    """根据现有 HTML 文件生成索引页面。"""
    html_files = sorted(HTML_DIR.glob("*.html"))
    with INDEX_PATH.open("w", encoding="utf-8") as outf:
        outf.write("""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<div style="position:absolute;top:0;left:0;width:80%;height:100%;">
  <iframe width="100%" height="100%" name="pdf"></iframe>
</div>
<div style="position:absolute;top:0;right:0;width:20%;height:100%;overflow:auto;text-align:right;">
""")
        for html_path in html_files:
            outf.write(f'<a href="{HTML_DIR.name}/{html_path.name}" target="pdf">{html_path.stem}</a><br/>\n')
        outf.write("</div></body></html>")


def main() -> int:
    args = parse_args()

    if not EXE.exists():
        print(f"错误: 未找到 pdf2htmlEX 可执行文件: {EXE}")
        return 1

    HTML_DIR.mkdir(exist_ok=True)

    try:
        start_page, end_page = validate_page_range(args.start, args.end)
        pdf_files = resolve_inputs(args.input)
    except Exception as exc:
        print(f"错误: {exc}")
        return 1

    if not pdf_files:
        print("未找到 PDF 文件")
        write_index()
        return 0

    try:
        for pdf_path in pdf_files:
            convert_pdf(
                pdf_path,
                force=args.force,
                start_page=start_page,
                end_page=end_page,
            )
        write_index()
    except Exception as exc:
        print(f"错误: {exc}")
        return 1

    print("完成!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
