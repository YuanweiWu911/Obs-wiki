# Obs-wiki
tools to build Obsidian wiki
=======
# pdf2markdown

这个目录下包含 7 个 Python 脚本，用于完成论文 PDF 转 Markdown、扫描版 PDF OCR、英文论文翻译、知识总结生成、Obsidian LLM wiki 构建，以及基于 LLM 的自动 concept 质检。

## 目录说明

- `pdf2markdown.py`：将 `./pdf/*.pdf` 转为 `./markdown/*.md`
- `ocr_pdf2markdown.py`：将扫描版 PDF 逐页 OCR 后转为 `./markdown/*.md`
- `en2cn.py`：将 `./markdown/*-en.md` 翻译为 `./markdown/*-cn.md`
- `knowledge.py`：读取一对 `*-en.md` 和 `*-cn.md`，在 `./knowledge/` 下生成中英文知识总结
- `run_without_proxy.py`：以“直连模式”启动其他脚本，绕过系统代理
- `build_obsidian_wiki.py`：构建和刷新 Obsidian LLM wiki
- `review_concepts_with_llm.py`：用 DeepSeek 审查自动生成的 concepts，并缓存保留/删除决策

## 前置条件

### 1. Python

建议使用 Python 3.10 及以上版本。

### 2. 安装依赖

至少需要安装：

```bash
pip install requests markitdown
```

如果 `markitdown` 还依赖额外的 PDF 解析组件，请按你的本地环境补齐。

如果要处理扫描版 PDF，建议额外安装一种 OCR 后端：

```bash
pip install rapidocr-onnxruntime
```

或者：

```bash
pip install pytesseract
```

如果使用 `pytesseract`，还需要另外安装 Tesseract OCR 可执行程序。

### 3. 设置 DeepSeek API Key

`en2cn.py` 和 `knowledge.py` 都会读取环境变量 `ANTHROPIC_AUTH_TOKEN`：

```powershell
$env:ANTHROPIC_AUTH_TOKEN = "你的 DeepSeek API Key"
```

### 4. 可选环境变量

- `DEEPSEEK_MODEL`
  - 默认值：`deepseek-v4-flash`
  - 可选：`deepseek-v4-pro`
- `DEEPSEEK_PROXY_MODE`
  - `auto`：优先继承系统代理，代理失败时回退直连
  - `off`：完全不使用系统代理
  - `on`：强制使用系统代理

## 单独使用

### 1. `pdf2markdown.py`

作用：把 `./pdf` 目录中的 PDF 转成 Markdown，并根据文本内容自动判断中文/英文，输出为：

- `xxx-cn.md`
- `xxx-en.md`

运行方式：

```powershell
python pdf2markdown.py
```

适用场景：

- 你刚把新的 PDF 放进 `./pdf`
- 你想先生成 Markdown，再决定是否翻译和总结

### 2. `en2cn.py`

作用：扫描 `./markdown` 下所有 `*-en.md`，调用 DeepSeek 翻译成 `*-cn.md`。如果对应中文文件已存在，会自动跳过。

运行方式：

```powershell
python en2cn.py
```

指定模型：

```powershell
$env:DEEPSEEK_MODEL = "deepseek-v4-pro"
python en2cn.py
```

### 3. `ocr_pdf2markdown.py`

作用：专门处理扫描版 PDF。它会先把 PDF 页面渲染成图片，再使用 OCR 识别文本，最后输出为 Markdown。

运行方式：

```powershell
python ocr_pdf2markdown.py
```

只处理单个文件：

```powershell
python ocr_pdf2markdown.py "pdf\\07_yoderSecularVariationEarth1983a_yoder_1983_secular_variation_of_earth_s_gravitational_harmonic_j2_1.pdf"
```

指定 OCR 后端：

```powershell
python ocr_pdf2markdown.py --backend rapidocr
```

适用场景：

- `pdf2markdown.py` 提取出来几乎全是空白、页眉、版权信息
- 原 PDF 本质上是扫描图片，不是可选中文本

### 4. `knowledge.py`

作用：自动配对 `*-en.md` 和 `*-cn.md`，基于中英文双语内容提取知识点，并在 `./knowledge` 下生成：

- `xxx_knowledge_cn.md`
- `xxx_knowledge_en.md`

运行方式：

```powershell
python knowledge.py
```

适用前提：

- `./markdown` 下已经有成对的 `*-en.md` 和 `*-cn.md`

### 5. `run_without_proxy.py`

作用：绕过系统代理启动其他脚本。它会在子进程中：

- 清除 `HTTP_PROXY`
- 清除 `HTTPS_PROXY`
- 清除 `ALL_PROXY`
- 设置 `NO_PROXY=api.deepseek.com,deepseek.com`
- 设置 `DEEPSEEK_PROXY_MODE=off`

运行方式：

```powershell
python run_without_proxy.py en2cn.py
```

或者：

```powershell
python run_without_proxy.py knowledge.py
```

指定模型：

```powershell
python run_without_proxy.py --model deepseek-v4-pro en2cn.py
```

## 组合使用

### 流程一：从 PDF 到 Markdown

```powershell
python pdf2markdown.py
```

结果：

- `./pdf/*.pdf`
- 转成 `./markdown/*.md`

如果遇到扫描版 PDF，改用：

```powershell
python ocr_pdf2markdown.py
```

### 流程二：从英文 Markdown 到中文 Markdown

如果本机网络环境可以直接访问 DeepSeek：

```powershell
python en2cn.py
```

如果系统代理会干扰 DeepSeek 访问，推荐使用：

```powershell
python run_without_proxy.py en2cn.py
```

### 流程三：从双语 Markdown 到知识总结

