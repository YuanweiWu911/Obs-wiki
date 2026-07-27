"""
使用 LLM 审查自动生成的 Obsidian concepts，并缓存保留/删除决策。

用途：
1. 独立运行，审查当前 concepts 候选并输出汇总
2. 供 build_obsidian_wiki.py 调用，在构建阶段自动过滤错误 concepts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parent
STATE_PATH = ROOT_DIR / ".concept_review_state.json"
BLACKLIST_PATH = ROOT_DIR / ".concept_review_blacklist.json"

API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN")
BASE_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
PROXY_MODE = os.environ.get("DEEPSEEK_PROXY_MODE", "auto").lower()

_proxy_fallback_notice_lock = threading.Lock()
_proxy_fallback_notice_printed = False

SYSTEM_PROMPT = """你是学术知识库的概念质检员，负责审查自动提取的缩写或术语是否适合作为稳定 concept 卡片保留。

保留 keep 的条件：
- 它是领域内稳定、可复用、跨论文语义一致的概念或缩写
- 即使较短，只要语义单一且明确，也可以保留（例如 LOD、J2、EOP）

删除 drop 的条件：
- 只是公式变量、参数符号、局部记号、方程编号、附录编号
- 同名多义缩写，把不同概念混成一张卡片
- 只是国家名、地名、文件名、模型分辨率标签、单篇论文内部自定义记号
- 过短缩写且证据显示语义不稳定，例如 SH 同时表示 shear-horizontal 和 spherical harmonic

