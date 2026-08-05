from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ConfigurationError

BLOCKED_LIVE_HOSTS = {
    "nykaa.com",
    "www.nykaa.com",
    "myntra.com",
    "www.myntra.com",
    "tira.com",
    "www.tira.com",
    "mamaearth.in",
    "www.mamaearth.in",
}


@dataclasses.dataclass(frozen=True, slots=True)
class Address:
    name: str
    line1: str
    city: str
    state: str
    postal_code: str
    phone: str
    line2: str = ""
    country: str = "IN"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Address":
        required = ("name", "line1", "city", "state", "postal_code", "phone")
        missing = [key for key in required if not str(value.get(key, "")).strip()]
        if missing:
            raise ConfigurationError(f"Address missing fields: {', '.join(missing)}")
        return cls(**{field.name: value.get(field.name, field.default) for field in dataclasses.fields(cls)})


@dataclasses.dataclass(frozen=True, slots=True)
class Account:
    name: str
    phone: str
    address: Address
    test_account: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Account":
        if value.get("test_account") is not True:
            raise ConfigurationError(
                f"Account {value.get('name', '<unnamed>')!r} must set test_account=true"
            )
        return cls(
            name=str(value["name"]),
            phone=str(value["phone"]),
            address=Address.from_dict(value["address"]),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class ProductRule:
    id: str
    path: str
    target_price: float
    target_discount: float = 50.0
    quantity: int = 1
    preferred_size: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProductRule":
        quantity = int(value.get("quantity", 1))
        if not 1 <= quantity <= 10:
            raise ConfigurationError("Product quantity must be between 1 and 10")
        return cls(
            id=str(value["id"]),
            path=str(value.get("path") or f"/api/test/products/{value['id']}"),
            target_price=float(value["target_price"]),
            target_discount=float(value.get("target_discount", 50)),
            quantity=quantity,
            preferred_size=value.get("preferred_size"),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class Config:
    base_url: str
    allowed_hosts: frozenset[str]
    dry_run: bool
    accounts: tuple[Account, ...]
    products: tuple[ProductRule, ...]
    coupons: tuple[str, ...]
    telegram: TelegramConfig
    monitor_interval_seconds: float = 10.0
    max_concurrency: int = 20
    requests_per_second: float = 25.0
    max_orders_per_account: int = 5
    request_timeout_seconds: float = 20.0
    database_path: str = "order_log.db"
    session_dir: str = "sessions"
    log_dir: str = "logs"

    @property
    def target_host(self) -> str:
        return (urlparse(self.base_url).hostname or "").lower()

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        with Path(path).open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        telegram = raw.get("telegram", {})
        config = cls(
            base_url=str(raw["base_url"]).rstrip("/") + "/",
            allowed_hosts=frozenset(
                str(host).lower()
                for host in raw.get("allowed_hosts", ["127.0.0.1", "localhost"])
            ),
            dry_run=bool(raw.get("dry_run", True)),
            accounts=tuple(Account.from_dict(item) for item in raw.get("accounts", [])),
            products=tuple(ProductRule.from_dict(item) for item in raw.get("products", [])),
            coupons=tuple(
                str(code).strip().upper()
                for code in raw.get("coupons", [])
                if str(code).strip()
            ),
            telegram=TelegramConfig(
                bot_token=str(telegram.get("bot_token", "")),
                chat_id=str(telegram.get("chat_id", "")),
            ),
            monitor_interval_seconds=max(2.0, float(raw.get("monitor_interval_seconds", 10))),
            max_concurrency=max(1, min(int(raw.get("max_concurrency", 20)), 100)),
            requests_per_second=max(0.5, min(float(raw.get("requests_per_second", 25)), 200)),
            max_orders_per_account=max(1, min(int(raw.get("max_orders_per_account", 5)), 50)),
            request_timeout_seconds=max(5.0, float(raw.get("request_timeout_seconds", 20))),
            database_path=str(raw.get("database_path", "order_log.db")),
            session_dir=str(raw.get("session_dir", "sessions")),
            log_dir=str(raw.get("log_dir", "logs")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ConfigurationError("base_url must use http or https")
        if not self.target_host:
            raise ConfigurationError("base_url must contain a hostname")
        if self.target_host not in self.allowed_hosts:
            raise ConfigurationError(
                f"Target host {self.target_host!r} is not present in allowed_hosts"
            )
        if self.target_host in BLOCKED_LIVE_HOSTS:
            raise ConfigurationError("Live third-party commerce hosts are intentionally blocked")
        if not self.accounts:
            raise ConfigurationError("At least one test account is required")
        if not self.products:
            raise ConfigurationError("At least one product rule is required")
