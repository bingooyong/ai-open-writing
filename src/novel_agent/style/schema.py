"""Project writing-style pack stored in project.settings['style']."""

from pydantic import BaseModel, ConfigDict, Field


class StyleProfile(BaseModel):
    """Rhythm knobs; compiled rules/samples are what Writer actually sees."""

    model_config = ConfigDict(extra="ignore")

    paragraph_unit: str
    avg_sentence_chars: list[int] = Field(min_length=2, max_length=2)
    punch_line_max_chars: int
    dialogue_ratio_hint: float
    narrator_distance: str
    interior: str
    time_place: str
    result_first: bool


class StylePack(BaseModel):
    """Frozen or project-copied style pack. Invalid payloads must not crash readers."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    mid_style: str | None = None
    profile: StyleProfile
    rules: str = Field(min_length=1)
    samples: list[str] = Field(min_length=1)