只输出 JSON，不要输出解释文本，不要使用 Markdown 代码块。
JSON 格式必须严格为：
{"decision":"keep|drop","reason":"一句中文理由","confidence":"high|medium|low"}"""

FORCE_KEEP_CONCEPTS = {
    "LS": "LS 在当前语料中稳定表示最小二乘（least squares），应保留。",
    "UT": "UT 是世界时（Universal Time）的标准时间尺度缩写，应保留。",
    "TT": "TT 是地球时（Terrestrial Time）的标准时间尺度缩写，应保留。",
    "RMS": "RMS 是均方根（root mean square）的稳定统计指标缩写，应保留。",
}

FORCE_DROP_CONCEPTS = {
    "S1": "S1 仅为两字母短缩写，且当前证据混合内核相关局部表述，不作为稳定 concept 保留。",
    "IC": "IC 仅为两字母短缩写，且当前证据混合内核相关局部表述，不作为稳定 concept 保留。",
    "DF": "DF 仅为两字母震相分支缩写，过短且跨文献泛化能力弱，不作为稳定 concept 保留。",
}

SHORT_CONCEPT_FOCUS_LENGTH = 2
SHORT_CONCEPT_FOCUS_MAX_PAPERS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 LLM 审查自动生成的 concepts。")
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略缓存，强制重新审查所有 concepts。",
    )
    parser.add_argument(
        "--show-dropped",
        action="store_true",
        help="打印被判定为 drop 的 concept 及理由。",
    )
    return parser.parse_args()


def current_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_session(use_env_proxy: bool) -> requests.Session:
    session = requests.Session()
    session.trust_env = use_env_proxy
    return session


def post_with_proxy_fallback(headers: dict, data: dict, timeout: int):
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
                print("  检测到代理不可用，概念审查自动切换为直连...")
                _proxy_fallback_notice_printed = True
        with create_session(use_env_proxy=False) as session:
            return session.post(BASE_URL, headers=headers, json=data, timeout=timeout)


def call_api(system_prompt: str, user_content: str, retries: int = 3) -> str:
    if not API_KEY:
        raise RuntimeError("未设置环境变量 ANTHROPIC_AUTH_TOKEN，无法执行 LLM 概念审查。")

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
        "temperature": 0.0,
        "max_tokens": 512,
    }

    for attempt in range(retries):
        try:
            response = post_with_proxy_fallback(headers=headers, data=data, timeout=120)
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                return content.strip() if content else ""
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        except Exception as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"概念审查 API 调用失败: {exc}") from exc
            time.sleep(2 ** attempt)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_string_list(values) -> list[str]:
    if not values:
        return []
    return [str(item) for item in values if str(item).strip()]


def concept_payload(concept_name: str, concept_record: dict[str, object]) -> dict[str, object]:
    return {
        "concept": concept_name,
        "concept_length": len(concept_name),
        "is_short_concept": len(concept_name) <= SHORT_CONCEPT_FOCUS_LENGTH,
        "aliases": sorted(normalize_string_list(concept_record.get("aliases"))),
        "paper_count": len(set(normalize_string_list(concept_record.get("papers")))),
        "papers": sorted(normalize_string_list(concept_record.get("papers")))[:8],
        "evidence": normalize_string_list(concept_record.get("evidence"))[:5],
    }


def concept_fingerprint(concept_name: str, concept_record: dict[str, object]) -> str:
    payload = concept_payload(concept_name, concept_record)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_user_prompt(concept_name: str, concept_record: dict[str, object]) -> str:
    payload = concept_payload(concept_name, concept_record)
    extra_rule = ""
    if (
        len(concept_name) <= SHORT_CONCEPT_FOCUS_LENGTH
        and payload["paper_count"] <= SHORT_CONCEPT_FOCUS_MAX_PAPERS
    ):
        extra_rule = (
            "\n额外规则：该缩写非常短，且 Related Papers 较少。"
            "除非它是公认的标准时间尺度、统计方法或跨论文稳定术语，否则应倾向判定为 drop。"
        )
    return (
        "请判断以下自动生成 concept 是否应保留在学术知识库中。\n"
        "重点关注是否属于稳定领域概念，还是只是局部缩写、参数符号、编号或混义缩写。"
        f"{extra_rule}\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def extract_json_object(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"无法从 LLM 响应中提取 JSON: {text}")
    return cleaned[start : end + 1]


def normalize_decision(value: str) -> str:
    decision = value.strip().lower()
    if decision in {"keep", "retain", "preserve"}:
        return "keep"
    if decision in {"drop", "remove", "reject", "delete"}:
        return "drop"
    raise ValueError(f"未知 decision: {value}")


def parse_review_response(text: str) -> dict[str, str]:
    obj = json.loads(extract_json_object(text))
    decision = normalize_decision(str(obj.get("decision", "")).strip())
    reason = str(obj.get("reason", "")).strip() or "LLM 未提供理由"
    confidence = str(obj.get("confidence", "medium")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return {
        "decision": decision,
        "reason": reason,
        "confidence": confidence,
    }


def local_policy_review(concept_name: str) -> dict[str, str] | None:
    if concept_name in FORCE_KEEP_CONCEPTS:
        return {
            "decision": "keep",
            "reason": FORCE_KEEP_CONCEPTS[concept_name],
            "confidence": "high",
            "model": "local-policy",
            "reviewed_at": current_timestamp(),
        }
    if concept_name in FORCE_DROP_CONCEPTS:
        return {
            "decision": "drop",
            "reason": FORCE_DROP_CONCEPTS[concept_name],
            "confidence": "high",
            "model": "local-policy",
            "reviewed_at": current_timestamp(),
        }
    return None


def review_concept(concept_name: str, concept_record: dict[str, object]) -> dict[str, str]:
    response = call_api(SYSTEM_PROMPT, build_user_prompt(concept_name, concept_record))
    result = parse_review_response(response)
    result["model"] = MODEL
    result["reviewed_at"] = current_timestamp()
    return result


def load_review_state() -> dict[str, object]:
    return load_json(
        STATE_PATH,
        {
            "updated_at": "",
            "model": MODEL,
            "concepts": {},
        },
    )


def save_review_state(state: dict[str, object]):
    state["updated_at"] = current_timestamp()
    state["model"] = MODEL
    write_json(STATE_PATH, state)


def write_blacklist_snapshot(state: dict[str, object]):
    concepts = state.get("concepts", {})
    dropped = {
        concept_name: {
            "reason": concept_state.get("reason", ""),
            "confidence": concept_state.get("confidence", "medium"),
            "reviewed_at": concept_state.get("reviewed_at", ""),
            "fingerprint": concept_state.get("fingerprint", ""),
        }
        for concept_name, concept_state in sorted(concepts.items())
        if concept_state.get("decision") == "drop"
    }
    write_json(
        BLACKLIST_PATH,
        {
            "updated_at": current_timestamp(),
            "count": len(dropped),
            "concepts": dropped,
        },
    )


def review_concept_inventory(
    concept_inventory: dict[str, dict[str, object]],
    *,
    force: bool = False,
    verbose: bool = True,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, str]]]:
    state = load_review_state()
    concept_state = state.setdefault("concepts", {})
    approved: dict[str, dict[str, object]] = {}
    rejected: dict[str, dict[str, str]] = {}

    for concept_name in sorted(concept_inventory):
        fingerprint = concept_fingerprint(concept_name, concept_inventory[concept_name])
        cached = concept_state.get(concept_name, {})
        local_result = local_policy_review(concept_name)
        use_cached = (
            local_result is None
            and not force
            and cached.get("fingerprint") == fingerprint
            and cached.get("decision") in {"keep", "drop"}
        )

        if local_result is not None:
            result = dict(local_result)
            result["fingerprint"] = fingerprint
            concept_state[concept_name] = result
        elif use_cached:
            result = cached
        elif API_KEY:
            try:
                if verbose:
                    print(f"  LLM 审查 concept: {concept_name}")
                result = review_concept(concept_name, concept_inventory[concept_name])
                result["fingerprint"] = fingerprint
                concept_state[concept_name] = result
            except Exception as exc:
                if cached.get("decision") in {"keep", "drop"}:
                    result = dict(cached)
                    result["reason"] = str(cached.get("reason", "")) or f"沿用历史审查结果：{exc}"
                    result["fingerprint"] = fingerprint
                    result["reviewed_at"] = current_timestamp()
                    result["model"] = str(cached.get("model", MODEL))
                    concept_state[concept_name] = result
                    if verbose:
                        print(f"  LLM 审查失败，沿用缓存: {concept_name}")
                else:
                    result = {
                        "decision": "keep",
                        "reason": f"LLM 审查失败，默认保留：{exc}",
                        "confidence": "low",
                        "reviewed_at": current_timestamp(),
                        "fingerprint": fingerprint,
                        "model": MODEL,
                    }
                    concept_state[concept_name] = result
                    if verbose:
                        print(f"  LLM 审查失败，默认保留: {concept_name}")
        elif cached.get("decision") in {"keep", "drop"}:
            result = dict(cached)
            result["fingerprint"] = fingerprint
            concept_state[concept_name] = result
        else:
            result = {
                "decision": "keep",
                "reason": "未配置 API Key，且无历史审查缓存，默认保留。",
                "confidence": "low",
                "reviewed_at": current_timestamp(),
                "fingerprint": fingerprint,
                "model": MODEL,
            }
            concept_state[concept_name] = result

        if result.get("decision") == "drop":
            rejected[concept_name] = {
                "reason": str(result.get("reason", "")),
                "confidence": str(result.get("confidence", "medium")),
            }
        else:
            approved[concept_name] = concept_inventory[concept_name]

    # 保留历史记录，但同步写入最新快照。
    save_review_state(state)
    write_blacklist_snapshot(state)
    return approved, rejected


def apply_llm_concept_review(
    paper_concepts: dict[str, list[str]],
    concept_inventory: dict[str, dict[str, object]],
    *,
    force: bool = False,
    verbose: bool = True,
) -> tuple[dict[str, list[str]], dict[str, dict[str, object]], dict[str, dict[str, str]]]:
    approved_inventory, rejected = review_concept_inventory(
        concept_inventory,
        force=force,
        verbose=verbose,
    )
    allowed = set(approved_inventory)
    filtered_paper_concepts = {
        base_name: [concept for concept in concepts if concept in allowed]
        for base_name, concepts in paper_concepts.items()
    }
    return filtered_paper_concepts, approved_inventory, rejected


def main() -> int:
    args = parse_args()

    import build_obsidian_wiki as wiki

    records = wiki.gather_records()
    paper_concepts, concept_inventory = wiki.build_concept_inventory(records)
    filtered_paper_concepts, approved_inventory, rejected = apply_llm_concept_review(
        paper_concepts,
        concept_inventory,
        force=args.force,
        verbose=True,
    )

    print(f"候选 concepts: {len(concept_inventory)}")
    print(f"保留 concepts: {len(approved_inventory)}")
    print(f"删除 concepts: {len(rejected)}")
    print(f"涉及论文: {sum(1 for concepts in filtered_paper_concepts.values() if concepts)}")

    if args.show_dropped and rejected:
        print("\n被删除的 concepts：")
        for concept_name in sorted(rejected):
            info = rejected[concept_name]
            print(f"- {concept_name}: {info['reason']} ({info['confidence']})")

    print(f"\n审查缓存: {STATE_PATH.name}")
    print(f"删除快照: {BLACKLIST_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
