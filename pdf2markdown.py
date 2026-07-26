import re
from pathlib import Path
from markitdown import MarkItDown

pdf_dir = Path("./pdf")
md_dir = Path("./markdown")
md_dir.mkdir(exist_ok=True)

CN_RATIO_THRESHOLD = 0.3  # 中文字符占比超过此值判定为中文


def detect_language(text: str) -> str:
    """检测文本语言，返回 'cn' 或 'en'。"""
    # 统计中文字符（CJK 统一表意文字）
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    # 统计字母字符（英文）
    en_chars = len(re.findall(r"[a-zA-Z]", text))
    total = cn_chars + en_chars
    if total == 0:
        return "en"
    return "cn" if cn_chars / total >= CN_RATIO_THRESHOLD else "en"


md = MarkItDown()

for pdf_path in pdf_dir.glob("*.pdf"):
    result = md.convert(str(pdf_path))
    content = result.text_content
    lang = detect_language(content)
    md_path = md_dir / f"{pdf_path.stem}-{lang}.md"
    md_path.write_text(content, encoding="utf-8")
    print(f"Converted: {pdf_path.name} -> {md_path.name}")

print("Done.")
