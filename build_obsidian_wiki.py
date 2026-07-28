"""
为当前仓库自动搭建 Obsidian LLM wiki。

执行后会创建：
- .obsidian/ 基础配置
- notes/papers/ 论文聚合笔记
- concepts/ 概念卡片目录
- maps/ 导航与索引页
- templates/ 中英双语模板

支持：
- 全量刷新
- 只更新受影响论文
- 监听 pdf/、markdown/、knowledge/ 目录变化并自动刷新
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from collections import Counter

from review_concepts_with_llm import apply_llm_concept_review

ROOT_DIR = Path(__file__).resolve().parent
PDF_DIR = ROOT_DIR / "pdf"
MARKDOWN_DIR = ROOT_DIR / "markdown"
KNOWLEDGE_DIR = ROOT_DIR / "knowledge"

OBSIDIAN_DIR = ROOT_DIR / ".obsidian"
NOTES_DIR = ROOT_DIR / "notes"
PAPERS_DIR = NOTES_DIR / "papers"
CONCEPTS_DIR = ROOT_DIR / "concepts"
MAPS_DIR = ROOT_DIR / "maps"
TEMPLATES_DIR = ROOT_DIR / "templates"

AUTO_START = "<!-- AUTO-GENERATED START -->"
AUTO_END = "<!-- AUTO-GENERATED END -->"
DEFAULT_INTERVAL = 5.0
MANUAL_SECTION = """## Notes / 研究笔记

## Related Concepts / 相关概念

"""
CONCEPT_MANUAL_SECTION = """## Notes / 备注

