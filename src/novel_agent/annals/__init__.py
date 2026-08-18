from novel_agent.annals.research import NullResearchPort, ResearchPort, WebResearchPort
from novel_agent.annals.skeleton import (
    CANONICAL_TITLE_RULE,
    AnnalsSkeleton,
    build_skeleton,
    confirm_errors,
    fill_skeleton,
    patch_kernel_title_rule,
)
from novel_agent.annals.span import (
    YEAR_MAX,
    YEAR_MIN,
    derive_story_span,
    extract_years,
    parse_story_year,
    plot_hit_years,
    widen_span,
)

__all__ = [
    "CANONICAL_TITLE_RULE",
    "YEAR_MAX",
    "YEAR_MIN",
    "AnnalsSkeleton",
    "NullResearchPort",
    "ResearchPort",
    "WebResearchPort",
    "build_skeleton",
    "confirm_errors",
    "derive_story_span",
    "extract_years",
    "fill_skeleton",
    "parse_story_year",
    "patch_kernel_title_rule",
    "plot_hit_years",
    "widen_span",
]
