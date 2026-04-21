---
name: rtd-to-chunk
description: Convert RTD-style markdown (local files or GitHub repository/tree/root URLs) into structured chunk JSON for retrieval and downstream DB build. Use when running `rtd-to-chunk/scripts/execute.py`, validating chunk output contracts, debugging preprocessing/classification/chunking behavior, exporting retrieval_text for review, or iterating rules in `scripts/rtd2chunk_pipeline_pkg/`.
---

# RTD2Chunk Pipeline

执行 RTD 文档到 chunk JSON 的单一流水线。

## 目标与边界

- 目标：单次离线执行，把 RTD markdown 转为结构化 chunks。
- 边界：仅使用 `execute.py`作为流程入口 。
- 输入：离线 markdown 目录，或一个/多个 GitHub 仓库/目录 URL。
- 输出：仅保存最终产物，供检索、评估、下游构建使用。

## Quick Start

离线目录模式：

```bash
python scripts/execute.py \
  --input-dir <offline_md_dir> \
  --output-dir <output_root_dir> \
  --router-mode rule \
  --glob "*.md" \
  --max-concurrency 4 \
  --run-id <run_id_optional>
```

GitHub URL 模式（可重复 `--input-url`）：

```bash
python scripts/execute.py \
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
- `--router-mode llm` 时配置 `OPENAI_API_KEY`（可选 `OPENAI_BASE_URL`）。

## CLI 参数

- `--input-dir`：离线 markdown 输入目录（与 `--input-url` 二选一）。
- `--input-url`：GitHub 仓库/目录 URL 输入（与 `--input-dir` 二选一，可重复）。
- `--output-dir`：输出根目录（必填）。
- `--glob`：输入文件匹配模式，默认 `*.md`。
- `--max-concurrency`：并发度，默认 `4`。
- `--router-mode`：`rule` 或 `llm`，默认 `rule`。
- `--llm-model`：仅 `--router-mode llm` 时生效。
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
  -> route(rule | llm->fallback rule)
  -> process(overview/quick_start/parameter_reference/list)
  -> chunk
  -> export(final json)
```


## 输出目录

- 文档级：`outputs/<run_id>/<doc_id>.json`
- 运行级：`outputs/<run_id>/_run_summary.json`

## Validation Checklist

交付前至少验证：

1. 命令执行无崩溃，输出目录存在。
2. `_run_summary.json` 存在且计数正确。
3. 每个文档 JSON 包含 `chunks`，且关键字段完整。
4. 抽样确认 `retrieval_text` 不包含 `分块类型:`。

## LLM 环境变量

- `OPENAI_API_KEY`：`--router-mode llm` 必需。
- `OPENAI_BASE_URL`：可选，默认 `https://api.openai.com/v1`。

## Debug Helpers

- 使用 [`scripts/debug.py`](scripts/debug.py) 导出某目录下全部 `retrieval_text` 到审阅文件。
- 修改策略后用新的 `run_id` 重跑，避免覆盖旧结果并方便 diff。

## Edit Scope

优先修改目录：`scripts/rtd2chunk_pipeline_pkg/`。

不要在本技能内新增：

- 多阶段迭代子命令，
- 配置文件加载框架，
- 额外持久化层。
