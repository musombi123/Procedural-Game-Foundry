from generators.terrain.heightfield import generate_heightfield
def test_deterministic(): assert generate_heightfield(42,32,32,12)==generate_heightfield(42,32,32,12)
def test_dimensions():
    grid=generate_heightfield(7,32,48,10)
    assert len(grid)==11 and all(len(row)==11 for row in grid)
def test_seed_changes_output(): assert generate_heightfield(1,16,16,8)!=generate_heightfield(2,16,16,8)


def test_terrain_sculpting_is_deterministic_and_local():
    from generators.terrain.heightfield import apply_terrain_edits
    base = generate_heightfield(42, 32, 32, 12)
    stroke = {"id": "raise-1", "operation": "raise", "x": 0, "z": 0, "radius": 8, "strength": 3}
    sculpted = apply_terrain_edits(base, 32, 32, [stroke])
    assert sculpted == apply_terrain_edits(base, 32, 32, [stroke])
    assert sculpted[6][6] > base[6][6]
    assert sculpted[0][0] == base[0][0]


def test_lower_and_smooth_terrain_sculpting():
    from generators.terrain.heightfield import apply_terrain_edits
    base = generate_heightfield(7, 48, 48, 16)
    lowered = apply_terrain_edits(base, 48, 48, [{"operation": "lower", "x": 0, "z": 0, "radius": 10, "strength": 2}])
    assert lowered[8][8] < base[8][8]
    smoothed = apply_terrain_edits(base, 48, 48, [{"operation": "smooth", "x": 0, "z": 0, "radius": 10, "strength": 12}])
    assert smoothed != base
