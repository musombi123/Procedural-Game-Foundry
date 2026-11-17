import pytest
from core.movie_pipeline.story import StoryBrief
from core.movie_pipeline.procedural_world import build_world_spec

def test_creator_story_keeps_user_authored_instructions_and_portrait_identity():
    brief=StoryBrief(mode="story", title="The Crossing", premise="A pilot crosses a flooded continent.",
                     player_role="Pilot", instructions="Never use firearms; rescue stranded families.")
    manifest=brief.as_manifest()
    assert manifest["source"]=="creator"
    assert manifest["player"]["identity_source"]=="uploaded_portrait"
    assert manifest["player"]["is_player_avatar"] is True
    assert manifest["instructions"]=="Never use firearms; rescue stranded families."
    assert len(manifest["missions"])==5

def test_world_spec_is_deterministic_and_contains_real_3d_geometry_instructions():
    story={"title":"Coastal Run","setting":"Coastal city and ancient harbour","world_scale":"medium"}
    first=build_world_spec(story,seed=42)
    second=build_world_spec(story,seed=42)
    assert first==second
    assert first["terrain"]["type"]=="heightfield_mesh"
    assert first["dimensions"]==[96,48,96]
    assert len(first["landmarks"])==4
    assert len(first["props"])>=24
    assert first["navigation"]["generate_collision"] is True
    assert first["requires_creator_review"] is True

def test_story_requires_nonempty_title():
    with pytest.raises(ValueError):
        StoryBrief(title="   ")
