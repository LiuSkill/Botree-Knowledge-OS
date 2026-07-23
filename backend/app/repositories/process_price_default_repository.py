"""工艺配置默认价格批量查询仓储。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.process_config import (
    ProcessAsset,
    ProcessConsumable,
    ProcessLaborCost,
    ProcessMaterial,
    ProcessProduct,
    ProcessPublicService,
    ProcessRegionPrice,
)


class ProcessPriceDefaultRepository:
    """批量加载基础库和区域价格，避免按价格配置逐条查询。"""

    LIBRARY_MODELS = {
        "material": ProcessMaterial,
        "product": ProcessProduct,
        "consumable": ProcessConsumable,
        "public_service": ProcessPublicService,
        "labor": ProcessLaborCost,
        "asset": ProcessAsset,
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_libraries(self) -> dict[tuple[str, str], Any]:
        result: dict[tuple[str, str], Any] = {}
        for owner_type, model in self.LIBRARY_MODELS.items():
            items = self.db.scalars(select(model).where(model.is_deleted.is_(False))).all()
            result.update({(owner_type, item.code): item for item in items})
        return result

    def list_active_prices(self) -> dict[tuple[str, int, str], ProcessRegionPrice]:
        prices = self.db.scalars(
            select(ProcessRegionPrice).where(ProcessRegionPrice.is_deleted.is_(False))
        ).all()
        return {(price.owner_type, price.owner_id, price.region_code): price for price in prices}

    def add_price(self, price: ProcessRegionPrice) -> None:
        self.db.add(price)
