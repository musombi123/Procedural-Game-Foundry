"""Deterministic procedural audio synthesis using only the Python standard library."""
from __future__ import annotations
import math, random, struct, wave
from pathlib import Path

SAMPLE_RATE=22050
NOTE={"C":261.63,"D":293.66,"E":329.63,"F":349.23,"G":392.00,"A":440.00,"B":493.88}

def _envelope(t,duration,attack=.012,release=.12):
    return min(1.0,t/max(attack,1e-5),max(0.0,(duration-t)/max(release,1e-5)))

def _tone(t,freq,phase=0.0):
    return math.sin(2*math.pi*freq*t+phase)

def render_effect(kind:str, frequency:float, duration:float, seed:int)->list[float]:
    count=int(SAMPLE_RATE*duration); rng=random.Random(seed); samples=[]
    for i in range(count):
        t=i/SAMPLE_RATE; progress=t/duration; env=_envelope(t,duration,.004,min(.25,duration*.45))
        if kind=="impact":
            freq=frequency*(1-progress*.72); value=.72*_tone(t,freq)+.24*rng.uniform(-1,1)
            env*=math.exp(-5*progress)
        elif kind=="sweep":
            freq=frequency*(.35+2.8*progress); value=_tone(t,freq)
        elif kind=="pulse":
            value=1.0 if math.sin(2*math.pi*frequency*t)>0 else -1.0
        elif kind=="noise":
            value=rng.uniform(-1,1)
        elif kind=="alarm":
            gate=1.0 if int(t*4)%2==0 else .18; value=gate*_tone(t,frequency)
        else:
            value=.72*_tone(t,frequency)+.18*_tone(t,frequency*2.01)
        samples.append(max(-1,min(1,value*env*.62)))
    return samples

def render_music(duration:float, seed:int, mood:str)->list[float]:
    # Original synthesized arpeggio, no samples or existing composition.
    progressions={"adventure":[[0,4,7],[5,9,12],[2,5,9],[7,11,14]],
                  "calm":[[0,3,7],[5,8,12],[2,5,9],[0,3,7]],
                  "tense":[[0,3,6],[1,4,7],[5,8,11],[0,3,6]],
                  "triumphant":[[0,4,7],[7,11,14],[9,12,16],[5,9,12]]}
    chords=progressions[mood]; samples=[]; beat=.5; base=NOTE["C"]*.5; rng=random.Random(seed)
    total=int(SAMPLE_RATE*duration)
    for i in range(total):
        t=i/SAMPLE_RATE; beat_index=int(t/beat); chord=chords[(beat_index//4)%len(chords)]
        note=chord[beat_index%len(chord)]; freq=base*(2**(note/12))
        local=t%beat; env=math.exp(-4.8*local)*min(1,local/.012)
        fundamental=_tone(t,freq); overtone=.25*_tone(t,freq*2.0)+.08*_tone(t,freq*3.0)
        pad=.10*_tone(t,base*(2**(chord[0]/12))*.5)
        samples.append(max(-1,min(1,(fundamental*.42+overtone+pad)*env*.48)))
    return samples

def write_wav(path:Path,samples:list[float]):
    path.parent.mkdir(parents=True,exist_ok=True)
    peak=max((abs(x) for x in samples),default=1.0) or 1.0
    gain=min(1.0,.92/peak)
    with wave.open(str(path),"wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(SAMPLE_RATE)
        output.writeframes(b"".join(struct.pack("<h",int(max(-1,min(1,x*gain))*32767)) for x in samples))
    return path.stat().st_size

def generate_audio(output_dir:Path, cues:list[dict], music:dict|None):
    output_dir.mkdir(parents=True,exist_ok=True); manifest={"schema_version":"1.0","generator":"PGF Procedural Audio Foundry v1","sample_rate":SAMPLE_RATE,"format":"WAV PCM 16-bit mono","effects":[],"music":None,"requires_creator_review":True}
    for index,cue in enumerate(cues):
        path=output_dir/(cue["id"]+".wav"); size=write_wav(path,render_effect(cue["kind"],cue["frequency"],cue["duration"],cue["seed"]))
        manifest["effects"].append({"id":cue["id"],"label":cue["label"],"kind":cue["kind"],"file":str(path.name),"duration_seconds":cue["duration"],"sample_rate":SAMPLE_RATE,"bytes":size,"trigger":cue["trigger"]})
    if music:
        path=output_dir/"background-music.wav"; size=write_wav(path,render_music(music["duration"],music["seed"],music["mood"]))
        manifest["music"]={"file":path.name,"mood":music["mood"],"duration_seconds":music["duration"],"loop":music["loop"],"bytes":size}
    manifest_path=output_dir/"audio-manifest.json"
    import json
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return manifest
