"""离线评测入口。默认不访问网络、不打付费 API。"""

from novel_agent.eval.retrieval import (
    HASH_MIN_HIT_RATE,
    HASH_MIN_MRR,
    HASH_MIN_RECALL_AT_1,
    HASH_MIN_RECALL_AT_3,
    HASH_MUST_HIT_AT_3,
    EvalReport,
    default_golden_path,
    format_report,
    load_golden,
    run_retrieval_eval,
    seed_golden_project,
)

__all__ = [
    "HASH_MIN_HIT_RATE",
    "HASH_MIN_MRR",
    "HASH_MIN_RECALL_AT_1",
    "HASH_MIN_RECALL_AT_3",
    "HASH_MUST_HIT_AT_3",
    "EvalReport",
    "default_golden_path",
    "format_report",
    "load_golden",
    "run_retrieval_eval",
    "seed_golden_project",
]
