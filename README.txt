pdf2markdown

This project contains tools for:
- converting text-based PDFs to Markdown
- converting scanned PDFs to Markdown via OCR
- translating English Markdown into Chinese
- generating bilingual knowledge summaries
- bypassing proxy settings when calling DeepSeek APIs

Files
- pdf2markdown.py
  Convert text-based PDFs in ./pdf/ to Markdown files in ./markdown/

- ocr_pdf2markdown.py
  Convert scanned PDFs in ./pdf/ to Markdown using OCR
  Output files are written to ./markdown/
  Preferred OCR backend: rapidocr_onnxruntime
  Fallback OCR backend: pytesseract + Tesseract OCR executable

- en2cn.py
  Translate ./markdown/*-en.md into ./markdown/*-cn.md

- knowledge.py
  Read paired *-en.md and *-cn.md files from ./markdown/
  Write bilingual knowledge summaries to ./knowledge/

- run_without_proxy.py
  Launch other scripts with HTTP_PROXY / HTTPS_PROXY / ALL_PROXY removed
  Useful when DeepSeek access fails because traffic is forced through a proxy

OCR Quick Start
1. Install an OCR backend:
   python -m pip install rapidocr-onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple

   or:
   python -m pip install pytesseract -i https://pypi.tuna.tsinghua.edu.cn/simple

2. If using pytesseract, also install Tesseract OCR and make sure tesseract.exe is in PATH.

3. Run OCR conversion:
   python ocr_pdf2markdown.py

4. Run OCR conversion for a single PDF:
   python ocr_pdf2markdown.py "pdf\07_yoderSecularVariationEarth1983a_yoder_1983_secular_variation_of_earth_s_gravitational_harmonic_j2_1.pdf"

Recommended Workflow
1. Text PDF:
   python pdf2markdown.py
   python run_without_proxy.py en2cn.py
   python run_without_proxy.py knowledge.py

2. Scanned PDF:
   python ocr_pdf2markdown.py
   python run_without_proxy.py en2cn.py
   python run_without_proxy.py knowledge.py

Notes
- If pdf2markdown.py only extracts copyright lines, years, page numbers, or near-empty output,
  the PDF is likely image-based and should be processed with ocr_pdf2markdown.py.
- For more complete Markdown documentation, see README.md.
