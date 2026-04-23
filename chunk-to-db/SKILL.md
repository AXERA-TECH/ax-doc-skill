---
name: chunk-to-db
description: Build the LanceDB vector database from JSON result files produced by the rtd-to-chunk parsing skill using the script scripts/build_db.py.
---

# Chunk To DB

执行 `chunk JSON -> LanceDB` 构建流程。

## Scope

- 仅负责数据库构建与增量写入。
- 不负责查询与健康检查。
- 查询能力已迁移到 `pulsar2-doc-search`（`scripts/server_db.py`）。

## Quick Start

本地构建（仅 FTS）：

```bash
python scripts/build_db.py \
  --input-dir ../rtd-to-chunk/scripts/tmp/<run_id> \
  --db-dir ../pulsar2-doc-search/assets/pulsar2_rtd \
  --table pulsar2-doc \
  --mode overwrite \
  --embedding-provider none
```

本地构建（含向量）：

```bash
python scripts/build_db.py \
  --input-dir ../rtd-to-chunk/scripts/tmp/<run_id> \
  --db-dir ../pulsar2-doc-search/assets/pulsar2_rtd \
  --table pulsar2-doc \
  --mode overwrite \
  --embedding-provider openai
```

## Workflow

1. 选择输入 chunk 目录（来自 `rtd-to-chunk` 输出）。
2. 使用 `build_db.py` 写入 LanceDB（`overwrite` 或 `append`）。
3. 由 `pulsar2-doc-search/scripts/server_db.py` 执行后续 `health/list/search`。

## Script API

### scripts/build_db.py

用途：把 `rtd-to-chunk` 产出的文档 JSON 入库到 LanceDB，创建 FTS（best effort），可选生成向量列。

核心参数：

- `--input-dir`（必填）：chunk JSON 目录
- `--db-dir`（必填）：目标 LanceDB 目录
- `--table`（必填）：目标表名
- `--mode`：`overwrite|append`，默认 `overwrite`
- `--embedding-provider`：`none|openai`，默认 `none`
- `--embedding-model`：默认 `text-embedding-3-small`
- `--embedding-batch-size`：默认 `64`
- `--vector-column`：默认 `vector`

输出字段（stdout JSON）：

- `status`：`ok|error`
- `rows_written`：写入行数
- `embedded_rows`：成功生成向量行数
- `vector_dim`：向量维度（未生成则 `null`）
- `fts_index`：FTS 建索引结果（best effort）

## Current Data Contract

输入要求（来自 `rtd-to-chunk` 结果）：

- 每个文档一个 JSON，含 `doc_id`、`title`、`url`、`classification`、`chunks`。
- 每个 chunk 至少可解析出：`chunk_id`、`chunk_type`、`section_path`、`display_text`、`retrieval_text`。

默认入库列：

- `chunk_id`
- `doc_id`
- `title`
- `url`
- `doc_type`
- `chunk_type`
- `section_path`
- `display_text`
- `retrieval_text`
- `metadata_json`
- `structured_data_json`
- `source_file`
- `vector`（可选，列名由 `--vector-column` 控制）

## Validation Checklist

至少执行以下检查：

1. `build_db.py` 返回 `status=ok`。
2. `rows_written > 0`。
3. 若启用向量，`embedded_rows > 0` 且 `vector_dim` 非空。
4. 使用 `pulsar2-doc-search/scripts/server_db.py --action health` 返回 `status=ok`。

## Environment

当使用向量构建时：

- `OPENAI_API_KEY`：`embedding-provider=openai` 时必需
- `OPENAI_BASE_URL`：可选，用于网关或兼容服务



## Constraints

- 不在 `chunk-to-db` 内修改 chunk 切分策略。
- 不修改输入 chunk 源 JSON。
- 优先使用向量构建方式,当环境变量不满足要求时,告知用户,并且切换为FTS构建.
- 将 FTS 建索引视为 best effort，不因索引失败阻断核心入库。