"""
ACRONYM_BLACKLIST = {
    "A1",
    "CN",
    "BC",
    "EN",
    "PDF",
    "OCR",
    "README",
    "AUTO",
    "START",
    "END",
    "SSI",
    "SV",
    "RUSSIA",
    "GM",
    "MR",
}
CONCEPT_CANONICAL_MAP = {
    "EOPS": "EOP",
}
CONCEPT_BLACKLIST_PATTERNS = [
    re.compile(r"^IMF\d+$"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自动搭建并刷新 Obsidian LLM wiki。")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="持续监听 pdf/、markdown/、knowledge/ 的变化并自动刷新。",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"监听模式下的轮询间隔（秒），默认 {DEFAULT_INTERVAL}。",
    )
    parser.add_argument(
        "--skip-llm-concept-review",
        action="store_true",
        help="跳过基于 LLM 的 concept 质检，仅使用本地规则生成概念。",
    )
    parser.add_argument(
        "--force-llm-concept-review",
        action="store_true",
        help="忽略 concept 审查缓存，强制重新进行 LLM 审查。",
    )
    return parser.parse_args()


def ensure_dirs():
    for path in [
        OBSIDIAN_DIR,
        NOTES_DIR,
        PAPERS_DIR,
        CONCEPTS_DIR,
        MAPS_DIR,
        TEMPLATES_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def write_text_if_changed(path: Path, content: str):
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.write_text(content, encoding="utf-8")


def extract_year(stem: str) -> str:
    match = re.search(r"(19|20)\d{2}", stem)
    return match.group(0) if match else ""


def slug_from_stem(stem: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()
    return slug or "paper"


def normalize_doc_stem(stem: str) -> str:
    if stem.endswith("-en") or stem.endswith("-cn"):
        return stem[:-3]
    if stem.endswith("_knowledge_cn"):
        return stem[: -len("_knowledge_cn")]
    if stem.endswith("_knowledge_en"):
        return stem[: -len("_knowledge_en")]
    return stem


def gather_records() -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}

    def ensure_record(base_name: str) -> dict[str, str]:
        if base_name not in records:
            records[base_name] = {
                "pdf": "",
                "en_markdown": "",
                "cn_markdown": "",
                "knowledge_cn": "",
                "knowledge_en": "",
            }
        return records[base_name]

    for pdf_path in sorted(PDF_DIR.glob("*.pdf")):
        ensure_record(pdf_path.stem)["pdf"] = pdf_path.name

    for md_path in sorted(MARKDOWN_DIR.glob("*.md")):
        stem = md_path.stem
        if "knowledge" in stem:
            continue
        if stem.endswith("-en"):
            ensure_record(normalize_doc_stem(stem))["en_markdown"] = md_path.name
        elif stem.endswith("-cn"):
            ensure_record(normalize_doc_stem(stem))["cn_markdown"] = md_path.name

    for knowledge_path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        stem = knowledge_path.stem
        if stem.endswith("_knowledge_cn"):
            ensure_record(normalize_doc_stem(stem))["knowledge_cn"] = knowledge_path.name
        elif stem.endswith("_knowledge_en"):
            ensure_record(normalize_doc_stem(stem))["knowledge_en"] = knowledge_path.name

    return records


def yaml_bool(value: bool) -> str:
    return "true" if value else "false"


def current_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_link(prefix: str, folder: str, file_name: str) -> str:
    if not file_name:
        return f"- {prefix}: missing"
    return f"- {prefix}: [[{folder}/{file_name}]]"


def format_note_link(folder: str, note_name: str, label: str | None = None) -> str:
    if label and label != note_name:
        return f"[[{folder}/{note_name}|{label}]]"
    return f"[[{folder}/{note_name}]]"


def sanitize_note_name(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\\\|?*]+', "-", name).strip()
    return sanitized or "untitled"


def build_frontmatter(base_name: str, record: dict[str, str], concepts: list[str]) -> str:
    year = extract_year(base_name)
    slug = slug_from_stem(base_name)
    concept_json = json.dumps(concepts, ensure_ascii=False)
    lines = [
        "---",
        f'title: "{base_name}"',
        'type: "paper-note"',
        f'paper_id: "{slug}"',
        f'year: "{year}"',
        'tags: ["paper", "llm-wiki"]',
        f"concepts: {concept_json}",
        f'has_pdf: {yaml_bool(bool(record["pdf"]))}',
        f'has_en_markdown: {yaml_bool(bool(record["en_markdown"]))}',
        f'has_cn_markdown: {yaml_bool(bool(record["cn_markdown"]))}',
        f'has_knowledge_cn: {yaml_bool(bool(record["knowledge_cn"]))}',
        f'has_knowledge_en: {yaml_bool(bool(record["knowledge_en"]))}',
        f'wiki_last_built: "{current_timestamp()}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def build_concept_links(concepts: list[str]) -> list[str]:
    return [f"- {format_note_link('concepts', sanitize_note_name(concept), concept)}" for concept in concepts]


def build_auto_block(base_name: str, record: dict[str, str], concepts: list[str]) -> str:
    lines = [
        AUTO_START,
        f"# {base_name}",
        "",
        "## Overview / 概览",
        f"- PDF: {'yes' if record['pdf'] else 'no'}",
        f"- English Markdown: {'yes' if record['en_markdown'] else 'no'}",
        f"- Chinese Markdown: {'yes' if record['cn_markdown'] else 'no'}",
        f"- Knowledge CN: {'yes' if record['knowledge_cn'] else 'no'}",
        f"- Knowledge EN: {'yes' if record['knowledge_en'] else 'no'}",
        "",
        "## Sources / 原始资料",
        format_link("PDF", "pdf", record["pdf"]),
        format_link("English Markdown", "markdown", record["en_markdown"]),
        format_link("Chinese Markdown", "markdown", record["cn_markdown"]),
        "",
        "## Knowledge / 知识总结",
        format_link("Knowledge CN", "knowledge", record["knowledge_cn"]),
        format_link("Knowledge EN", "knowledge", record["knowledge_en"]),
        "",
        "## Auto Concepts / 自动识别概念",
    ]
    if concepts:
        lines.extend(build_concept_links(concepts))
    else:
        lines.append("- none detected")
    lines.extend(
        [
            "",
        AUTO_END,
        "",
        ]
    )
    return "\n".join(lines)


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text

    end_marker = text.find("\n---\n", 4)
    if end_marker == -1:
        return "", text

    frontmatter = text[: end_marker + 5]
    body = text[end_marker + 5 :]
    return frontmatter, body


def ensure_manual_sections(body: str, manual_heading: str, manual_section: str) -> str:
    if manual_heading in body:
        return body.lstrip("\n")

    stripped = body.strip()
    if not stripped:
        return manual_section

    return stripped + "\n\n" + manual_section


def replace_auto_block(body: str, auto_block: str, manual_heading: str, manual_section: str) -> str:
    body = body.lstrip("\n")
    if AUTO_START in body and AUTO_END in body:
        start_index = body.index(AUTO_START)
        end_index = body.index(AUTO_END) + len(AUTO_END)
        before = body[:start_index].rstrip()
        after = body[end_index:].lstrip("\n")

        parts: list[str] = []
        if before:
            parts.append(before)
        parts.append(auto_block.rstrip())
        if after:
            parts.append(after.rstrip())

        return "\n\n".join(parts) + "\n"

    parts = [auto_block.rstrip(), ensure_manual_sections(body, manual_heading, manual_section).rstrip()]
    return "\n\n".join(part for part in parts if part) + "\n"


def build_note_content(base_name: str, record: dict[str, str], concepts: list[str], existing_text: str = "") -> str:
    _, body = split_frontmatter(existing_text)
    auto_block = build_auto_block(base_name, record, concepts)
    updated_body = replace_auto_block(body, auto_block, "## Notes / 研究笔记", MANUAL_SECTION)
    updated_body = ensure_manual_sections(updated_body, "## Notes / 研究笔记", MANUAL_SECTION)
    content = build_frontmatter(base_name, record, concepts) + updated_body
    if not content.endswith("\n"):
        content += "\n"
    return content


def replace_or_prepend_auto_block(body: str, auto_block: str) -> str:
    body = body.lstrip("\n")
    if AUTO_START in body and AUTO_END in body:
        start_index = body.index(AUTO_START)
        end_index = body.index(AUTO_END) + len(AUTO_END)
        before = body[:start_index].rstrip()
        after = body[end_index:].lstrip("\n")

        parts: list[str] = []
        if before:
            parts.append(before)
        parts.append(auto_block.rstrip())
        if after:
            parts.append(after.rstrip())
        return "\n\n".join(parts) + "\n"

    if not body:
        return auto_block.rstrip() + "\n"

    return auto_block.rstrip() + "\n\n" + body.rstrip() + "\n"


def build_knowledge_auto_block(base_name: str, record: dict[str, str]) -> str:
    lines = [
        AUTO_START,
        f"# {base_name}",
        "",
        "## Sources / 原始资料",
        format_link("PDF", "pdf", record["pdf"]),
        f"- Paper Note: {format_note_link('notes/papers', base_name, base_name)}",
        "",
        AUTO_END,
        "",
    ]
    return "\n".join(lines)


def build_knowledge_content(base_name: str, record: dict[str, str], existing_text: str = "") -> str:
    auto_block = build_knowledge_auto_block(base_name, record)
    content = replace_or_prepend_auto_block(existing_text, auto_block)
    if not content.endswith("\n"):
        content += "\n"
    return content


def write_paper_notes(
    records: dict[str, dict[str, str]],
    paper_concepts: dict[str, list[str]],
    target_bases: set[str] | None = None,
):
    bases = sorted(target_bases) if target_bases else sorted(records)
    for base_name in bases:
        record = records.get(
            base_name,
            {
                "pdf": "",
                "en_markdown": "",
                "cn_markdown": "",
                "knowledge_cn": "",
                "knowledge_en": "",
            },
        )
        note_path = PAPERS_DIR / f"{base_name}.md"
        existing_text = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        concepts = paper_concepts.get(base_name, [])
        content = build_note_content(base_name, record, concepts, existing_text)
        write_text_if_changed(note_path, content)


def write_knowledge_links(
    records: dict[str, dict[str, str]],
    target_bases: set[str] | None = None,
):
    bases = sorted(target_bases) if target_bases else sorted(records)
    for base_name in bases:
        record = records.get(
            base_name,
            {
                "pdf": "",
                "en_markdown": "",
                "cn_markdown": "",
                "knowledge_cn": "",
                "knowledge_en": "",
            },
        )
        for key in ["knowledge_cn", "knowledge_en"]:
            file_name = record[key]
            if not file_name:
                continue
            knowledge_path = KNOWLEDGE_DIR / file_name
            existing_text = knowledge_path.read_text(encoding="utf-8") if knowledge_path.exists() else ""
            content = build_knowledge_content(base_name, record, existing_text)
            write_text_if_changed(knowledge_path, content)


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def canonicalize_concept(token: str) -> str:
    cleaned = token.strip().strip(".,;:()[]{}")
    if not cleaned:
        return ""
    cleaned = cleaned.replace("–", "-").replace("—", "-")
    if re.fullmatch(r"[A-Za-z]{1,3}[0-9]{1,3}", cleaned):
        concept = cleaned.upper()
        return CONCEPT_CANONICAL_MAP.get(concept, concept)
    if re.fullmatch(r"[A-Za-z0-9-]{2,12}", cleaned):
        concept = cleaned.upper()
        return CONCEPT_CANONICAL_MAP.get(concept, concept)
    return cleaned


def is_valid_alias(phrase: str, concept_name: str) -> bool:
    cleaned = re.sub(r"[*`_]", "", phrase).strip(" .,:;()[]{}")
    if not cleaned:
        return False
    if cleaned.upper() == concept_name:
        return False
    if any(char in cleaned for char in "\\="):
        return False
    if len(cleaned) > 40:
        return False
    if len(cleaned.split()) > 6:
        return False
    if re.search(r"[\u4e00-\u9fff]", cleaned):
        if " " in cleaned:
            return False
        if len(cleaned) > 12:
            return False
        if cleaned[0] in "的和与年及或在对将从按把被":
            return False
        if cleaned[-1] in "的和与":
            return False
    return True


def is_filtered_concept(concept_name: str) -> bool:
    if concept_name in ACRONYM_BLACKLIST:
        return True
    return any(pattern.fullmatch(concept_name) for pattern in CONCEPT_BLACKLIST_PATTERNS)


def is_acronym_token(token: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9-]{2,12}", token):
        return False
    upper_count = sum(1 for char in token if char.isupper())
    digit_count = sum(1 for char in token if char.isdigit())
    if upper_count >= 2:
        return True
    if upper_count >= 1 and digit_count >= 1:
        return True
    return False


def extract_explicit_concepts(text: str) -> list[tuple[str, str, str]]:
    explicit: list[tuple[str, str, str]] = []
    patterns = [
        re.compile(r"([A-Z][A-Za-z0-9'/-]*(?: [A-Z][A-Za-z0-9'/-]*){0,4}) \(([A-Za-z][A-Za-z0-9-]{1,11})\)"),
        re.compile(r"([\u4e00-\u9fff]{2,12})（([A-Za-z][A-Za-z0-9-]{1,11})）"),
    ]
    for line in text.splitlines():
        stripped = line.strip(" -\t")
        if not stripped:
            continue
        for pattern in patterns:
            for match in pattern.finditer(stripped):
                phrase = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;")
                acronym = canonicalize_concept(match.group(2))
                if not acronym or is_filtered_concept(acronym):
                    continue
                explicit.append((acronym, phrase, stripped))
    return explicit


def extract_acronym_candidates(text: str) -> tuple[Counter, dict[str, list[str]]]:
    counter: Counter = Counter()
    evidence: dict[str, list[str]] = {}
    token_pattern = re.compile(r"\b[A-Za-z][A-Za-z0-9-]{1,11}\b")
    for line in text.splitlines():
        stripped = line.strip(" -\t")
        if not stripped:
            continue
        for token in token_pattern.findall(stripped):
            if not is_acronym_token(token):
                continue
            concept = canonicalize_concept(token)
            if is_filtered_concept(concept):
                continue
            counter[concept] += 1
            evidence.setdefault(concept, [])
            if stripped not in evidence[concept] and len(evidence[concept]) < 3:
                evidence[concept].append(stripped)
    return counter, evidence


def build_concept_inventory(records: dict[str, dict[str, str]]) -> tuple[dict[str, list[str]], dict[str, dict[str, object]]]:
    paper_concepts: dict[str, list[str]] = {}
    concept_inventory: dict[str, dict[str, object]] = {}

    for base_name, record in records.items():
        texts = []
        if record["knowledge_cn"]:
            texts.append(load_text(KNOWLEDGE_DIR / record["knowledge_cn"]))
        if record["knowledge_en"]:
            texts.append(load_text(KNOWLEDGE_DIR / record["knowledge_en"]))
        combined_text = "\n".join(texts)
        if not combined_text.strip():
            paper_concepts[base_name] = []
            continue

        explicit_matches = extract_explicit_concepts(combined_text)
        acronym_counts, acronym_evidence = extract_acronym_candidates(combined_text)
        selected: dict[str, dict[str, object]] = {}

        for acronym, phrase, evidence_line in explicit_matches:
            selected.setdefault(acronym, {"aliases": set(), "evidence": []})
            alias_set = selected[acronym]["aliases"]
            assert isinstance(alias_set, set)
            if is_valid_alias(phrase, acronym):
                alias_set.add(phrase)
            evidence_list = selected[acronym]["evidence"]
            assert isinstance(evidence_list, list)
            if evidence_line not in evidence_list and len(evidence_list) < 3:
                evidence_list.append(evidence_line)

        for acronym, count in acronym_counts.items():
            if count < 2 and acronym not in selected:
                continue
            selected.setdefault(acronym, {"aliases": set(), "evidence": []})
            evidence_list = selected[acronym]["evidence"]
            assert isinstance(evidence_list, list)
            for evidence_line in acronym_evidence.get(acronym, []):
                if evidence_line not in evidence_list and len(evidence_list) < 3:
                    evidence_list.append(evidence_line)

        concept_names = sorted(selected)
        paper_concepts[base_name] = concept_names

        for concept_name in concept_names:
            concept_record = concept_inventory.setdefault(
                concept_name,
                {
                    "aliases": set(),
                    "papers": set(),
                    "evidence": [],
                },
            )
            aliases = concept_record["aliases"]
            papers = concept_record["papers"]
            evidence = concept_record["evidence"]
            assert isinstance(aliases, set)
            assert isinstance(papers, set)
            assert isinstance(evidence, list)
            aliases.update(selected[concept_name]["aliases"])
            papers.add(base_name)
            for evidence_line in selected[concept_name]["evidence"]:
                if evidence_line not in evidence and len(evidence) < 5:
                    evidence.append(evidence_line)

    filtered_inventory: dict[str, dict[str, object]] = {}
    for concept_name, concept_record in concept_inventory.items():
        aliases = {alias for alias in concept_record["aliases"] if is_valid_alias(alias, concept_name)}
        papers = concept_record["papers"]
        if is_filtered_concept(concept_name):
            continue
        ranked_aliases = sorted(aliases, key=lambda item: (len(item), item))[:3]
        aliases = set(ranked_aliases)
        if len(papers) < 5 and not (aliases and len(papers) >= 2):
            continue
        filtered_inventory[concept_name] = {
            "aliases": aliases,
            "papers": papers,
            "evidence": concept_record["evidence"],
        }

    filtered_paper_concepts: dict[str, list[str]] = {}
    for base_name, concepts in paper_concepts.items():
        filtered_paper_concepts[base_name] = [concept for concept in concepts if concept in filtered_inventory]

    return filtered_paper_concepts, filtered_inventory


def build_concept_frontmatter(concept_name: str, concept_record: dict[str, object]) -> str:
    aliases = sorted(alias for alias in concept_record["aliases"] if alias and alias != concept_name)
    alias_json = json.dumps(aliases, ensure_ascii=False)
    lines = [
        "---",
        f'title: "{concept_name}"',
        'type: "concept"',
        'tags: ["concept", "auto-generated"]',
        f"aliases: {alias_json}",
        f'paper_count: "{len(concept_record["papers"])}"',
        f'wiki_last_built: "{current_timestamp()}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def build_concept_auto_block(concept_name: str, concept_record: dict[str, object]) -> str:
    aliases = sorted(alias for alias in concept_record["aliases"] if alias and alias != concept_name)
    related_papers = sorted(concept_record["papers"])
    evidence_lines = concept_record["evidence"]
    lines = [
        AUTO_START,
        f"# {concept_name}",
        "",
        "## Overview / 概览",
        f'- Related Papers: {len(related_papers)}',
        f'- Aliases: {", ".join(aliases) if aliases else "none"}',
        "",
        "## Related Papers / 相关论文",
    ]
    if related_papers:
        lines.extend(
            f"- {format_note_link('notes/papers', paper_name, paper_name)}"
            for paper_name in related_papers
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Evidence / 自动提取线索"])
    if evidence_lines:
        lines.extend(f"- {line}" for line in evidence_lines)
    else:
        lines.append("- none")
    lines.extend(["", AUTO_END, ""])
    return "\n".join(lines)


def build_concept_note_content(concept_name: str, concept_record: dict[str, object], existing_text: str = "") -> str:
    _, body = split_frontmatter(existing_text)
    auto_block = build_concept_auto_block(concept_name, concept_record)
    updated_body = replace_auto_block(body, auto_block, "## Notes / 备注", CONCEPT_MANUAL_SECTION)
    updated_body = ensure_manual_sections(updated_body, "## Notes / 备注", CONCEPT_MANUAL_SECTION)
    content = build_concept_frontmatter(concept_name, concept_record) + updated_body
    if not content.endswith("\n"):
        content += "\n"
    return content


def write_concept_notes(concept_inventory: dict[str, dict[str, object]]):
    for concept_name in sorted(concept_inventory):
        note_name = sanitize_note_name(concept_name)
        note_path = CONCEPTS_DIR / f"{note_name}.md"
        existing_text = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        content = build_concept_note_content(concept_name, concept_inventory[concept_name], existing_text)
        write_text_if_changed(note_path, content)

    active_note_names = {sanitize_note_name(concept_name) for concept_name in concept_inventory}
    for note_path in CONCEPTS_DIR.glob("*.md"):
        if note_path.stem in active_note_names:
            continue
        text = note_path.read_text(encoding="utf-8")
        if 'type: "concept"' not in text or 'tags: ["concept", "auto-generated"]' not in text:
            continue
        manual_index = text.find("## Notes / 备注")
        if manual_index == -1:
            continue
        manual_tail = text[manual_index + len("## Notes / 备注"):].strip()
        if manual_tail:
            continue
        note_path.unlink()


def write_templates():
    write_text_if_changed(
        TEMPLATES_DIR / "paper_note.md",
        """---
