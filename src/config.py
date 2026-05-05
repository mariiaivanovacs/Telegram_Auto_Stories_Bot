import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ChannelConfig:
    username: str
    display_name: str = ""

    def __post_init__(self) -> None:
        self.username = self.username.strip().lstrip("@")


@dataclass
class ProductConfig:
    id: str
    canonical: str
    category: str
    display_name: str
    aliases: list
    regex: str
    default_price: int | None = None
    exclude_if_contains: list = field(default_factory=list)


@dataclass
class AdminConfig:
    telegram_id: int
    username: str = ""


@dataclass
class PricingSettings:
    discount: int = 500
    large_change_threshold: int = 3000


@dataclass
class ScheduleSettings:
    run_time: str = "09:00"
    timezone: str = "Europe/Moscow"


@dataclass
class StorySettings:
    blur_radius: int = 8
    darken_alpha: int = 120
    panel_color: tuple = (0, 0, 0, 160)
    panel_corner_radius: int = 24
    padding_x: int = 60
    padding_y: int = 48
    font_path: str = "assets/Inter-SemiBold.ttf"
    font_size_title: int = 42
    font_size_body: int = 34
    font_size_price: int = 38
    line_height: float = 1.5
    accent_color: str = "#F5A623"
    background_selection: str = "random"


@dataclass
class Settings:
    api_id: int
    api_hash: str
    bot_token: str
    admin_id: int
    phone: str
    channels: list
    products: list
    admins: list
    pricing: PricingSettings
    schedule: ScheduleSettings
    story: StorySettings
    price_list_template: str


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = _load()
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = _load()
    return _settings


def _load() -> Settings:
    load_dotenv()

    config_path = Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(
            "config.yaml not found — copy config.example.yaml to config.yaml and fill it in"
        )

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    pricing = PricingSettings(**cfg.get("pricing", {}))
    schedule = ScheduleSettings(**cfg.get("schedule", {}))

    story_raw = dict(cfg.get("story", {}))
    panel_color_list = story_raw.pop("panel_color", [0, 0, 0, 160])
    story = StorySettings(panel_color=tuple(panel_color_list), **story_raw)

    channels = [ChannelConfig(**c) for c in cfg.get("channels", [])]
    products = [ProductConfig(**p) for p in cfg.get("products", [])]

    admin_id_env = int(os.environ.get("TELEGRAM_ADMIN_ID", 0))
    admins_raw = cfg.get("admins", [])
    if admin_id_env:
        admins_raw = [
            a for a in admins_raw
            if int(a.get("telegram_id", 0)) not in {0, 987654321}
        ]
        if all(int(a.get("telegram_id", 0)) != admin_id_env for a in admins_raw):
            admins_raw.append({"telegram_id": admin_id_env, "username": ""})
    elif not admins_raw:
        admins_raw = []
    admins = [AdminConfig(**a) for a in admins_raw]

    return Settings(
        api_id=int(os.environ.get("TELEGRAM_API_ID", 0)),
        api_hash=os.environ.get("TELEGRAM_API_HASH", ""),
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        admin_id=admin_id_env,
        phone=os.environ.get("TELEGRAM_PHONE", ""),
        channels=channels,
        products=products,
        admins=admins,
        pricing=pricing,
        schedule=schedule,
        story=story,
        price_list_template=cfg.get("price_list_template", ""),
    )
