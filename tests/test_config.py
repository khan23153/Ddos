from __future__ import annotations

import json
from pathlib import Path

import pytest

from flash_sale_qa.config import Config
from flash_sale_qa.errors import ConfigurationError


def base_config() -> dict:
    return {
        "base_url": "http://127.0.0.1:8080",
        "allowed_hosts": ["127.0.0.1"],
        "dry_run": True,
        "accounts": [
            {
                "name": "qa-1",
                "phone": "9000000001",
                "test_account": True,
                "address": {
                    "name": "QA",
                    "line1": "Test",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "postal_code": "400001",
                    "phone": "9000000001",
                },
            }
        ],
        "products": [{"id": "sku-1", "target_price": 1000}],
    }


def write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    config = Config.load(write(tmp_path, base_config()))
    assert config.target_host == "127.0.0.1"
    assert config.accounts[0].test_account is True
    assert config.products[0].path.endswith("sku-1")


def test_rejects_non_test_account(tmp_path: Path) -> None:
    raw = base_config()
    raw["accounts"][0]["test_account"] = False
    with pytest.raises(ConfigurationError, match="test_account=true"):
        Config.load(write(tmp_path, raw))


def test_rejects_non_allowlisted_host(tmp_path: Path) -> None:
    raw = base_config()
    raw["base_url"] = "https://example.com"
    with pytest.raises(ConfigurationError, match="allowed_hosts"):
        Config.load(write(tmp_path, raw))


def test_rejects_known_live_store(tmp_path: Path) -> None:
    raw = base_config()
    raw["base_url"] = "https://www.myntra.com"
    raw["allowed_hosts"] = ["www.myntra.com"]
    with pytest.raises(ConfigurationError, match="intentionally blocked"):
        Config.load(write(tmp_path, raw))
