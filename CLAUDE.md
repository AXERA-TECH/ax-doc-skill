# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

`ax-doc-skill` 是三个面向 RTD 的文档处理 Skills，构成一条完整的离线流水线：

```
RTD Markdown → rtd-to-chunk → chunk-to-db → pulsar2-doc-search
```

并在 CI 流程中，预构建爱芯元智自研 NPU 工具链 [Pulsar2](https://github.com/AXERA-TECH/pulsar2-docs) 的官方仓库文档 LanceDB 数据库。


每个 Skill 目录结构相同：`agents/`（Skill接口描述）、`scripts/`（可执行脚本）、`SKILL.md`（Skill 行为说明）。

## 常用命令

### 安装依赖

```bash
pip install -r requirements.txt
```


### 单独运行各 Skill

```bash
# rtd-to-chunk
cd rtd-to-chunk
python scripts/chunk.py --input-url https://github.com/<org>/<repo> --output-dir scripts/tmp

# chunk-to-db
cd chunk-to-db
python scripts/build_db.py --input-dir ../rtd-to-chunk/scripts/tmp/<run_id> --db-dir ../pulsar2-doc-search/assets/pulsar2_rtd --table pulsar2-doc --mode overwrite --embedding-provider none

# pulsar2-doc-search 健康检查
cd pulsar2-doc-search
python scripts/server_db.py --db-dir assets/pulsar2_rtd --table pulsar2-doc --action health
```

## 架构说明

### rtd-to-chunk 内部流程

核心逻辑在 `rtd-to-chunk/scripts/rtd2chunk_pipeline_pkg/`：

- `engine.py`：编排单文档和批量流程（asyncio + Semaphore 控制并发）
- `rules.py`：文档分类与类型处理器（`rule_based_classify` + `PROCESSOR_MAP`）
- `models.py`：核心数据结构——`RawDocument` → `DocumentClassification` → `DocumentChunk` → `PipelineResult`
- `pulsar2_chunking.py`：`preprocess_content` + `plan_chunks`，Pulsar2 文档定向切块策略
- `sources.py`：输入源适配，支持本地目录和 GitHub URL
- `cli.py`：`chunk.py` 的实际驱动层

**DocumentType** 枚举共四类：`overview`、`quick_start`、`parameter_reference`、`list`。修改切块策略时主要改 `pulsar2_chunking.py` 和 `rules.py`。

### chunk-to-db 与 pulsar2-doc-search 的数据路径

- `chunk-to-db/scripts/build_db.py`：读取 rtd-to-chunk 输出的 JSON，写入 LanceDB
- LanceDB 默认落在 `pulsar2-doc-search/assets/pulsar2_rtd/`，表名 `pulsar2-doc`
- `pulsar2-doc-search/scripts/server_db.py`：对上述 DB 执行检索，支持 one-shot 和 `--stdio` 常驻 JSON 协议


## 关键约束

- `rtd-to-chunk` 只负责切块，不写 DB；`chunk-to-db` 只写 DB，不做检索；`pulsar2-doc-search` 只做检索，不修改 DB。职责边界不应跨越。
- 修改切块策略，优先改 `rtd-to-chunk/scripts/rtd2chunk_pipeline_pkg/`，不改其他 Skill。
- `chunk-to-db` 向量构建失败时应降级为 FTS，不应中断入库流程。
- FTS 建索引为 best effort，索引失败不阻断核心入库。
- 调试切块输出：直接检查 `rtd-to-chunk/scripts/tmp/<run_id>/` 下的文档 JSON 和 `_run_summary.json`；换 `run_id` 重跑避免覆盖历史结果。
