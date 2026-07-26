"""
将扫描版 PDF 通过 OCR 转为 Markdown。

优先使用 rapidocr_onnxruntime，其次使用 pytesseract。

用法示例：
    python ocr_pdf2markdown.py
    python ocr_pdf2markdown.py "pdf/07_yoderSecularVariationEarth1983a_yoder_1983_secular_variation_of_earth_s_gravitational_harmonic_j2_1.pdf"
    python ocr_pdf2markdown.py --backend rapidocr --dpi 220
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageOps

PDF_DIR = Path("./pdf")
OUTPUT_DIR = Path("./markdown")
CN_RATIO_THRESHOLD = 0.3


def detect_language(text: str) -> str:
    """检测 OCR 输出语言，返回 'cn' 或 'en'。"""
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_chars = len(re.findall(r"[a-zA-Z]", text))
    total = cn_chars + en_chars
    if total == 0:
        return "en"
    return "cn" if cn_chars / total >= CN_RATIO_THRESHOLD else "en"


def preprocess_image(image: Image.Image) -> Image.Image:
    """对页面图像做轻量预处理，提升 OCR 识别效果。"""
    gray = image.convert("L")
    enhanced = ImageOps.autocontrast(gray)
    return enhanced


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

    content = "\n\n---\n\n".join(page_texts)
    print(f"  OCR 后端: {backend_name}")
    return content


def convert_pdf(pdf_path: Path, backend_name: str, ocr_func, dpi: int):
    """将单个 PDF OCR 转换为 Markdown。"""
    print(f"处理: {pdf_path.name}")
    content = ocr_pdf(pdf_path, backend_name=backend_name, ocr_func=ocr_func, dpi=dpi)
    lang = detect_language(content)
    out_path = OUTPUT_DIR / f"{pdf_path.stem}-{lang}.md"
    out_path.write_text(content, encoding="utf-8")
    print(f"  已保存: {out_path.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将扫描版 PDF 通过 OCR 转为 Markdown。")
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
        help="页面渲染 DPI，默认 220。",
    )
    return parser.parse_args()


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


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(exist_ok=True)

    try:
        pdf_paths = resolve_inputs(args.inputs)
        backend_name, ocr_func = get_ocr_backend(args.backend)
    except Exception as exc:
        print(f"错误: {exc}")
        return 1

    if not pdf_paths:
        print(f"未找到待处理的 PDF 文件: {PDF_DIR}")
        return 0

    print(f"找到 {len(pdf_paths)} 个 PDF 文件，使用 {backend_name} OCR\n")

    for pdf_path in pdf_paths:
        try:
            convert_pdf(pdf_path, backend_name=backend_name, ocr_func=ocr_func, dpi=args.dpi)
            print()
        except Exception as exc:
            print(f"  处理失败: {exc}\n")

    print("全部完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