title: "{{title}}"
type: "paper-note"
tags: ["paper", "llm-wiki"]
---

# {{title}}

## Overview / 概览

## Sources / 原始资料
- PDF:
- English Markdown:
- Chinese Markdown:

## Knowledge / 知识总结
- Knowledge CN:
- Knowledge EN:

## Notes / 研究笔记

## Related Concepts / 相关概念
""",
    )

    write_text_if_changed(
        TEMPLATES_DIR / "concept.md",
        """---
title: "{{title}}"
type: "concept"
tags: ["concept"]
---

# {{title}}

## Definition / 定义

## Related Papers / 相关论文

## Related Concepts / 相关概念

## Notes / 备注
""",
    )

    write_text_if_changed(
        TEMPLATES_DIR / "map.md",
        """---
title: "{{title}}"
type: "map"
tags: ["map"]
---

# {{title}}

## Core Concepts / 核心概念

## Papers / 论文

## Knowledge Notes / 知识总结

## Open Questions / 待研究问题
""",
    )


def write_maps():
    write_text_if_changed(
        MAPS_DIR / "Home.md",
        """# Obsidian LLM Wiki Home / 首页

## Quick Links / 快速入口
- [[maps/Papers Index]]
- [[maps/Concepts Index]]
- [[maps/Knowledge Index]]
- [[maps/Missing Chinese Translation]]
- [[maps/Missing Knowledge Summary]]
- [[maps/OCR Candidates]]
- [[maps/LLM Setup]]

