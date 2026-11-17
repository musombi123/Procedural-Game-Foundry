# Procedural Audio Foundry

Audio generation is local, deterministic and model-free. The Python standard library synthesizes mono PCM WAV sound effects and original arpeggiated background music from creator-authored descriptors. It uses oscillators, envelopes, deterministic seeded noise and simple chord progressions; it does not use downloaded samples, models, paid APIs or third-party sound assets.

Supported effects: tone, impact, sweep, pulse, noise and alarm. Music moods: adventure, calm, tense and triumphant. Each output is recorded in a JSON manifest with duration, sample rate, cue trigger, file path and byte count. The creator listens to every asset and approves the AUDIO stage before gameplay becomes READY.

Important boundary: cue triggers are authored metadata. This stage does not yet connect audio to a runtime event bus, spatial audio, adaptive mixing or game-state transitions. Audio is currently 22,050 Hz, mono, 16-bit PCM WAV.
