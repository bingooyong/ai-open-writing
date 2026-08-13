"""配置系统(M0.5):四模型槽位 + 预算参数,env / .env 加载。

环境变量约定(前缀 NOVEL_,嵌套用双下划线):
  NOVEL_CREATIVE__PROVIDER=anthropic
  NOVEL_CREATIVE__MODEL=...
  NOVEL_CREATIVE__API_KEY=...
  NOVEL_JUDGE__PROVIDER=openai_compat ...
密钥只经环境变量进入,绝不落库、不落日志(Spec §9)。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["mock", "openai_compat", "anthropic"]


class SlotConfig(BaseModel):
    """一个模型槽位(Spec D8:creative/review/judge/extract 四槽)。"""

    provider: ProviderName = "mock"
    model: str = "mock-model"
    family: str = "mock"
    api_key: SecretStr | None = None
    base_url: str | None = None
    input_price_usd_per_million: float | None = None
    output_price_usd_per_million: float | None = None

    @field_validator("family", mode="before")
    @classmethod
    def _canonical_family(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _require_key_for_real_provider(self) -> "SlotConfig":
        if self.provider != "mock":
            if self.api_key is None:
                raise ValueError(
                    f"provider={self.provider} 需要 api_key"
                    "(通过环境变量 NOVEL_<槽位>__API_KEY 提供)"
                )
            if not self.family or self.family == "mock":
                raise ValueError("真实 provider 必须显式配置非 mock 的 family")
        prices = (self.input_price_usd_per_million, self.output_price_usd_per_million)
        if any(price is not None for price in prices) and any(
            price is None or price <= 0 for price in prices
        ):
            raise ValueError("价格覆盖必须同时提供正数 input/output USD per million")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOVEL_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 四模型槽位(Spec D8)
    creative: SlotConfig = SlotConfig()
    review: SlotConfig = SlotConfig()
    judge: SlotConfig = SlotConfig()
    extract: SlotConfig = SlotConfig()

    # 存储
    db_path: Path = Path("data/novel.db")

    # 本地写作台 API(默认只绑 localhost);前端 Vite 固定 18765,避开 5173
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    web_port: int = 18765
    cors_origins: str = (
        "http://localhost:18765,http://127.0.0.1:18765,"
        "http://[::1]:18765"
    )

    # 预算(PRD §8.11;Stage 1 Writer B + Reader Advocate 需要两轮修订余量)
    max_calls_per_chapter: int = 40
    max_tokens_per_batch: int | None = None

    # 修订轮次上限:领域固定语义(Spec §6 N7),不可通过配置放宽
    max_revision_rounds: Literal[2] = 2

    # 卷工厂:已规划但未锁定的滚动窗口(默认约 5 章)
    rolling_window: int = 5

    # 调试:默认不落完整提示词与正文(PRD §18.3)
    debug_log: bool = False

    @model_validator(mode="after")
    def _judge_must_differ_from_creative(self) -> "Settings":
        """Spec D8:Judge 与 Writer 须不同模型族。"""
        j, c = self.judge, self.creative
        if j.provider != "mock" and c.provider != "mock" and j.family == c.family:
            raise ValueError(
                "judge.family 与 creative.family 不得相同(Spec D8);"
                "请显式配置不同模型族"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """测试用:清除配置缓存。"""
    get_settings.cache_clear()