## Data Layers / 数据分层
- `pdf/`：原始 PDF
- `markdown/`：正文 Markdown
- `knowledge/`：知识总结
- `notes/papers/`：Obsidian 聚合笔记
- `concepts/`：概念卡片
- `maps/`：导航与索引

## Workflow / 工作流
1. 使用 `pdf2markdown.py` 或 `ocr_pdf2markdown.py` 生成 Markdown
2. 使用 `en2cn.py` 生成中文稿
3. 使用 `knowledge.py` 生成知识总结
4. 使用 `build_obsidian_wiki.py` 刷新 Obsidian wiki
5. 构建阶段会自动调用 LLM 审查高风险 concepts，并排除误识别条目

## Incremental Refresh / 增量刷新
- 一次刷新：`python build_obsidian_wiki.py`
- 持续监听：`python build_obsidian_wiki.py --watch`
""",
    )

    write_text_if_changed(
        MAPS_DIR / "Papers Index.md",
        """# Papers Index / 论文索引

```dataview
TABLE year, has_pdf, has_en_markdown, has_cn_markdown, has_knowledge_cn, has_knowledge_en, wiki_last_built
FROM "notes/papers"
WHERE type = "paper-note"
SORT file.name ASC
```
""",
    )

    write_text_if_changed(
        MAPS_DIR / "Concepts Index.md",
        """# Concepts Index / 概念索引

