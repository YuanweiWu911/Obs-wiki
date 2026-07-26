"""
论文知识点梳理脚本
同时读取 ./markdown/*.md 和 ./markdown/*-cn.md，生成中英文双版本知识总结到 ./knowledge/。
"""
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
OUTPUT_DIR = Path("./knowledge")
MAX_WORKERS = 6

OUTPUT_DIR.mkdir(exist_ok=True)

_proxy_fallback_notice_lock = threading.Lock()
_proxy_fallback_notice_printed = False

# ---- 中文 Prompt ----
EXTRACT_PROMPT_CN = """你是一个学术论文分析专家。请从以下论文片段中提取关键知识点，以结构化列表输出。

要求：
- 每条知识点用一句话概括核心概念/方法/结论
- 包含方法名称、关键公式/参数、性能数据等定量信息
- 按以下分类组织：

## 研究背景与问题
- ...

## 核心方法
- ...

## 关键公式与参数
- ...

## 实验设计与数据
- ...

## 主要结果与性能
- ...

## 重要结论
- ...

只输出结构化知识列表，不要输出其他内容。"""

AGGREGATE_PROMPT_CN = """你是一个学术论文分析专家。以下是从一篇论文各章节提取的知识点片段，请将它们整合为一份完整的中文结构化知识总结。

要求：
1. 去重合并，相同或相似的知识点合并为一条
2. 按以下结构组织（用中文撰写）：

# 论文知识总结

## 一、研究背景与问题
（论文要解决什么问题？现有方法有什么不足？）

## 二、核心方法
（论文提出的方法是什么？原理是什么？相比现有方法有什么创新？）

## 三、关键技术细节
（公式、参数设置、数据处理方式等）

## 四、实验设计
（用什么数据验证？对比了哪些方法？评估指标是什么？）

## 五、实验结果
（主要性能数据，包含定量对比）

## 六、结论与贡献
（论文的核心贡献和结论）

只输出整理后的知识总结，不要添加额外说明。"""

# ---- English Prompt ----
EXTRACT_PROMPT_EN = """You are an academic paper analysis expert. Extract key knowledge points from the following paper excerpt and output as a structured list.

Requirements:
- Each point summarizes a core concept/method/conclusion in one sentence
- Include quantitative information such as method names, key formulas/parameters, performance data
- Organize by the following categories:

## Research Background & Problem
- ...

## Core Methodology
- ...

## Key Formulas & Parameters
- ...

## Experimental Design & Data
- ...

## Main Results & Performance
- ...

## Key Conclusions
- ...

Output only the structured knowledge list, nothing else."""

AGGREGATE_PROMPT_EN = """You are an academic paper analysis expert. Below are knowledge point fragments extracted from a paper's sections. Integrate them into a complete, structured English knowledge summary.

Requirements:
1. Deduplicate and merge similar points
2. Organize by the following structure (write in English):

# Paper Knowledge Summary

## 1. Research Background & Problem
(What problem does the paper solve? What are the shortcomings of existing methods?)

## 2. Core Methodology
(What method does the paper propose? What is the principle? What innovations compared to existing methods?)

## 3. Key Technical Details
(Formulas, parameter settings, data processing methods, etc.)

## 4. Experimental Design
(What data was used for validation? What methods were compared? What evaluation metrics?)

## 5. Experimental Results
(Main performance data with quantitative comparisons)

## 6. Conclusions & Contributions
(Core contributions and conclusions of the paper)

Output only the organized knowledge summary, nothing else."""


def normalize_doc_stem(stem: str) -> str:
    """移除文档语言后缀，得到中英文共用的基名。"""
    if stem.endswith("-en") or stem.endswith("-cn"):
        return stem[:-3]
    return stem


def split_markdown(text: str, max_chars: int = 4000) -> list[str]:
    """将 markdown 按段落/标题分块。"""
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


