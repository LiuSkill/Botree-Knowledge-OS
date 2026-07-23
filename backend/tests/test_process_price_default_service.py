"""工艺配置默认价格补齐服务测试。"""

from __future__ import annotations

from decimal import Decimal
import sys
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base  # noqa: E402
from app.models.process_config import ProcessAsset, ProcessConsumable, ProcessLaborCost, ProcessRegionPrice  # noqa: E402
from app.services.process_price_default_service import ProcessPriceDefaultService  # noqa: E402


def test_sync_zero_prices_fills_presets_without_overwriting_manual_price() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        sulfuric_acid = ProcessConsumable(code="C1", name="H2SO4", type="chemical", unit="t/t-BM", status="enabled")
        sodium_hydroxide = ProcessConsumable(code="C2", name="NaOH", type="chemical", unit="t/t-BM", status="enabled")
        db.add_all([sulfuric_acid, sodium_hydroxide])
        db.flush()
        db.add_all(
            [
                _price(sulfuric_acid.id, Decimal("0"), "t/t-BM"),
                _price(sodium_hydroxide.id, Decimal("999"), "t"),
            ]
        )
        db.flush()

        query_count = 0

        def count_query(*_: object) -> None:
            nonlocal query_count
            query_count += 1

        event.listen(engine, "before_cursor_execute", count_query)
        service = ProcessPriceDefaultService(db)
        updated_count = service.sync_zero_prices()
        second_sync_count = service.sync_zero_prices()
        event.remove(engine, "before_cursor_execute", count_query)
        prices = {
            item.owner_id: item
            for item in db.scalars(select(ProcessRegionPrice).where(ProcessRegionPrice.region_code == "europe")).all()
        }

        assert updated_count >= 1
        assert second_sync_count == 0
        # 两次同步分别批量读取 6 类基础库和价格表，首次同步另写入两个缺失区域并更新欧洲价格。
        assert query_count <= 19
        assert prices[sulfuric_acid.id].unit_price == Decimal("165")
        assert prices[sulfuric_acid.id].unit == "t"
        assert prices[sodium_hydroxide.id].unit_price == Decimal("999")
    engine.dispose()


def test_sync_zero_prices_supports_labor_and_asset_defaults() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        labor = ProcessLaborCost(code="L01", name="生产操作工", type="production", unit="person-year", status="enabled")
        asset = ProcessAsset(
            code="EQ001",
            name="酸浸反应釜",
            type="reactor",
            asset_class="equipment",
            unit="set",
            status="enabled",
        )
        db.add_all([labor, asset])
        db.flush()

        ProcessPriceDefaultService(db).sync_zero_prices()
        prices = {
            item.owner_type: item
            for item in db.scalars(select(ProcessRegionPrice).where(ProcessRegionPrice.region_code == "europe")).all()
        }

        assert prices["labor"].unit_price == Decimal("38000")
        assert prices["labor"].unit == "person-year"
        assert prices["asset"].unit_price == Decimal("280000")
        assert prices["asset"].unit == "set"
        asia_labor = db.scalar(
            select(ProcessRegionPrice).where(
                ProcessRegionPrice.owner_type == "labor",
                ProcessRegionPrice.owner_id == labor.id,
                ProcessRegionPrice.region_code == "asia",
            )
        )
        americas_asset = db.scalar(
            select(ProcessRegionPrice).where(
                ProcessRegionPrice.owner_type == "asset",
                ProcessRegionPrice.owner_id == asset.id,
                ProcessRegionPrice.region_code == "americas",
            )
        )
        assert asia_labor is not None and asia_labor.currency == "CNY"
        assert asia_labor.unit_price == Decimal("315400")
        assert americas_asset is not None and americas_asset.currency == "USD"
        assert americas_asset.unit_price == Decimal("324800")
    engine.dispose()


def _price(owner_id: int, unit_price: Decimal, unit: str) -> ProcessRegionPrice:
    return ProcessRegionPrice(
        owner_type="consumable",
        owner_id=owner_id,
        region_code="europe",
        region_name="欧洲",
        currency="EUR",
        unit_price=unit_price,
        unit=unit,
        status="enabled",
    )
