# BEIR RAG 评测模块

本模块提供统一 CLI：`python -m eval.beir.cli`，用于在 BEIR 公开数据集上评估当前项目的 RAG 检索链路。默认数据集为 `scifact`，向量检索必须使用项目现有 Milvus，embedding 和 reranker 复用 `backend/app/services` 的实现。

## 能力

- 自动下载并读取 BEIR `corpus`、`queries`、`qrels`，默认 split 为 `test`。
- 支持 `info`、`index`、`business_index`、`eval`、`full`、`compare` 流程。
- Milvus indexing 与 retrieval evaluation 分离；eval 阶段不会重复 corpus embedding。
- Milvus collection 新建时保留 `dataset`、`split`、`beir_doc_id`、`title`、`text` 和 `embedding`。
- collection 已存在且文档数等于当前 corpus 数量时默认跳过 corpus embedding/write；只有 `--force_reindex` 会重建。
- `--skip_index` 可直接复用已有 collection 做 query 检索。
- corpus embedding 支持 `--embedding_batch_size`，默认 32；query embedding 支持 `--query_batch_size`，默认 32，并批量缓存。
- 本地 embedding 检测到 CUDA 时优先使用 GPU；只能使用 CPU 时日志会明确提示较慢。
- 支持单路检索：`bm25`、`milvus`、`ripgrep`。
- 支持组合检索：`--retrievers milvus,bm25,ripgrep`，融合方法为 `rrf`、`weighted`、`concat_dedupe`。
- 支持 `hybrid`（Milvus + BM25）和 `hybrid_reranker`（Milvus + BM25 + reranker）。
- `agentic_router`、`full_rag` 可通过 `business_index` 接入真实业务 RAG；`pageindex`、`graphrag` 仍保留接口并在未支持时输出明确 warning/unsupported。
- 使用 BEIR `EvaluateRetrieval` 输出 `NDCG@K`、`MAP@K`、`Recall@K`、`Precision@K`、`MRR@K`，默认 K 为 `1,3,5,10,50,100`。
- 每个 query 记录检索耗时、命中文档、TopK 排名、是否命中 qrels。

## 安装

```powershell
cd E:\workspace\botree-knowledge
python -m pip install -r backend\requirements.txt
```

需要在 `backend/.env` 或环境变量中配置 Milvus、embedding、数据库等项目运行参数：

- `MILVUS_HOST`、`MILVUS_PORT`
- `EMBEDDING_PROVIDER`、`EMBEDDING_MODEL`、`EMBEDDING_DIM`
- 项目数据库连接配置

## 常用命令

查看数据集信息：

```powershell
python -m eval.beir.cli --mode info --dataset scifact
```

只构建 Milvus BEIR collection：

```powershell
python -m eval.beir.cli --mode index --dataset scifact --collection_name beir_scifact_eval
```

强制重建 Milvus collection：

```powershell
python -m eval.beir.cli --mode index --dataset scifact --collection_name beir_scifact_eval --force_reindex --embedding_batch_size 32
```

BM25 baseline：

```powershell
python -m eval.beir.cli --mode eval --dataset scifact --retriever bm25 --top_k 100
```

Milvus 复用已有 collection 评测：

```powershell
python -m eval.beir.cli --mode eval --dataset scifact --retriever milvus --collection_name beir_scifact_eval --skip_index --top_k 100
```

Milvus + BM25 RRF：

```powershell
python -m eval.beir.cli --mode eval --dataset scifact --retriever hybrid --collection_name beir_scifact_eval --skip_index --top_k 100
```

Hybrid + reranker：

```powershell
python -m eval.beir.cli --mode eval --dataset scifact --retriever hybrid_reranker --collection_name beir_scifact_eval --skip_index --top_k 100 --rerank true --reranker_score_order desc
```

任意组合检索：

```powershell
python -m eval.beir.cli --mode eval --dataset scifact --retrievers milvus,bm25,ripgrep --fusion rrf --collection_name beir_scifact_eval --skip_index --top_k 100
```

加权融合：

