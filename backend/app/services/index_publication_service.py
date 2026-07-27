"""文档版本索引发布完整性判定。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublicationAssessment:
    publishable: bool
    partial_coverage: bool
    coverage: float
    required: dict[str, list[int]]
    missing: dict[str, list[int]]


class IndexPublicationService:
    """以文档版本为原子单位核对必需索引，避免多通道分批生效。"""

    REQUIRED_BY_ADMISSION = {
        "text_indexed": ("text",),
        "visual_indexed": ("visual",),
        "metadata_only": ("metadata",),
    }

    def assess(
        self,
        units: list[Any],
        completed: dict[str, set[int]],
        *,
        key_unit_ids: set[int] | None = None,
        minimum_coverage: float = 1.0,
        required_by_unit: dict[int, tuple[str, ...]] | None = None,
    ) -> PublicationAssessment:
        required: dict[str, list[int]] = {}
        missing: dict[str, list[int]] = {}
        covered_units: set[int] = set()
        for unit in units:
            unit_id = int(unit.id)
            indexes = (required_by_unit or {}).get(
                unit_id,
                self.REQUIRED_BY_ADMISSION.get(str(unit.index_admission_status), ()),
            )
            unit_complete = bool(indexes)
            for index_name in indexes:
                required.setdefault(index_name, []).append(unit_id)
                if unit_id not in completed.get(index_name, set()):
                    missing.setdefault(index_name, []).append(unit_id)
                    unit_complete = False
            if unit_complete:
                covered_units.add(unit_id)
        coverage = round(len(covered_units) / len(units), 4) if units else 1.0
        key_complete = (key_unit_ids or set()).issubset(covered_units)
        publishable = coverage >= minimum_coverage and key_complete
        return PublicationAssessment(
            publishable=publishable,
            partial_coverage=publishable and coverage < 1.0,
            coverage=coverage,
            required=required,
            missing=missing,
        )