```dataview
TABLE paper_count, aliases, wiki_last_built
FROM "concepts"
WHERE type = "concept"
SORT file.name ASC
```
""",
    )

    write_text_if_changed(
        MAPS_DIR / "Knowledge Index.md",
        """# Knowledge Index / 知识总结索引

```dataview
TABLE year, has_knowledge_cn, has_knowledge_en, wiki_last_built
FROM "notes/papers"
WHERE type = "paper-note" AND (has_knowledge_cn = true OR has_knowledge_en = true)
SORT file.name ASC
```
""",
    )

    write_text_if_changed(
        MAPS_DIR / "Missing Chinese Translation.md",
        """# Missing Chinese Translation / 缺失中文翻译

```dataview
TABLE year, has_pdf, has_en_markdown, wiki_last_built
FROM "notes/papers"
WHERE type = "paper-note" AND has_en_markdown = true AND has_cn_markdown = false
SORT file.name ASC
```
""",
    )

    write_text_if_changed(
        MAPS_DIR / "Missing Knowledge Summary.md",
        """# Missing Knowledge Summary / 缺失知识总结

```dataview
TABLE year, has_en_markdown, has_cn_markdown, wiki_last_built
FROM "notes/papers"
WHERE type = "paper-note" AND has_knowledge_cn = false AND has_knowledge_en = false
SORT file.name ASC
```
""",
    )

    write_text_if_changed(
        MAPS_DIR / "OCR Candidates.md",
        """# OCR Candidates / OCR 候选文档