```powershell
python -m eval.beir.cli --mode eval --dataset scifact --retrievers milvus,bm25 --fusion weighted --weights milvus=0.6,bm25=0.4 --collection_name beir_scifact_eval --skip_index
```

全流程：加载数据、检查/构建 Milvus、执行检索评测、写报告：

```powershell
python -m eval.beir.cli --mode full --dataset scifact --retriever milvus --collection_name beir_scifact_eval --top_k 100
```

Agentic router 预留入口：

```powershell
python -m eval.beir.cli --mode eval --dataset scifact --retriever agentic_router
```

Full RAG 预留入口，默认不生成答案：

```powershell
python -m eval.beir.cli --mode eval --dataset scifact --retriever full_rag --include_answer false
```

多策略对比：

```powershell
python -m eval.beir.cli --mode compare --dataset scifact --collection_name beir_scifact_eval --skip_index --top_k 100 --max_queries 20
```

## 真实业务 RAG 评测

`agentic_router` 和 `full_rag` 会先读取业务映射，然后调用当前项目真实 `RetrievalGraph`。请先用 `business_index` 将 BEIR corpus 导入独立评测项目；默认一条 BEIR doc 对应一个真实 Document 和一个 Chunk，映射文件保存到 `eval/beir/results/{dataset}/doc_id_mapping.jsonl`。

导入 BEIR 到真实业务索引：

```powershell
python -m eval.beir.cli --dataset scifact --mode business_index --business_project_code EVAL_BEIR_SCIFACT --business_user_id beir_eval_user --business_index_targets milvus,bm25,ripgrep
```

强制重建仅允许作用于 `EVAL_BEIR_` 前缀项目：

```powershell
python -m eval.beir.cli --dataset scifact --mode business_index --business_project_code EVAL_BEIR_SCIFACT --business_user_id beir_eval_user --business_index_targets milvus,bm25,ripgrep --force_business_reindex
```

评测 agentic router：

```powershell
python -m eval.beir.cli --dataset scifact --mode eval --retriever agentic_router --business_project_code EVAL_BEIR_SCIFACT --business_user_id beir_eval_user --top_k 100 --max_queries 20
```

评测 full_rag，不调用最终 answer LLM：

```powershell
python -m eval.beir.cli --dataset scifact --mode eval --retriever full_rag --business_project_code EVAL_BEIR_SCIFACT --business_user_id beir_eval_user --top_k 100 --include_answer false --max_queries 20
```

评测 full_rag 并调用 answer LLM，建议先小样本：

```powershell
python -m eval.beir.cli --dataset scifact --mode eval --retriever full_rag --business_project_code EVAL_BEIR_SCIFACT --business_user_id beir_eval_user --top_k 100 --include_answer true --enable_online_answer true --max_queries 5
```

业务评测报告会额外输出 `unmapped_evidence.jsonl` 和 `answer_details.jsonl`；`report.md` 会展示业务项目、用户、索引 targets、真实权限过滤、answer LLM 开关、映射命中率、节点耗时和失败 query。

## CLI 参数

- `--dataset`：BEIR 数据集名称，例如 `scifact`、`fiqa`、`nfcorpus`、`trec-covid`。
- `--split`：qrels split，默认 `test`。
- `--mode`：`info`、`index`、`eval`、`full`、`compare`。
- `--retriever`：单路或预置策略，支持 `bm25`、`milvus`、`ripgrep`、`hybrid`、`hybrid_reranker` 等。
- `--retrievers`：逗号分隔的任意组合，例如 `milvus,bm25,ripgrep`。
- `--fusion`：组合检索融合方法，支持 `rrf`、`weighted`、`concat_dedupe`。
- `--weights`：加权融合权重，例如 `milvus=0.6,bm25=0.4`。
- `--top_k`：最终写入 BEIR results 的 TopK，默认 100。
- `--candidate_k`：融合或 rerank 前候选 TopK，默认 100。
- `--rerank`：是否对 Top100 候选重排，默认 false。
- `--reranker_score_order`：reranker 分数排序方向，支持 `desc`/`asc`，默认 `desc`。
- `--collection_name`：Milvus 测试 collection，默认 `beir_{dataset}_eval`。
- `--force_reindex`：显式删除并重建 collection。
- `--skip_index`：直接使用已有 collection，不执行 corpus indexing。
- `--embedding_batch_size`：corpus embedding batch size，默认 32。
- `--query_batch_size`：query embedding batch size，默认 32。
- `--k_values`：指标 K 值，默认 `1,3,5,10,50,100`。
- `--max_queries`：本地 smoke test query 限制。
- `--include_answer`：是否保留 full_rag 的答案相关输出字段，默认 false。
- `--enable_online_answer`：是否真正调用在线 answer LLM，默认 false；只有与 `--include_answer true` 同时传入时才会触发在线回答。
- `--output_dir`：报告目录，默认 `eval/beir/results/{dataset}/{timestamp}`。
- `--verbose`：开启 DEBUG 日志。

