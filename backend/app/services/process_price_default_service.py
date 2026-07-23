"""工艺配置默认价格补齐服务。"""

from __future__ import annotations

from decimal import Decimal
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.process_config import ProcessRegionPrice
from app.repositories.process_price_default_repository import ProcessPriceDefaultRepository

logger = logging.getLogger(__name__)

PRICE_DEFAULTS_PATH = Path(__file__).resolve().parents[1] / "core" / "process_price_defaults.json"


class ProcessPriceDefaultService:
    """用可审计价格基准补齐空价格，人工维护的非零价格始终优先。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ProcessPriceDefaultRepository(db)

    def sync_zero_prices(self) -> int:
        config = self._load_config()
        source = config["source"]
        regions = source.get("regions") or [source]
        libraries = self.repository.list_libraries()
        libraries_by_id = {(owner_type, library.id): library for (owner_type, _), library in libraries.items()}
        prices = self.repository.list_active_prices()
        updated_count = 0

        # 基础库保存的是消耗系数单位，区域价格必须使用实际计价单位。
        for price in prices.values():
            if price.unit_price != 0:
                continue
            library = libraries_by_id.get((price.owner_type, price.owner_id))
            if library is None:
                continue
            normalized_unit = self._coefficient_output_unit(library.unit)
            if price.unit != normalized_unit:
                price.unit = normalized_unit
                updated_count += 1

        for preset in config["prices"]:
            owner_type = str(preset["owner_type"])
            owner_code = str(preset["owner_code"])
            library = libraries.get((owner_type, owner_code))
            if library is None:
                logger.warning("默认价格未匹配基础库 owner_type=%s owner_code=%s", owner_type, owner_code)
                continue
            for region in regions:
                region_code = str(region["region_code"])
                key = (owner_type, library.id, region_code)
                price = prices.get(key)
                if price is not None and price.unit_price != 0:
                    continue
                if price is None:
                    price = ProcessRegionPrice(
                        owner_type=owner_type,
                        owner_id=library.id,
                        region_code=region_code,
                        region_name=str(region["region_name"]),
                        currency=str(region["currency"]),
                        unit_price=Decimal("0"),
                        unit=str(preset["unit"]),
                        status="enabled",
                        is_deleted=False,
                    )
                    self.repository.add_price(price)
                    prices[key] = price
                price.region_name = str(region["region_name"])
                price.currency = str(region["currency"])
                price.unit_price = Decimal(str(preset["unit_price"])) * Decimal(str(region.get("multiplier") or "1"))
                price.unit = str(preset["unit"])
                price.status = "enabled"
                updated_count += 1

        if updated_count:
            self.db.flush()
            logger.info(
                "工艺配置默认价格补齐完成 region_code=%s currency=%s updated_count=%s source=%s",
                ",".join(str(region["region_code"]) for region in regions),
                source["currency"],
                updated_count,
                source["name"],
            )
        return updated_count

    @staticmethod
    def _load_config() -> dict[str, Any]:
        if not PRICE_DEFAULTS_PATH.exists():
            raise FileNotFoundError(f"工艺配置默认价格文件不存在: {PRICE_DEFAULTS_PATH}")
        data = json.loads(PRICE_DEFAULTS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data.get("source"), dict) or not isinstance(data.get("prices"), list):
            raise ValueError("工艺配置默认价格文件结构不正确")
        return data

    @staticmethod
    def _coefficient_output_unit(unit: str) -> str:
        normalized = unit.strip()
        compact = normalized.lower().replace(" ", "")
        for suffix in ("/t-bm", "/tbm", "/t_bm", "/吨bm", "/吨黑粉"):
            if compact.endswith(suffix):
                return normalized[: len(normalized) - len(suffix)].strip()
        return "t" if compact in {"t-bm", "t/bm", "ton", "tons"} else normalized
