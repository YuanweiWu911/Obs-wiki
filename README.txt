pdf2markdown

This project contains tools for:
- converting PDFs to Markdown with automatic OCR fallback
- forcing scanned PDFs through OCR when needed
- translating English Markdown into Chinese
- generating bilingual knowledge summaries
- building an Obsidian LLM wiki
- reviewing auto-generated concepts with an LLM
- bypassing proxy settings when calling DeepSeek APIs

Files
- pdf2markdown.py
  Convert PDFs in ./pdf/ to Markdown files in ./markdown/
  Automatically detect image-based PDFs and switch to OCR when needed
  Supports --input for a single PDF, --start/--end for page ranges,
  and --force to skip output existence checks

- pdf2html.py
  Convert PDFs in ./pdf/ to HTML files in ./html/
  Rebuild out.html as an index page for browsing converted files
  Supports --input for a single PDF, --start/--end for page ranges,
  and --force to reconvert existing HTML outputs

- ocr_pdf2markdown.py
  Compatibility wrapper that forces OCR mode through pdf2markdown.py
  Useful when you already know the PDF is scanned

- en2cn.py
  Translate ./markdown/*-en.md into ./markdown/*-cn.md
  Supports --input for a single Markdown file and --force to overwrite existing translations

- review_cn_markdown.py
  Review ./markdown/*-cn.md for grammar issues and typos using DeepSeek
  Write reports to ./report/*-cn-review-report.md
  Supports --input for a single Markdown file and --force to regenerate existing reports

- knowledge.py
  Read paired *-en.md and *-cn.md files from ./markdown/
  Write bilingual knowledge summaries to ./knowledge/
  Supports --input for a single paired paper and --force to regenerate existing summaries

- run_without_proxy.py
  Launch other scripts with HTTP_PROXY / HTTPS_PROXY / ALL_PROXY removed
  Useful when DeepSeek access fails because traffic is forced through a proxy

- build_obsidian_wiki.py
  Build and refresh the Obsidian LLM wiki from pdf/, markdown/, and knowledge/

- review_concepts_with_llm.py
  Review auto-generated concepts with DeepSeek and cache keep/drop decisions

OCR Quick Start
1. Install an OCR backend:
   python -m pip install rapidocr-onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple

   or:
   python -m pip install pytesseract -i https://pypi.tuna.tsinghua.edu.cn/simple

2. If using pytesseract, also install Tesseract OCR and make sure tesseract.exe is in PATH.

3. Run PDF conversion with automatic detection:
   python pdf2markdown.py

   Run a single PDF:
   python pdf2markdown.py --input ".\pdf\paper.pdf"

   Convert only a page range:
   python pdf2markdown.py --input ".\pdf\paper.pdf" --start 1 --end 3

   Force re-run even when Markdown output already exists:
   python pdf2markdown.py --input ".\pdf\paper.pdf" --force

4. Force OCR conversion:
   python ocr_pdf2markdown.py

5. Run OCR conversion for a single PDF:
   python ocr_pdf2markdown.py "pdf\07_yoderSecularVariationEarth1983a_yoder_1983_secular_variation_of_earth_s_gravitational_harmonic_j2_1.pdf"

HTML Quick Start
1. Convert all PDFs to HTML:
   python pdf2html.py

2. Convert a single PDF to HTML:
   python pdf2html.py --input ".\pdf\paper.pdf"

   Convert only a page range:
   python pdf2html.py --input ".\pdf\paper.pdf" --start 1 --end 3

3. Force reconvert a single PDF:
   python pdf2html.py --input ".\pdf\paper.pdf" --force

Recommended Workflow
1. Text PDF:
   python pdf2markdown.py
   python run_without_proxy.py en2cn.py
   python run_without_proxy.py knowledge.py

2. Scanned PDF:
   python pdf2markdown.py
   python run_without_proxy.py en2cn.py
   python run_without_proxy.py knowledge.py

Notes
- pdf2markdown.py now auto-detects image-based PDFs and falls back to OCR.
- Use ocr_pdf2markdown.py only when you want to force OCR explicitly.
- For more complete Markdown documentation, see README.md.
- Single-file examples:
  - python pdf2html.py --input ".\pdf\paper.pdf"
  - python pdf2html.py --input ".\pdf\paper.pdf" --start 1 --end 3
  - python pdf2html.py --input ".\pdf\paper.pdf" --force
  - python pdf2markdown.py --input ".\pdf\paper.pdf" --start 1 --end 3
  - python en2cn.py --input ".\markdown\paper-en.md"
  - python en2cn.py --input ".\markdown\paper-en.md" --force
  - python review_cn_markdown.py --input ".\markdown\paper-cn.md"
  - python review_cn_markdown.py --input ".\markdown\paper-cn.md" --force
  - python knowledge.py --input ".\markdown\paper-en.md"
  - python knowledge.py --input ".\markdown\paper-en.md" --force

Obsidian LLM Wiki
- This repository can now also work as an Obsidian Vault data source.

- Generated Vault structure:
  - .obsidian/
  - notes/papers/
  - concepts/
  - maps/
  - templates/

- Build command:
  python build_obsidian_wiki.py

- Watch mode:
  python build_obsidian_wiki.py --watch

- The build script will:
  - create the Vault directories and base config
  - generate bilingual templates
  - generate navigation and Dataview index pages
  - generate one aggregated paper note per paper from pdf/, markdown/, and knowledge/
  - generate basic concept notes from knowledge/*.md
  - call review_concepts_with_llm.py to remove wrong concepts such as short mixed-meaning abbreviations
  - preserve manual note sections while replacing only the auto-generated block

- Optional flags:
  - skip LLM concept review:
    python build_obsidian_wiki.py --skip-llm-concept-review
  - force re-review:
    python build_obsidian_wiki.py --force-llm-concept-review

- Review concepts only:
  python review_concepts_with_llm.py --show-dropped

- Recommended workflows:
  Text PDF:
    python pdf2markdown.py
    python run_without_proxy.py en2cn.py
    python run_without_proxy.py knowledge.py
    python build_obsidian_wiki.py

  Scanned PDF:
    python ocr_pdf2markdown.py
    python run_without_proxy.py en2cn.py
    python run_without_proxy.py knowledge.py
    python build_obsidian_wiki.py

- In Obsidian:
  1. Open d:\ywwu_workspace\pdf2markdown as the Vault
  2. Use maps/Home.md as the entry page
  3. Install Dataview, Templater, PDF++, Smart Connections, and Copilot
  4. Follow maps/LLM Setup.md to connect DeepSeek API