确保已经有成对的 `*-en.md` 和 `*-cn.md` 后：

```powershell
python knowledge.py
```

如果需要绕过代理：

```powershell
python run_without_proxy.py knowledge.py
```

### 流程四：完整工作流

这是最常见的完整处理链路：

1. PDF 转 Markdown
2. 英文 Markdown 翻译成中文
3. 基于双语文档生成知识总结

推荐命令：

```powershell
python pdf2markdown.py
python run_without_proxy.py en2cn.py
python run_without_proxy.py knowledge.py
```

如果 PDF 是扫描件，则把第一步替换为：

```powershell
python ocr_pdf2markdown.py
python run_without_proxy.py en2cn.py
python run_without_proxy.py knowledge.py
```

## 推荐用法

如果你当前机器经常开代理，最稳妥的方式是：

```powershell
python pdf2markdown.py
python run_without_proxy.py en2cn.py
python run_without_proxy.py knowledge.py
```

这样：

- PDF 转换不依赖网络
- 翻译和知识总结都自动绕过代理
- 不需要每次手动删除环境变量

## 输出文件规则

### `pdf2markdown.py`

- `paper.pdf` -> `paper-en.md` 或 `paper-cn.md`

### `en2cn.py`

- `paper-en.md` -> `paper-cn.md`

### `ocr_pdf2markdown.py`

- `paper.pdf` -> `paper-en.md` 或 `paper-cn.md`

### `knowledge.py`

- `paper-en.md` + `paper-cn.md`
- 在 `./knowledge/` 中生成：
  - `paper_knowledge_cn.md`
  - `paper_knowledge_en.md`

## 常见问题

### 1. `API 调用失败: ProxyError`

说明系统代理干扰了 DeepSeek 访问。优先使用：

```powershell
python run_without_proxy.py en2cn.py
python run_without_proxy.py knowledge.py
```

### 2. `pdf2markdown.py` 提取结果只有版权页、页码或空白

这通常说明 PDF 是扫描图片，不是文本层 PDF。请改用：

```powershell
python ocr_pdf2markdown.py
```

### 3. `HTTP 400` 提示模型名不支持

当前接口只支持新版模型，建议使用默认值，或显式指定：

```powershell
python run_without_proxy.py --model deepseek-v4-flash en2cn.py
```

或：

```powershell
python run_without_proxy.py --model deepseek-v4-pro knowledge.py
```

### 4. `knowledge.py` 提示找不到对应的 `-cn` 文件

先确认 `./markdown` 中对应论文是否已经存在：

- `xxx-en.md`
- `xxx-cn.md`

如果只有英文文件，请先运行：

```powershell
python run_without_proxy.py en2cn.py
```

## 最短上手命令

如果你只想记最少的命令，记住这一组就够了：

```powershell
python pdf2markdown.py
python run_without_proxy.py en2cn.py
python run_without_proxy.py knowledge.py
```

## Obsidian LLM Wiki

当前仓库现在也可以直接作为 Obsidian Vault 的数据源使用。

### 目录角色

- `pdf/`：原始 PDF
- `markdown/`：英文/中文正文 Markdown
- `knowledge/`：中英文知识总结
- `notes/papers/`：每篇论文的聚合笔记
- `concepts/`：概念卡片目录
- `maps/`：导航页、Dataview 索引页、LLM 配置说明
- `templates/`：中英双语模板
- `.obsidian/`：Vault 基础配置

### 一键生成 Vault 结构

执行：

```powershell
python build_obsidian_wiki.py
```

它会自动：

- 创建 `.obsidian/`
- 创建 `notes/papers/`
- 创建 `concepts/`
- 创建 `maps/`
- 创建 `templates/`
- 为当前仓库中的全部论文生成 Obsidian 聚合笔记
- 从 `knowledge/*.md` 自动提取基础概念，并生成 `concepts/*.md`
- 使用 `review_concepts_with_llm.py` 审查自动生成概念，删除像 `SH`、参数符号、局部编号这类错误 concepts

### 增量刷新与监听

手动刷新一次：

```powershell
python build_obsidian_wiki.py
```

跳过 LLM concept 审查：

```powershell
python build_obsidian_wiki.py --skip-llm-concept-review
```

忽略审查缓存，强制重审：

```powershell
python build_obsidian_wiki.py --force-llm-concept-review
```

持续监听 `pdf/`、`markdown/`、`knowledge/` 的变化并自动刷新：

```powershell
python build_obsidian_wiki.py --watch
```

监听模式适合你在 Obsidian 开着的同时，持续生成或更新 `knowledge/*.md` 的场景。

### 单独执行 concept 质检

如果你只想检查自动生成的 concepts，而不重建整个 wiki，可以执行：

```powershell
python review_concepts_with_llm.py --show-dropped
```

审查结果会缓存到：

- `.concept_review_state.json`
- `.concept_review_blacklist.json`

### 推荐工作流

普通文本 PDF：

```powershell
python pdf2markdown.py
python run_without_proxy.py en2cn.py
python run_without_proxy.py knowledge.py
python build_obsidian_wiki.py
```

扫描版 PDF：

```powershell
python ocr_pdf2markdown.py
python run_without_proxy.py en2cn.py
python run_without_proxy.py knowledge.py
python build_obsidian_wiki.py
```

### 在 Obsidian 中使用

1. 直接用 Obsidian 打开 `d:\ywwu_workspace\pdf2markdown`
2. 将 `maps/Home.md` 作为入口页
3. 安装社区插件：
   - Dataview
   - Templater
   - PDF++
   - Smart Connections
   - Copilot
4. 按 `maps/LLM Setup.md` 中的说明接入 DeepSeek API
