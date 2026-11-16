"""Deterministic biome classification from elevation and seeded moisture fields."""
from generators.terrain.heightfield import value_noise

def classify_biome(seed: int,elevation: float,moisture: float) -> str:
    if elevation < -1.8: return "water"
    if elevation > 5.5: return "rocky-highlands"
    if moisture < -0.25: return "rocky-desert"
    if moisture > 0.35: return "alien-forest"
    return "open-plains"

def generate_biome_map(seed: int,heights: list[list[float]]) -> list[list[str]]:
    if not heights or not heights[0]: raise ValueError("Height field cannot be empty")
    rows=len(heights); cols=len(heights[0])
    if any(len(row)!=cols for row in heights): raise ValueError("Height field must be rectangular")
    return [[classify_biome(seed,float(heights[z][x]),value_noise(seed+991,x*.12,z*.12)) for x in range(cols)] for z in range(rows)]
