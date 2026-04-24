---
name: rtd-to-chunk
description: Convert RTD-style markdown (local files or GitHub repository/tree/root URLs) into structured chunk JSON for retrieval and downstream DB build. Use when running `rtd-to-chunk/scripts/chunk.py`.After chunk generation finishes, it will ask users whether to run chunk-to-db skill for LanceDB construction, and generate a dedicated retrieval skill following the logic of pulsar2-doc-search with a user-defined skill name.
---

# RTD2Chunk Pipeline

执行 RTD 文档到 chunk JSON 的单一流水线。

## 目标与边界

- 目标：单次离线执行，把 RTD markdown 转为结构化 chunks。
- 边界：仅使用 `chunk.py`作为流程入口 。
- 输入：
  - 离线 markdown 目录
  - 一个/多个 GitHub 仓库/目录 URL。
- 输出：仅保存最终产物，供检索、评估、下游构建使用。在当前文件下生成tmp文件,在下游构建完成后删除。

## Quick Start

离线目录模式：

```bash
python scripts/chunk.py \
  --input-dir <offline_md_dir> \
  --output-dir <output_root_dir> \
  --router-mode rule \
  --glob "*.md" \
  --max-concurrency 4 \
  --run-id <run_id_optional>
```

GitHub URL 模式（可重复 `--input-url`）：

```bash
python scripts/chunk.py \
  --input-url https://github.com/<org>/<repo> \
  --input-url https://github.com/<org>/<repo>/tree/<branch>/<path_optional> \
  --output-dir <output_root_dir> \
  --router-mode llm \
  --llm-model gpt-4o-mini \
  --max-concurrency 2 \
  --run-id <run_id_optional>
```

要求：

- 传入 `--input-dir` 或 `--input-url`（二选一）。
- 必填 `--output-dir`。

## CLI 参数

- `--input-dir`：离线 markdown 输入目录（与 `--input-url` 二选一）。
- `--input-url`：GitHub 仓库/目录 URL 输入（与 `--input-dir` 二选一，可重复）。
- `--output-dir`：输出根目录（必填）。
- `--glob`：输入文件匹配模式，默认 `*.md`。
- `--max-concurrency`：并发度，默认 `4`。
- `--router-mode`：依文档类型处理逻辑的路由。
- `--run-id`：运行标识，可选；不传自动生成。

## Run Workflow

按以下顺序执行：

1. 加载源文档（本地 markdown 或 GitHub repository/tree/root URL）。
2. 预处理内容。
3. 进行文档分类（`rule` 或 `llm`，llm 失败回退 rule）。
4. 执行类型处理器。
5. 执行切块规划。
6. 写出最终 JSON 与 `_run_summary.json`。

内部主链路：

```text
source(offline_md | github_rtd)
  -> preprocess
  -> route
  -> process(overview/quick_start/parameter_reference/list)
  -> chunk
  -> export(final json)
```


## 输出目录

- 文档级：`scripts/tmp/<run_id>/<doc_id>.json`
- 运行级：`scripts/tmp/<run_id>/_run_summary.json`

## Validation Checklist

执行结束后至少验证：

1. 命令执行无崩溃，输出目录存在。
2. 输出目录json文件存在。


