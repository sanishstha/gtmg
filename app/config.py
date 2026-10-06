"""Runtime settings. Prices are a configured table, not a live lookup."""

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_FEEDS = ",".join(
    [
        "https://openai.com/news/rss.xml",
        "https://blogs.nvidia.com/feed/",
        "https://huggingface.co/blog/feed.xml",
    ]
)
DEFAULT_PRICES = ",".join(
    [
        "gpt-4.1-mini=0.40:1.60",
        "gpt-4.1=2.00:8.00",
        "gpt-4.1-nano=0.10:0.40",
        "gpt-4o-mini=0.15:0.60",
    ]
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://desk:desk@localhost:5432/desk"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    rss_feeds: str = DEFAULT_FEEDS
    rss_items_per_feed: int = 10
    model_prices: str = DEFAULT_PRICES

    def feed_urls(self) -> list[str]:
        return [item.strip() for item in self.rss_feeds.split(",") if item.strip()]

    def price_for(self, model: str) -> tuple[Decimal, Decimal] | None:
        for entry in self.model_prices.split(","):
            item = entry.strip()
            if not item or "=" not in item or ":" not in item:
                continue
            name, raw_prices = item.split("=", 1)
            if name.strip() != model:
                continue
            input_price, output_price = raw_prices.split(":", 1)
            return Decimal(input_price), Decimal(output_price)
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal | None:
    price = get_settings().price_for(model)
    if price is None:
        return None
    input_price, output_price = price
    total = (Decimal(tokens_in) * input_price + Decimal(tokens_out) * output_price) / Decimal(1_000_000)
    return total.quantize(Decimal("0.000001"))
