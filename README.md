# ax-doc-skill

一组面向RTD文档处理 Skills，实现从原始 RTD 文档到可检索向量数据库的完整离线流水线。

## 概述

```
RTD Markdown 文档
      ↓
  rtd-to-chunk        将文档切分为结构化 chunk JSON
      ↓
  chunk-to-db         将 chunk JSON 写入 LanceDB
      ↓
pulsar2-doc-search    对 LanceDB 执行 FTS / 向量 / 混合检索
```

三个 Skill 各司其职，可单独使用，也可按顺序串联完成端到端入库与检索。

## 一键构建 Pulsar2 DB

项目根目录提供脚本 `build_pulsar2_db_pipeline.py`，用于一键执行：

1. 从 `https://github.com/AXERA-TECH/pulsar2-docs` 拉取并切分文档（`rtd-to-chunk/scripts/chunk.py`）
2. 构建 LanceDB（`chunk-to-db/scripts/build_db.py`）
3. 覆盖 `pulsar2-doc-search/assets/pulsar2_rtd`（默认会先删除旧目录再重建）

仅 FTS（默认）：

```bash
python3 build_pulsar2_db_pipeline.py
```

向量构建（需要 `OPENAI_API_KEY`）：

```bash
python3 build_pulsar2_db_pipeline.py --embedding-provider openai
```

常用参数：

- `--repo-url`：指定 GitHub 仓库/目录 URL
- `--run-id`：指定本次产物目录名
- `--max-concurrency`：指定切分阶段并发度
- `--log-level`：指定 `rtd-to-chunk` 日志级别
- `--chunk-output-root`：指定 chunk 输出根目录
- `--table`：指定目标表名（默认 `pulsar2-doc`）
- `--db-subdir`：指定 `pulsar2-doc-search/assets` 下 DB 子目录（默认 `pulsar2_rtd`）
- `--keep-existing-db`：构建前不删除现有 DB 目录（仍以 `overwrite` 模式写表）

## Skills

### rtd-to-chunk

将 RTD 风格的 Markdown 文档（本地目录或 GitHub URL）解析为结构化 chunk JSON，供下游入库和检索使用。

- 支持离线目录与 GitHub 仓库/目录 URL 两种输入模式
- 使用轻量 rule-based 分类
- 输出每文档一个 JSON 及 `_run_summary.json`

### chunk-to-db

将 `rtd-to-chunk` 产出的 chunk JSON 写入 LanceDB，创建 FTS 索引，可选生成向量列。

- 支持 `overwrite` 和 `append` 两种写入模式
- 向量构建依赖 OpenAI Embeddings，环境变量不满足时自动降级为纯 FTS 构建
- 输出写入路径由 `pulsar2-doc-search` 读取

### pulsar2-doc-search

对已构建的 LanceDB 执行检索与健康检查，专注于 Pulsar2 CLI、AX 系列产品模型部署及 NPU 算子相关内容。

- 支持 `health`、`list-tables`、`fts-search`、`vector-search`、`hybrid-search` 五种 action
- 支持 one-shot 调用和 `--stdio` 常驻 JSON 协议

## 环境变量

| 变量 | 用途 | 必需场景 |
|------|------|----------|
| `OPENAI_API_KEY` | Embeddings | 向量构建/检索 |
| `OPENAI_BASE_URL` | 自定义 API 网关 | 可选 |



## 在 Nanobot 中使用

参考 [docs/assets/nanobot.md](docs/assets/nanobot.md) 了解如何将本项目的 Skills 接入 Nanobot，并通过飞书进行端到端验证。

## TODO LIST
- [ ] 完善使用文档
  - [x]  nanobot
  - [ ]  Claude Code
  - [ ]  CodeX
  - [ ] openclaw
  - [ ]  hermes
- [ ] 搭建评估体系,实现自适应chunk策略迭代闭环
- [ ] 更加轻量化
- [ ] ...