当 `pdf2markdown.py` 导出的内容主要是页码、版权页、年份、空白段落时，应优先改用 `ocr_pdf2markdown.py`。

## Recommended Command / 推荐命令

```powershell
python ocr_pdf2markdown.py
```

## Candidates / 候选列表

```dataview
TABLE year, has_pdf, has_en_markdown, wiki_last_built
FROM "notes/papers"
WHERE type = "paper-note" AND has_pdf = true AND has_en_markdown = false
SORT file.name ASC
```

> 如果文档已经有 `*-en.md`，但内容质量很差，也建议手动重新跑 OCR。
""",
    )

    write_text_if_changed(
        MAPS_DIR / "LLM Setup.md",
        """# LLM Setup / LLM 配置说明

## Recommended Plugins / 推荐插件
- Dataview
- Templater
- PDF++
- Smart Connections
- Copilot

## Install Order / 安装顺序
1. Dataview
2. Templater
3. PDF++
4. Smart Connections
5. Copilot

## DeepSeek API / DeepSeek 接入

建议在 Obsidian 的 LLM 相关插件中使用 OpenAI-compatible / Custom endpoint 模式：

- Base URL: `https://api.deepseek.com`
- Model: `deepseek-v4-flash` 或 `deepseek-v4-pro`
- API Key: 使用你自己的 DeepSeek API Key

