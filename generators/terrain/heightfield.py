"""Deterministic value-noise terrain shared by the browser preview and export pipeline."""
import math

def _smooth(t):
    return t * t * (3 - 2 * t)

def _hash(seed, x, z):
    value = math.sin(x * 127.1 + z * 311.7 + seed * 0.017) * 43758.5453
    return (value - math.floor(value)) * 2 - 1

def value_noise(seed, x, z):
    x0, z0 = math.floor(x), math.floor(z)
    tx, tz = _smooth(x - x0), _smooth(z - z0)
    a, b = _hash(seed, x0, z0), _hash(seed, x0 + 1, z0)
    c, d = _hash(seed, x0, z0 + 1), _hash(seed, x0 + 1, z0 + 1)
    return a * (1 - tx) * (1 - tz) + b * tx * (1 - tz) + c * (1 - tx) * tz + d * tx * tz

def generate_heightfield(seed, width, depth, resolution, amplitude=9.0, frequency=0.055):
    if width < 1 or depth < 1 or resolution < 2:
        raise ValueError("Invalid terrain dimensions")
    rows = []
    for z in range(resolution + 1):
        row = []
        for x in range(resolution + 1):
            nx = (x / resolution - 0.5) * width
            nz = (z / resolution - 0.5) * depth
            base = value_noise(seed, nx * frequency, nz * frequency) * 0.72
            detail = value_noise(seed + 101, nx * frequency * 2.1, nz * frequency * 2.1) * 0.35
            ridge = (1 - abs(value_noise(seed + 211, nx * frequency * 0.55, nz * frequency * 0.55))) * 0.18
            row.append(round((base + detail + ridge) * amplitude, 4))
        rows.append(row)
    return rows
