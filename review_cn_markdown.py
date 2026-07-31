"""
中文 Markdown 语法与错别字审查脚本
读取 ./markdown/*-cn.md，调用 DeepSeek 识别语法问题和错别字，
输出 ./report/*-cn-review-report.md。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# DeepSeek API 配置
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN")
BASE_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
PROXY_MODE = os.environ.get("DEEPSEEK_PROXY_MODE", "auto").lower()

INPUT_DIR = Path("./markdown")
OUTPUT_DIR = Path("./report")
MAX_WORKERS = 6

OUTPUT_DIR.mkdir(exist_ok=True)

_proxy_fallback_notice_lock = threading.Lock()
_proxy_fallback_notice_printed = False

REVIEW_PROMPT = """你是一个严谨的中文学术校对助手。请检查给定的中文 Markdown 文本，只识别以下两类问题：
1. 错别字
2. 语法错误或明显病句

要求：
- 输入的每一行都带有行号前缀，格式为 `L12| 正文`
- 只根据给定文本判断，不要臆造不存在的问题
- 只检查自然语言正文，不要把以下内容当作错误：
  - Markdown 标题符号、列表符号、表格分隔符
  - 代码块、公式、URL、文件路径、文献编号
  - Obsidian 链接、标签、Front Matter
- 如果一行没有问题，不要输出
- 如果没有发现任何问题，返回空 JSON 数组 `[]`

输出格式必须是 JSON 数组，数组元素格式如下：
[
  {
    "line": 12,
    "issue_type": "错别字",
    "excerpt": "原文片段",
    "problem": "问题说明",
    "suggestion": "建议改法"
  }
]

不要输出 JSON 之外的任何文字。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查中文 Markdown 的语法和错别字，并生成审查报告。")
    parser.add_argument(
        "--input",
        help="指定单个 Markdown 文件作为输入。",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        default=False,
        help="即使报告文件已存在，也强制重新生成。",
    )
    return parser.parse_args()


def create_session(use_env_proxy: bool) -> requests.Session:
    """创建 requests 会话，可选择是否继承环境代理设置。"""
    session = requests.Session()
    session.trust_env = use_env_proxy
    return session


def post_with_proxy_fallback(headers: dict, data: dict, timeout: int):
    """支持代理失败后自动回退直连。"""
    global _proxy_fallback_notice_printed

    if PROXY_MODE in {"off", "direct", "false", "0", "no"}:
        with create_session(use_env_proxy=False) as session:
            return session.post(BASE_URL, headers=headers, json=data, timeout=timeout)

    if PROXY_MODE in {"on", "proxy", "true", "1", "yes"}:
        with create_session(use_env_proxy=True) as session:
            return session.post(BASE_URL, headers=headers, json=data, timeout=timeout)

    try:
        with create_session(use_env_proxy=True) as session:
            return session.post(BASE_URL, headers=headers, json=data, timeout=timeout)
    except requests.exceptions.ProxyError:
        with _proxy_fallback_notice_lock:
            if not _proxy_fallback_notice_printed:
                print("  检测到代理不可用，自动切换为直连重试...")
                _proxy_fallback_notice_printed = True
        with create_session(use_env_proxy=False) as session:
            return session.post(BASE_URL, headers=headers, json=data, timeout=timeout)


def call_api(system_prompt: str, user_content: str, retries: int = 3) -> str:
    """调用 DeepSeek API。"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    for attempt in range(retries):
        try:
            response = post_with_proxy_fallback(headers=headers, data=data, timeout=120)
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                return content.strip() if content else ""
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        except Exception as exc:
            print(f"  API 调用失败 (第 {attempt + 1}/{retries} 次): {exc}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def strip_json_fence(text: str) -> str:
    """去掉常见的 JSON Markdown 围栏。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_issues(raw_text: str) -> list[dict[str, object]]:
    """解析模型返回的 JSON 问题列表。"""
    cleaned = strip_json_fence(raw_text)
    issues = json.loads(cleaned or "[]")
    if not isinstance(issues, list):
        raise ValueError("模型返回的结果不是 JSON 数组。")

    normalized: list[dict[str, object]] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        line = item.get("line")
        if not isinstance(line, int):
            continue
        normalized.append(
            {
                "line": line,
                "issue_type": str(item.get("issue_type", "")).strip() or "未分类",
                "excerpt": str(item.get("excerpt", "")).strip(),
                "problem": str(item.get("problem", "")).strip(),
                "suggestion": str(item.get("suggestion", "")).strip(),
            }
        )
    return normalized


