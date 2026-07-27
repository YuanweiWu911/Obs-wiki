"""
绕过系统代理运行 DeepSeek 相关脚本。

用法示例：
    python run_without_proxy.py en2cn.py
    python run_without_proxy.py knowledge.py
    python run_without_proxy.py --model deepseek-v4-pro en2cn.py
    python run_without_proxy.py -- python en2cn.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROXY_ENV_VARS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]

DIRECT_HOSTS = ["api.deepseek.com", "deepseek.com"]


def build_env(model: str | None) -> dict[str, str]:
    """构造不走代理的子进程环境变量。"""
    env = os.environ.copy()

    for key in PROXY_ENV_VARS:
        env.pop(key, None)

    current_no_proxy = env.get("NO_PROXY") or env.get("no_proxy") or ""
    no_proxy_items = [item.strip() for item in current_no_proxy.split(",") if item.strip()]
    merged_no_proxy = []
    seen = set()

    for host in no_proxy_items + DIRECT_HOSTS:
        if host not in seen:
            merged_no_proxy.append(host)
            seen.add(host)

    no_proxy_value = ",".join(merged_no_proxy)
    env["NO_PROXY"] = no_proxy_value
    env["no_proxy"] = no_proxy_value
    env["DEEPSEEK_PROXY_MODE"] = "off"

    if model:
        env["DEEPSEEK_MODEL"] = model

    return env


def normalize_command(raw_command: list[str]) -> list[str]:
    """将目标命令规范化为可执行命令。"""
    if not raw_command:
        raise ValueError("请提供要运行的脚本或命令。")

    first = raw_command[0]
    first_path = Path(first)
    if first_path.suffix.lower() == ".py":
        return [sys.executable, *raw_command]
    return raw_command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="绕过代理运行 Python 脚本或任意命令。")
    parser.add_argument(
        "--model",
        help="可选，覆盖 DEEPSEEK_MODEL，例如 deepseek-v4-flash 或 deepseek-v4-pro。",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="要执行的脚本或命令。示例：en2cn.py 或 -- python en2cn.py",
    )
    args = parser.parse_args()

    if args.command and args.command[0] == "--":
        args.command = args.command[1:]

    if not args.command:
        parser.error("请提供要运行的脚本或命令，例如：python run_without_proxy.py en2cn.py")

    return args


def main() -> int:
    args = parse_args()
    command = normalize_command(args.command)
    env = build_env(args.model)

    print("已启用直连模式：清除 HTTP(S)_PROXY/ALL_PROXY，并设置 DEEPSEEK_PROXY_MODE=off")
    print(f"NO_PROXY={env['NO_PROXY']}")
    print(f"执行命令：{' '.join(command)}")

    completed = subprocess.run(command, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
