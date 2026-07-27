from types import SimpleNamespace

from app.services.index_publication_service import IndexPublicationService


def test_publication_requires_every_admitted_index_before_atomic_publish() -> None:
    units = [
        SimpleNamespace(id=1, index_admission_status="text_indexed"),
        SimpleNamespace(id=2, index_admission_status="visual_indexed"),
    ]

    result = IndexPublicationService().assess(units, completed={"text": {1}, "visual": {1}})

    assert result.publishable is False
    assert result.missing == {"visual": [2]}


def test_partial_coverage_can_publish_only_when_key_units_are_complete() -> None:
    units = [
        SimpleNamespace(id=1, index_admission_status="text_indexed"),
        SimpleNamespace(id=2, index_admission_status="waiting_correction"),
    ]

    result = IndexPublicationService().assess(
        units,
        completed={"text": {1}},
        key_unit_ids={1},
        minimum_coverage=0.5,
    )

    assert result.publishable is True
    assert result.partial_coverage is True
    assert result.coverage == 0.5