def split_numbered_markdown(text: str, max_chars: int = 3500) -> list[str]:
    """将 Markdown 按行号编号后分块，便于定位问题。"""
    lines = text.splitlines()
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for idx, line in enumerate(lines, start=1):
        numbered_line = f"L{idx}| {line}"
        if current_lines and current_len + len(numbered_line) + 1 > max_chars:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
        current_lines.append(numbered_line)
        current_len += len(numbered_line) + 1

    if current_lines:
        chunks.append("\n".join(current_lines))
    return chunks


def resolve_input_files(single_input: str | None) -> list[Path]:
    """解析命令行输入，返回待审查文件列表。"""
    if single_input:
        md_path = Path(single_input)
        if not md_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {md_path}")
        return [md_path]

    return sorted(INPUT_DIR.glob("*-cn.md"))


def report_path_for(md_path: Path) -> Path:
    """根据输入 Markdown 路径计算报告输出路径。"""
    return OUTPUT_DIR / f"{md_path.stem}-review-report.md"


def unique_issues(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    """按行号和问题内容去重，并排序。"""
    seen: set[tuple[object, ...]] = set()
    deduped: list[dict[str, object]] = []
    for item in issues:
        key = (
            item.get("line"),
            item.get("issue_type"),
            item.get("excerpt"),
            item.get("problem"),
            item.get("suggestion"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    deduped.sort(key=lambda item: (int(item["line"]), str(item["issue_type"]), str(item["excerpt"])))
    return deduped


def escape_table_cell(text: str) -> str:
    """转义 Markdown 表格单元格。"""
    return str(text).replace("|", "\\|").replace("\n", "<br>")


def render_report(md_path: Path, issues: list[dict[str, object]]) -> str:
    """生成 Markdown 审查报告。"""
    lines = [
        f"# 中文语法与错别字审查报告：{md_path.name}",
        "",
        "## 文件信息",
        f"- 输入文件：`{md_path}`",
        f"- 问题总数：{len(issues)}",
        "",
    ]

    if not issues:
        lines.extend(
            [
                "## 结论",
                "",
                "未识别到明显的语法错误或错别字。",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "## 问题清单",
            "",
            "| 行号 | 问题类型 | 原文片段 | 问题说明 | 建议改法 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )

    for issue in issues:
        lines.append(
            "| {line} | {issue_type} | {excerpt} | {problem} | {suggestion} |".format(
                line=issue["line"],
                issue_type=escape_table_cell(issue["issue_type"]),
                excerpt=escape_table_cell(issue["excerpt"]),
                problem=escape_table_cell(issue["problem"]),
                suggestion=escape_table_cell(issue["suggestion"]),
            )
        )

    lines.append("")
    return "\n".join(lines)


def review_file(md_path: Path, force: bool = False) -> None:
    """审查单个中文 Markdown 文件并写出报告。"""
    out_path = report_path_for(md_path)
    if out_path.exists() and not force:
        print(f"  跳过（已存在）: {out_path.name}")
        return

    text = md_path.read_text(encoding="utf-8")
    chunks = split_numbered_markdown(text)
    total = len(chunks)
    collected: list[dict[str, object]] = []

    print(f"  共 {total} 段，{MAX_WORKERS} 线程并发审查...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(call_api, REVIEW_PROMPT, chunk): index
            for index, chunk in enumerate(chunks, start=1)
        }
        done = 0
        for future in as_completed(futures):
            chunk_index = futures[future]
            response_text = future.result()
            chunk_issues = parse_issues(response_text)
            collected.extend(chunk_issues)
            done += 1
            print(f"    完成 {done}/{total}（第 {chunk_index} 段）")

    issues = unique_issues(collected)
    out_path.write_text(render_report(md_path, issues), encoding="utf-8")
    print(f"  已保存: {out_path.name}")


def main():
    args = parse_args()

    if not API_KEY:
        print("错误: 请设置环境变量 ANTHROPIC_AUTH_TOKEN")
        return

    try:
        md_files = resolve_input_files(args.input)
    except Exception as exc:
        print(f"错误: {exc}")
        return

    skipped_reports: list[Path] = []
    if not args.force:
        pending_files: list[Path] = []
        for md_path in md_files:
            out_path = report_path_for(md_path)
            if out_path.exists():
                skipped_reports.append(out_path)
            else:
                pending_files.append(md_path)
        md_files = pending_files

    if not md_files:
        if skipped_reports:
            if args.input:
                print(f"跳过（报告已存在）: {skipped_reports[0].name}，使用 --force 可重新生成。")
            else:
                print(f"所有报告均已存在，使用 --force 可重新生成，共跳过 {len(skipped_reports)} 个文件。")
        else:
            print(f"未找到待审查的 *-cn.md 文件: {INPUT_DIR}")
        return

    print(f"找到 {len(md_files)} 个文件待审查\n")
    for md_path in md_files:
        print(f"审查: {md_path.name}")
        review_file(md_path, force=args.force)
        print()

    print("全部完成。")


if __name__ == "__main__":
    main()
