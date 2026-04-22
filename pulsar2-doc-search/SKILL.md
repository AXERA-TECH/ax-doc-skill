---
name: pulsar2-doc-search
description: Query existing Pulsar2 LanceDB with health/list/FTS/vector/hybrid retrieval using `scripts/server_db.py` and local assets under `assets/pulsar2_rtd`.
---

# Pulsar2 Doc Search

执行 `LanceDB 检索与健康检查`，不负责构建入库。

## Quick Start

健康检查：

```bash
python scripts/server_db.py \
  --db-dir assets/pulsar2_rtd \
  --table pulsar2-doc \
  --action health
```

FTS 查询：

```bash
python scripts/server_db.py \
  --db-dir assets/pulsar2_rtd \
  --table pulsar2-doc \
  --action fts-search \
  --query "quick start" \
  --limit 3
```

混合检索（向量+FTS）：

```bash
python scripts/server_db.py \
  --db-dir assets/pulsar2_rtd \
  --table pulsar2-doc \
  --action hybrid-search \
  --query "quick start" \
  --limit 3 \
  --embedding-provider openai
```

## Scope

- 仅负责查询和健康检查：`health/list-tables/fts-search/vector-search/hybrid-search`
- 支持 one-shot 和 `--stdio` 常驻 JSON 协议
- 不负责 chunk 生成和数据库构建

## Script API

### scripts/server_db.py

核心参数：

- `--db-dir`：默认 `assets/pulsar2_rtd`
- `--table`：默认 `pulsar2-doc`
- `--action`：`health|list-tables|fts-search|vector-search|hybrid-search`
- `--query`：search 类 action 必填
- `--limit`：默认 `5`
- `--vector-column`：默认 `vector`
- `--embedding-provider`：`none|openai`，默认 `none`
- `--embedding-model`：默认 `text-embedding-3-small`
- `--alpha`：混合检索向量分支权重，默认 `0.8`
- `--rrf-k`：RRF 常量，默认 `60.0`
- `--stdio`：启用常驻模式

stdio 请求示例：

```json
{"action":"fts-search","table":"pulsar2-doc","query":"quick start","limit":3}
```

## Validation Checklist

1. `--action health` 返回 `status=ok`
2. `--action fts-search` 返回至少 1 条
3. 启用向量时，`vector-search/hybrid-search` 返回 `status=ok`

## Environment

向量或混合检索时需要：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`（可选）
