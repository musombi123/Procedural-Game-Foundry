from generators.terrain.heightfield import generate_heightfield
def test_deterministic(): assert generate_heightfield(42,32,32,12)==generate_heightfield(42,32,32,12)
def test_dimensions():
    grid=generate_heightfield(7,32,48,10)
    assert len(grid)==11 and all(len(row)==11 for row in grid)
def test_seed_changes_output(): assert generate_heightfield(1,16,16,8)!=generate_heightfield(2,16,16,8)