## 输出文件

每次运行会写入：

- `metrics.json`：配置、指标、命中摘要、耗时、错误与 warning。
- `query_details.csv`：每个 query 的 Top1/3/5/10/100、hit@K、首个命中 rank、路由、融合、rerank 与耗时。
- `query_details.jsonl`：完整 query trace，包含各路 raw hits、融合结果、rerank 前后 hits、final hits，以及前 3 个 rerank 输入样例。
- `rerank_debug.csv`：rerank 前后 rank 对比，包含 `old_rank`、`new_rank`、`reranker_score`、`is_qrels_hit`。
- `failed_cases.md`：Top100 miss、Top100 hit but Top10 miss、reranker rank dropped。
- `report.md`：人类可读的指标、rerank_before/rerank_after、分阶段耗时、慢 query 和 warning 汇总。
- `compare_report.md`：仅 compare 模式生成。
- `beir_eval.log`：结构化运行日志。

## 接入自建测试集

核心边界如下：

- 数据加载：`eval/beir/dataset_loader.py`
- 检索 adapter：`eval/beir/adapters/`
- Milvus indexing：`eval/beir/indexer.py`
- 指标：`eval/beir/metrics.py`
- 报告：`eval/beir/report_writer.py`
- 公共 schema：`eval/beir/schemas.py`

自建测试集只需提供与 BEIR 等价的 `corpus`、`queries`、`qrels` 字典，并实现或复用 adapter 返回 `SearchHit`，即可继续使用统一 runner、metrics 和 report。

## 本地 reranker 与 K 值约定

本项目线上真实流程要求使用本地部署 reranker。当前默认模型路径可通过数据库 `model_configs`
的默认 `model_type=reranker` 配置，或通过环境变量 `RERANKER_MODEL_PATH` 指向，例如：

```powershell
$env:RERANKER_MODEL_PATH="E:\workspace\botree-agent\backend\workspace\bge-reranker-v2-m3"
```

后端服务启动时会调用 `RerankerService.warmup_local_reranker()`，提前把
`sentence_transformers.CrossEncoder` 加载到进程缓存中；评测 CLI 在需要真实 reranker
的任务开始前也会先预热一次。若 `--require_real_reranker true` 且模型不可用，评测会直接失败，
不会静默降级为启发式排序。

检查本地 reranker 是否可加载：

```powershell
python -m eval.beir.cli --dataset scifact --mode check_reranker
```

K 值在评测和真实 RAG 中分开记录，不能混用：

- `--candidate_k`：每一路检索器召回候选数量，默认 100。
- `--rerank_top_k`：送入真实 reranker 的融合候选数量，默认 100。
- `--eval_top_k`：用于 BEIR 指标计算的最大结果数，默认 100。
- `--answer_top_k`：最终进入答案生成的证据数量，当前真实链路固定为 10。

推荐真实流程评测命令：

```powershell
python -m eval.beir.cli --dataset scifact --mode eval --retriever full_rag `
  --business_project_code EVAL_BEIR_SCIFACT `
  --business_user_id beir_eval_user `
  --candidate_k 100 --rerank_top_k 100 --eval_top_k 100 --answer_top_k 10 `
  --include_answer false --max_queries 20
```