def extract_from_files(en_path: Path, cn_path: Path) -> str:
    """同时从英文原文和中文翻译中提取知识点，合并去重后得到原始知识片段。"""
    en_text = en_path.read_text(encoding="utf-8")
    cn_text = cn_path.read_text(encoding="utf-8")

    # 中英文各自分块，中文用中文 prompt，英文用英文 prompt
    en_chunks = split_markdown(en_text, max_chars=4000)
    cn_chunks = split_markdown(cn_text, max_chars=4000)

    total_en = len(en_chunks)
    total_cn = len(cn_chunks)

    print(f"  英文 {total_en} 段 + 中文 {total_cn} 段，并发提取...")

    all_results = [None] * (total_en + total_cn)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        # 英文 chunks
        for idx, chunk in enumerate(en_chunks):
            futures[executor.submit(call_api, EXTRACT_PROMPT_EN, chunk)] = idx
        # 中文 chunks
        for idx, chunk in enumerate(cn_chunks):
            futures[executor.submit(call_api, EXTRACT_PROMPT_CN, chunk)] = total_en + idx

        done = 0
        for future in as_completed(futures):
            idx = futures[future]
            all_results[idx] = future.result()
            done += 1
            print(f"    提取完成 {done}/{total_en + total_cn}")

    return "\n\n".join(r for r in all_results if r)


def aggregate_knowledge(raw_knowledge: str, lang: str) -> str:
    """将原始知识点整合为指定语言的结构化总结。"""
    prompt = AGGREGATE_PROMPT_CN if lang == "cn" else AGGREGATE_PROMPT_EN
    label = "中文" if lang == "cn" else "英文"
    print(f"  正在整合{label}知识总结...", end=" ", flush=True)

    if len(raw_knowledge) > 30000:
        chunk_size = 30000
        chunks = [raw_knowledge[i:i + chunk_size] for i in range(0, len(raw_knowledge), chunk_size)]
        partials = []
        for chunk in chunks:
            result = call_api(prompt, chunk)
            partials.append(result)
        combined = "\n\n".join(partials)
        result = call_api(prompt, f"请再次整合以下已部分汇总的知识点：\n\n{combined}")
    else:
        result = call_api(prompt, raw_knowledge)
    print("完成")
    return result


def process_pair(en_path: Path, cn_path: Path):
    """处理一对英文原文+中文翻译，生成中英文双版本知识总结。"""
    base_name = normalize_doc_stem(en_path.stem)
    out_cn = OUTPUT_DIR / f"{base_name}_knowledge_cn.md"
    out_en = OUTPUT_DIR / f"{base_name}_knowledge_en.md"

    # 增量跳过：两个输出都已存在则跳过
    skip_cn = out_cn.exists()
    skip_en = out_en.exists()
    if skip_cn and skip_en:
        print(f"  跳过（已存在）: {out_cn.name}, {out_en.name}")
        return

    # 第一步：从双语文档提取原始知识点
    raw = extract_from_files(en_path, cn_path)

    # 第二步：分别生成中英文总结（并发）
    tasks = []
    if not skip_cn:
        tasks.append(("cn", out_cn))
    if not skip_en:
        tasks.append(("en", out_en))

    with ThreadPoolExecutor(max_workers=2) as executor:
        lang_futures = {
            executor.submit(aggregate_knowledge, raw, lang): (lang, out_path)
            for lang, out_path in tasks
        }
        for future in as_completed(lang_futures):
            lang, out_path = lang_futures[future]
            result = future.result()
            out_path.write_text(result, encoding="utf-8")
            print(f"  已保存: {out_path.name}")


def main():
    if not API_KEY:
        print("错误: 请设置环境变量 ANTHROPIC_AUTH_TOKEN")
        return

    en_files = {
        normalize_doc_stem(f.stem): f
        for f in INPUT_DIR.glob("*-en.md")
        if "knowledge" not in f.stem
    }
    cn_files = {
        normalize_doc_stem(f.stem): f
        for f in INPUT_DIR.glob("*-cn.md")
        if "knowledge" not in f.stem
    }

    pairs = []
    for stem, en_path in en_files.items():
        if stem in cn_files:
            pairs.append((en_path, cn_files[stem]))
        else:
            print(f"警告: {en_path.name} 未找到对应的 -cn 翻译文件")

    if not pairs:
        print("未找到可处理的文件对")
        return

    print(f"找到 {len(pairs)} 个文件对\n")
    for en_path, cn_path in pairs:
        print(f"处理: {en_path.name}")
        process_pair(en_path, cn_path)
        print()

    print("全部完成。")


if __name__ == "__main__":
    main()