## Vault Settings / Vault 配置
- Templates 目录：`templates`
- 推荐把首页固定为：`maps/Home.md`
- 推荐先打开 Graph view、Backlinks、Page preview

## Notes / 注意
- 社区插件需要在 Obsidian 中手动安装
- 本仓库不会明文保存任何 DeepSeek 密钥
- `build_obsidian_wiki.py` 默认会调用 `review_concepts_with_llm.py` 进行 concept 质检
""",
    )


def write_obsidian_config():
    write_text_if_changed(
        OBSIDIAN_DIR / "app.json",
        json.dumps(
            {
                "showLineNumber": True,
                "spellcheck": True,
                "alwaysUpdateLinks": True,
                "attachmentFolderPath": "attachments",
                "newLinkFormat": "relative",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )

    write_text_if_changed(
        OBSIDIAN_DIR / "core-plugins.json",
        json.dumps(
            [
                "file-explorer",
                "global-search",
                "switcher",
                "graph",
                "backlink",
                "page-preview",
                "templates",
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )

    write_text_if_changed(
        OBSIDIAN_DIR / "templates.json",
        json.dumps(
            {
                "folder": "templates",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )


def refresh_static_files():
    write_obsidian_config()
    write_templates()
    write_maps()


def build_file_snapshot() -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for folder in [PDF_DIR, MARKDOWN_DIR, KNOWLEDGE_DIR]:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*")):
            if path.is_file():
                snapshot[str(path.relative_to(ROOT_DIR)).replace("\\", "/")] = path.stat().st_mtime
    return snapshot


def diff_snapshots(previous: dict[str, float], current: dict[str, float]) -> set[str]:
    changed_paths = set(previous) ^ set(current)
    for key in set(previous) & set(current):
        if previous[key] != current[key]:
            changed_paths.add(key)
    return changed_paths


def base_from_relative_path(relative_path: str) -> str:
    relative = Path(relative_path)
    if relative.parent.name == "pdf":
        return relative.stem
    return normalize_doc_stem(relative.stem)


def build_wiki(
    target_bases: set[str] | None = None,
    *,
    enable_llm_concept_review: bool = True,
    force_llm_concept_review: bool = False,
):
    ensure_dirs()
    refresh_static_files()
    records = gather_records()
    paper_concepts, concept_inventory = build_concept_inventory(records)
    removed_by_llm: dict[str, dict[str, str]] = {}
    if enable_llm_concept_review and concept_inventory:
        try:
            paper_concepts, concept_inventory, removed_by_llm = apply_llm_concept_review(
                paper_concepts,
                concept_inventory,
                force=force_llm_concept_review,
                verbose=True,
            )
        except Exception as exc:
            print(f"跳过 LLM concept 审查: {exc}")

    write_concept_notes(concept_inventory)
    write_knowledge_links(records, target_bases=target_bases)
    if target_bases:
        write_paper_notes(records, paper_concepts, target_bases=target_bases)
        if removed_by_llm:
            print(f"LLM 移除了 {len(removed_by_llm)} 个错误 concepts。")
        print(f"Refreshed {len(target_bases)} affected papers.")
    else:
        write_paper_notes(records, paper_concepts)
        if removed_by_llm:
            print(f"LLM 移除了 {len(removed_by_llm)} 个错误 concepts。")
        print(f"Generated Obsidian wiki for {len(records)} papers.")


def watch(
    interval: float,
    *,
    enable_llm_concept_review: bool = True,
    force_llm_concept_review: bool = False,
):
    print(f"Watching pdf/, markdown/, knowledge/ every {interval:.1f}s ...")
    previous_snapshot = build_file_snapshot()
    build_wiki(
        enable_llm_concept_review=enable_llm_concept_review,
        force_llm_concept_review=force_llm_concept_review,
    )

    while True:
        time.sleep(interval)
        current_snapshot = build_file_snapshot()
        changed_paths = diff_snapshots(previous_snapshot, current_snapshot)
        if not changed_paths:
            continue

        affected_bases = {base_from_relative_path(path) for path in changed_paths}
        print(f"Detected {len(changed_paths)} file changes, refreshing {len(affected_bases)} papers ...")
        build_wiki(
            target_bases=affected_bases,
            enable_llm_concept_review=enable_llm_concept_review,
            force_llm_concept_review=force_llm_concept_review,
        )
        previous_snapshot = current_snapshot


def main():
    args = parse_args()
    if args.watch:
        watch(
            args.interval,
            enable_llm_concept_review=not args.skip_llm_concept_review,
            force_llm_concept_review=args.force_llm_concept_review,
        )
        return

    build_wiki(
        enable_llm_concept_review=not args.skip_llm_concept_review,
        force_llm_concept_review=args.force_llm_concept_review,
    )


if __name__ == "__main__":
    main()
