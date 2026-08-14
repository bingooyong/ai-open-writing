# 检索评测决策（Stage 2）

冻结金标：`eval/retrieval/golden_queries.json`（14 问）。语料由 `seed_golden_project` 植入，覆盖人物、关系、场景、冲突、爽点、章摘要，并保留「北境商队」负例。

默认路径只跑 `HashEmbedding`，走生产 `MemoryRetrieval.retrieve`（Lance 距离转向量分 + `lexical_overlap`）。pytest / 默认 CI 不打付费嵌入。`--compare-real` 仅在 `NOVEL_EMBEDDING__PROVIDER=openai_compat` 且已配 key 时可用。

## 实测（hash 混合，2026-08-14）

| 指标 | hash 混合（生产） | 词面-only 对照 |
|---|---:|---:|
| recall@1 | 0.500 | 0.643 |
| recall@3 | 0.786 | 1.000 |
| recall@8 / hit_rate | 1.000 | 1.000 |
| MRR | 0.688 | — |
| pollution@3 | 0.000 | — |

文档化下限（`HASH_MIN_*`）：recall@1 ≥ 0.40，recall@3 ≥ 0.70，hit_rate ≥ 0.85，MRR ≥ 0.55。字面问句 `HASH_MUST_HIT_AT_3` 必须 Top-3 命中。

## hash 混合输在哪

词面-only 全面优于 hash 混合。hash 向量在小语料上把若干词面第一名挤出 Top-3：

- `character-mei-hostage`（「苏棠被扣在哪里」）：词面第 1，混合第 4
- `summary-ch1`（「第一章的核心事件是什么」）：词面第 1，混合第 4
- `implication-contract`（「谁被逼着卖身换亲人平安」）：词面第 3，混合第 8

字面重合足够的问句（西市火灾、晚生说书、兄妹、胁迫、茶楼段子、衙役、解释权、讲述者代价）hash 混合已经稳。改写/暗示类不是系统性地「完全找不到」，而是被噪声向量往后推。

负例「北境商队」未进入 Top-3；Top-8 有时出现，因为 hash 向量对无重叠文本仍给相近的底分。

## 要不要把默认换成真实嵌入

**不要。** 保持默认 `embedding.provider=mock`（`HashEmbedding`）。

1. 金标上 hash 混合已过文档化下限，字面问句够用。
2. 词面-only 已经 recall@3 = 1.0。当前短板是 **hash 向量噪声**，不是「缺语义模型」。先换付费嵌入解决不了「默认 CI 不能付钱」，也绕开了更便宜的杠杆（提高词面权重或检索时忽略 mock 向量）。
3. 真实嵌入对改写/暗示/异名可能有帮助，但必须 `--compare-real` 且自备 `openai_compat` 槽位。本仓不把它设成默认，也不在 pytest 里跑。

若下一刀要动检索本身（本切片不动）：先做「词面权重 / 向量底分」的小实验，用这套金标看 recall@3 会不会贴近词面-only；确认 mock 向量在拖后腿再考虑真实嵌入。
