"""
论文 Markdown 翻译脚本
读取 ./markdown/*.md，翻译为中文，输出 ./markdown/*-cn.md
"""
import argparse
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
OUTPUT_SUFFIX = "-cn"
MAX_WORKERS = 6

_proxy_fallback_notice_lock = threading.Lock()
_proxy_fallback_notice_printed = False

TRANSLATE_PROMPT = """你是一个专业学术论文翻译引擎。将以下英文 Markdown 文本翻译为中文。
要求：
- Markdown 格式（标题、列表、表格、公式、引用等）原样保留
- 专业术语翻译准确
- 只输出翻译结果，不要添加任何解释"""


def split_markdown(text: str, max_chars: int = 3000) -> list[str]:
    """将 markdown 按段落/标题分块，每块不超过 max_chars。"""
    lines = text.split("\n")
    chunks = []
    current = []
    current_len = 0

    for line in lines:
        if re.match(r"^#{1,3}\s", line) and current_len > 500:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
        if current_len >= max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

    if current:
        chunks.append("\n".join(current))
    return chunks


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
            r = post_with_proxy_fallback(headers=headers, data=data, timeout=120)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                return content.strip() if content else ""
            else:
                raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"  API 调用失败 (第 {attempt + 1}/{retries} 次): {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def resolve_input_files(single_input: str | None) -> list[Path]:
    """解析命令行输入，返回待翻译文件列表。"""
    if single_input:
        md_path = Path(single_input)
        if not md_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {md_path}")
        return [md_path]

    return sorted(INPUT_DIR.glob("*-en.md"))


def get_output_path(md_path: Path) -> Path:
    """根据输入 Markdown 计算中文输出文件路径。"""
    base = md_path.stem
    if base.endswith("-en"):
        base = base[:-3]
    return md_path.parent / f"{base}{OUTPUT_SUFFIX}.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="读取 Markdown 并翻译为中文版本。")
    parser.add_argument(
        "--input",
        help="指定单个 Markdown 文件作为输入。",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        default=False,
        help="不检查输出是否已存在，强制重新翻译。",
    )
    return parser.parse_args()


def translate_file(md_path: Path, force: bool = False):
    """翻译单个 markdown 文件（多线程并发）。"""
    out_path = get_output_path(md_path)
    if out_path.exists() and not force:
        print(f"  跳过（已存在）: {out_path.name}")
        return

    text = md_path.read_text(encoding="utf-8")
    chunks = split_markdown(text)
    total = len(chunks)
    translated = [None] * total

    print(f"  共 {total} 段，{MAX_WORKERS} 线程并发翻译...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(call_api, TRANSLATE_PROMPT, chunk): idx
            for idx, chunk in enumerate(chunks)
        }
        done = 0
        for future in as_completed(futures):
            idx = futures[future]
            translated[idx] = future.result()
            done += 1
            print(f"    完成 {done}/{total}")

    out_path.write_text("\n\n".join(translated), encoding="utf-8")
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

    if not args.force:
        md_files = [
            f for f in md_files
            if not get_output_path(f).exists()
        ]
    if not md_files:
        print(f"未找到待翻译的 *-en.md 文件: {INPUT_DIR}")
        return

    print(f"找到 {len(md_files)} 个文件待翻译\n")
    for md_path in md_files:
        print(f"翻译: {md_path.name}")
        translate_file(md_path, force=args.force)
        print()

    print("全部完成。")


if __name__ == "__main__":
    main()
