"""
将 PDF 自动转换为 Markdown。

默认先检测 PDF 是否包含可用文本层：
- 文本型 PDF：直接使用 MarkItDown 提取
- 图片型 / 扫描型 PDF：自动切换到 OCR

也支持通过 --force-ocr 强制走 OCR 流程。
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from markitdown import MarkItDown
from PIL import Image, ImageOps

PDF_DIR = Path("./pdf")
OUTPUT_DIR = Path("./markdown")
CN_RATIO_THRESHOLD = 0.3
TEXT_LAYER_MIN_CHARS_PER_PAGE = 20
TEXT_LAYER_MIN_TOTAL_CHARS = 80
TEXT_EXTRACTION_MIN_CONTENT_CHARS = 80
TEXT_LAYER_SAMPLE_PAGES = 5


def detect_language(text: str) -> str:
    """检测文本语言，返回 'cn' 或 'en'。"""
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_chars = len(re.findall(r"[a-zA-Z]", text))
    total = cn_chars + en_chars
    if total == 0:
        return "en"
    return "cn" if cn_chars / total >= CN_RATIO_THRESHOLD else "en"


def preprocess_image(image: Image.Image) -> Image.Image:
    """对页面图像做轻量预处理，提升 OCR 识别效果。"""
    gray = image.convert("L")
    return ImageOps.autocontrast(gray)


def cleanup_ocr_text(text: str) -> str:
    """将 OCR 原始文本整理为更适合 Markdown 的段落文本。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    lines = [line.strip() for line in text.split("\n")]

    merged_lines: list[str] = []
    for line in lines:
        if not line:
            if merged_lines and merged_lines[-1] != "":
                merged_lines.append("")
            continue

        if merged_lines and merged_lines[-1] and merged_lines[-1].endswith("-"):
            merged_lines[-1] = merged_lines[-1][:-1] + line
        else:
            merged_lines.append(line)

    text = "\n".join(merged_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_ocr_backend(preferred: str):
    """选择 OCR 后端并返回名称与 OCR 函数。"""
    if preferred in {"auto", "rapidocr"}:
        try:
            from rapidocr_onnxruntime import RapidOCR

            engine = RapidOCR()

            def rapidocr_runner(image: Image.Image) -> str:
                result, _ = engine(np.array(image))
                if not result:
                    return ""
                return "\n".join(item[1] for item in result if len(item) >= 2)

            return "rapidocr", rapidocr_runner
        except ImportError:
            if preferred == "rapidocr":
                raise RuntimeError(
                    "未安装 rapidocr_onnxruntime。请先执行: pip install rapidocr-onnxruntime"
                )

    if preferred in {"auto", "tesseract"}:
        try:
            import pytesseract
        except ImportError:
            if preferred == "tesseract":
                raise RuntimeError(
                    "未安装 pytesseract。请先执行: pip install pytesseract"
                )
        else:
            if shutil.which("tesseract"):

                def tesseract_runner(image: Image.Image) -> str:
                    return pytesseract.image_to_string(image)

                return "tesseract", tesseract_runner

            if preferred == "tesseract":
                raise RuntimeError(
                    "未找到 tesseract 可执行文件。请先安装 Tesseract OCR，并确保命令 `tesseract` 可用。"
                )

    raise RuntimeError(
        "未找到可用的 OCR 后端。\n"
        "推荐安装其一：\n"
        "1. pip install rapidocr-onnxruntime\n"
        "2. 或 pip install pytesseract，并安装 Tesseract OCR"
    )


def render_page(page, dpi: int) -> Image.Image:
    """将 PDF 页面渲染为 PIL 图像。"""
    scale = dpi / 72.0
    bitmap = page.render(scale=scale, rev_byteorder=True)
    return bitmap.to_pil()


def ocr_pdf(pdf_path: Path, backend_name: str, ocr_func, dpi: int) -> str:
    """逐页 OCR PDF，并拼接为 Markdown 文本。"""
    pdf = pdfium.PdfDocument(str(pdf_path))
    page_texts: list[str] = []

    for page_index in range(len(pdf)):
        page = pdf[page_index]
        image = preprocess_image(render_page(page, dpi=dpi))
        text = cleanup_ocr_text(ocr_func(image))
        if text:
            page_texts.append(text)
        print(f"  OCR 第 {page_index + 1}/{len(pdf)} 页完成")

    if not page_texts:
        raise RuntimeError(f"OCR 未识别出任何文本: {pdf_path.name}")

    print(f"  OCR 后端: {backend_name}")
    return "\n\n---\n\n".join(page_texts)


def resolve_inputs(raw_inputs: list[str]) -> list[Path]:
    """解析命令行输入，得到要处理的 PDF 列表。"""
    if raw_inputs:
        pdf_paths = [Path(item) for item in raw_inputs]
    else:
        pdf_paths = sorted(PDF_DIR.glob("*.pdf"))

    missing = [path for path in pdf_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("以下文件不存在:\n" + "\n".join(str(path) for path in missing))

    return pdf_paths


def sample_page_indices(page_count: int, max_pages: int = TEXT_LAYER_SAMPLE_PAGES) -> list[int]:
    """均匀抽样若干页，用于判断是否存在可用文本层。"""
    if page_count <= 0:
        return []
    if page_count <= max_pages:
        return list(range(page_count))

    step = (page_count - 1) / (max_pages - 1)
    return sorted({round(index * step) for index in range(max_pages)})


def inspect_text_layer(pdf_path: Path) -> tuple[bool, str]:
    """判断 PDF 是否更像文本型文档而非纯图片扫描件。"""
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except Exception as exc:
        return True, f"文本层检测失败，先按文本 PDF 处理: {exc}"

    indices = sample_page_indices(len(pdf))
    total_chars = 0
    pages_with_text = 0

    for page_index in indices:
        text_page = pdf[page_index].get_textpage()
        char_count = text_page.count_chars()
        total_chars += char_count
        if char_count >= TEXT_LAYER_MIN_CHARS_PER_PAGE:
            pages_with_text += 1

    sampled = len(indices)
    if total_chars < TEXT_LAYER_MIN_TOTAL_CHARS or pages_with_text == 0:
        return False, f"抽样 {sampled} 页仅检测到 {total_chars} 个文本字符"

    return True, f"抽样 {sampled} 页检测到 {total_chars} 个文本字符"


def extract_text_pdf(pdf_path: Path, converter: MarkItDown) -> str:
    """使用 MarkItDown 提取文本型 PDF 内容。"""
    result = converter.convert(str(pdf_path))
    return (result.text_content or "").strip()


def has_meaningful_text(content: str) -> bool:
    """判断提取结果是否足够像正常正文，而非零碎页眉页脚。"""
    useful_chars = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", content))
    return useful_chars >= TEXT_EXTRACTION_MIN_CONTENT_CHARS


def save_markdown(pdf_path: Path, content: str):
    """按语言后缀保存 Markdown 文件。"""
    lang = detect_language(content)
    out_path = OUTPUT_DIR / f"{pdf_path.stem}-{lang}.md"
    out_path.write_text(content, encoding="utf-8")
    print(f"  已保存: {out_path.name}")


def ensure_ocr_backend(cache: dict[str, object], preferred: str):
    """按需初始化 OCR 后端，避免纯文本 PDF 也强制依赖 OCR。"""
    if cache.get("func") is None:
        backend_name, ocr_func = get_ocr_backend(preferred)
        cache["name"] = backend_name
        cache["func"] = ocr_func
    return cache["name"], cache["func"]


def convert_pdf(
    pdf_path: Path,
    *,
    converter: MarkItDown,
    ocr_backend_cache: dict[str, object],
    ocr_backend: str,
    dpi: int,
    force_ocr: bool,
):
    """自动选择文本提取或 OCR，并写出 Markdown。"""
    print(f"处理: {pdf_path.name}")

    if force_ocr:
        print("  模式: 强制 OCR")
        backend_name, ocr_func = ensure_ocr_backend(ocr_backend_cache, ocr_backend)
        content = ocr_pdf(pdf_path, backend_name=backend_name, ocr_func=ocr_func, dpi=dpi)
        save_markdown(pdf_path, content)
        return

    has_text_layer, reason = inspect_text_layer(pdf_path)
    if has_text_layer:
        print(f"  检测结果: 文本型 PDF ({reason})")
        try:
            content = extract_text_pdf(pdf_path, converter)
            if has_meaningful_text(content):
                save_markdown(pdf_path, content)
                return

            print("  文本提取结果过短，自动回退到 OCR")
        except Exception as exc:
            print(f"  文本提取失败，自动回退到 OCR: {exc}")
    else:
        print(f"  检测结果: 图片型 PDF ({reason})，自动切换到 OCR")

    backend_name, ocr_func = ensure_ocr_backend(ocr_backend_cache, ocr_backend)
    content = ocr_pdf(pdf_path, backend_name=backend_name, ocr_func=ocr_func, dpi=dpi)
    save_markdown(pdf_path, content)


def parse_args(force_ocr_default: bool = False) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 PDF 自动转换为 Markdown，必要时自动切换到 OCR。")
    parser.add_argument(
        "inputs",
        nargs="*",
        help="要处理的 PDF 文件路径；留空时默认处理 ./pdf/*.pdf",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "rapidocr", "tesseract"],
        default="auto",
        help="OCR 后端，默认 auto。",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=220,
        help="OCR 页面渲染 DPI，默认 220。",
    )
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        default=force_ocr_default,
        help="无论 PDF 是否有文本层，都强制使用 OCR。",
    )
    return parser.parse_args()


def main(force_ocr_default: bool = False) -> int:
    args = parse_args(force_ocr_default=force_ocr_default)
    OUTPUT_DIR.mkdir(exist_ok=True)

    try:
        pdf_paths = resolve_inputs(args.inputs)
    except Exception as exc:
        print(f"错误: {exc}")
        return 1

    if not pdf_paths:
        print(f"未找到待处理的 PDF 文件: {PDF_DIR}")
        return 0

    converter = MarkItDown()
    ocr_backend_cache: dict[str, object] = {"name": None, "func": None}
    print(f"找到 {len(pdf_paths)} 个 PDF 文件\n")

    for pdf_path in pdf_paths:
        try:
            convert_pdf(
                pdf_path,
                converter=converter,
                ocr_backend_cache=ocr_backend_cache,
                ocr_backend=args.backend,
                dpi=args.dpi,
                force_ocr=args.force_ocr,
            )
            print()
        except Exception as exc:
            print(f"  处理失败: {exc}\n")

    print("全部完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
