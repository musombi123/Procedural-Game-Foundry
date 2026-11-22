from __future__ import annotations

import pytest

from core.nexora_workspace.desktop_factory import validate_level_manifest


def test_level_manifest_normalizes_order_and_shared_assets() -> None:
    result = validate_level_manifest({"levels": [
        {"id": "chapter-two", "title": "The Crossing", "difficulty": "hard",
         "state": "testing", "shared_asset_ids": ["hero-model", "forest", "hero-model"]},
        {"id": "chapter-three", "title": "The Signal", "difficulty": "normal"},
    ]})
    assert result["level_count"] == 2
    assert [level["order"] for level in result["levels"]] == [1, 2]
    assert result["levels"][0]["shared_asset_ids"] == ["hero-model", "forest"]
    assert result["levels"][1]["state"] == "draft"


@pytest.mark.parametrize("payload", [
    {},
    {"levels": []},
    {"levels": [{"id": "bad id", "title": "Invalid"}]},
    {"levels": [{"id": "one", "title": "A"}, {"id": "one", "title": "B"}]},
    {"levels": [{"id": "one", "title": "A", "difficulty": "impossible"}]},
    {"levels": [{"id": "one", "title": "A", "state": "published"}]},
    {"levels": [{"id": "one", "title": "A", "shared_asset_ids": ["../secret"]}]},
])
def test_level_manifest_rejects_invalid_or_unsafe_data(payload: dict) -> None:
    with pytest.raises(ValueError):
        validate_level_manifest(payload)


def test_level_manifest_caps_project_at_100_levels() -> None:
    levels = [{"id": f"level-{index}", "title": f"Level {index}"} for index in range(101)]
    with pytest.raises(ValueError):
        validate_level_manifest({"levels": levels})
