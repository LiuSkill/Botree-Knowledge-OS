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
from app.models.process_config import ProcessConsumable, ProcessRegionPrice  # noqa: E402
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
        # 两次批量同步各 5 次读取，首次同步另有 1 次批量更新写入。
        assert query_count <= 11
        assert prices[sulfuric_acid.id].unit_price == Decimal("165")
        assert prices[sulfuric_acid.id].unit == "t"
        assert prices[sodium_hydroxide.id].unit_price == Decimal("999")
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
