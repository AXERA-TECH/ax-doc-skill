---
name: chunk-to-db
description: Build LanceDB from rtd-to-chunk outputs JSON, reuse existing `*_rtd` databases when available, and run health/search workflows with `scripts/build_db.py` and `scripts/server_db.py`. Use when validating DB readiness, running FTS/vector/hybrid retrieval, or troubleshooting chunk-to-db ingestion issues.
---

# Chunk To DB

执行 `chunk JSON -> LanceDB` 并提供检索与健康检查。

## Quick Start

优先做健康检查（复用已有 DB）：

```bash
python scripts/server_db.py \
  --db-dir assets/pulsar2_rtd \
  --table pulsar2-doc \
  --action health
```

本地构建（仅 FTS）：

```bash
python scripts/build_db.py \
  --input-dir ../rtd-to-chunk/scripts/tmp/<run_id> \
  --db-dir assets/pulsar2_rtd \
  --table pulsar2-doc \
  --mode overwrite \
  --embedding-provider none
```

FTS 冒烟检索：

```bash
python scripts/server_db.py \
  --db-dir assets/pulsar2_rtd \
  --table pulsar2-doc \
  --action fts-search \
  --query "quick start" \
  --limit 3
```

## Default Strategy

按以下优先级执行：

1. 复用已有 `assets/<doc_name>_rtd/`，先跑 `health`。
2. 本地不存在或不可用，或用户要求重建时，使用 `scripts/build_db.py` 从 chunk JSON 构建。

## Workflow

标准流程：

1. 选择目标 `db-dir` 与 `table`（默认 `pulsar2-doc`）。
2. 构建阶段使用 `build_db.py` 写入数据并创建 FTS 索引（best effort）。
3. 查询阶段使用 `server_db.py` 执行 `health/list-tables/fts-search/vector-search/hybrid-search`。
4. 需要常驻服务时，使用 `--stdio` 行分隔 JSON 协议。

## Script API

### scripts/build_db.py

用途：把 `rtd-to-chunk` 产出的文档 JSON 入库到 LanceDB，创建 FTS（best effort），可选生成向量列。

核心参数：

- `--input-dir`（必填）：chunk JSON 目录
- `--db-dir`（必填）：目标 LanceDB 目录（建议 `assets/<doc>_rtd`）
- `--table`（必填）：目标表名（建议 `xxx_-doc`）
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

### scripts/server_db.py

用途：健康检查、列举表、FTS/向量/混合检索；支持 one-shot 和 `--stdio` 常驻模式。

核心参数：

- `--db-dir`（必填）
- `--table`：默认 `pulsar2-doc`（建议显式传入，如 `pulsar2-doc`）
- `--action`：`health|list-tables|fts-search|vector-search|hybrid-search`（默认 `health`）
- `--query`：search 类 action 必填
- `--limit`：默认 `5`
- `--vector-column`：默认 `vector`
- `--embedding-provider`：`none|openai`，默认 `none`
- `--embedding-model`：默认 `text-embedding-3-small`
- `--alpha`：混合检索向量分支权重，默认 `0.8`
- `--rrf-k`：RRF 常量，默认 `60.0`
- `--stdio`：启用常驻 stdio 模式

stdio 请求/响应约定：

- 请求：每行一个 JSON（示例：`{"action":"fts-search","table":"pulsar2-doc","query":"quick start","limit":3}`）
- 响应：每行一个 JSON，包含 `status`，search 类 action 附带 `count`、`records`

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

1. `server_db.py --action health` 返回 `status=ok`。
2. `server_db.py --action fts-search` 至少返回 1 条结果。
3. 若启用向量：`vector-search` 或 `hybrid-search` 返回结果且无 embedding 错误。
4. 抽样检查结果记录中 `retrieval_text` 非空，`chunk_id` 唯一。

## Environment

当使用向量构建或向量/混合检索时：

- `OPENAI_API_KEY`：`embedding-provider=openai` 时必需
- `OPENAI_BASE_URL`：可选，用于网关或兼容服务

## Constraints

- 不在 `chunk-to-db` 内修改 chunk 切分策略。
- 不修改输入 chunk 源 JSON。
- 将 FTS 建索引视为 best effort，不因索引失败阻断核心入库。
- 优先复用已有数据库，无法满足再本地重建。
