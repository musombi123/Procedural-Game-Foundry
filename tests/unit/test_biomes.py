from generators.biomes.biome_map import generate_biome_map
def test_biome_map_shape_and_repeatability():
    heights=[[0.0,2.0],[-3.0,7.0]]
    a=generate_biome_map(10,heights)
    assert a==generate_biome_map(10,heights) and len(a)==2 and len(a[0])==2
