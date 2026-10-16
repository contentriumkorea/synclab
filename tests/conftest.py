from pathlib import Path
import numpy as np
from scipy import signal
from synclab.models import Clip, SAMPLE_RATE


def sound(seconds=40, seed=83):
    rng = np.random.default_rng(seed)
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    out = np.zeros(n)
    for lo, hi in [(100, 300), (350, 700), (750, 1250), (1300, 1850)]:
        noise = signal.sosfilt(signal.butter(3, [lo, hi], btype="bandpass", fs=SAMPLE_RATE, output="sos"), rng.normal(size=n))
        env = np.interp(t, np.arange(0, seconds + .25, .25), rng.uniform(.01, 1, int(seconds * 4) + 1))
        out += noise * env
    return (out / max(np.max(np.abs(out)), 1) * .7).astype(np.float32)


def clip(data, name):
    return Clip(Path(name), len(data) / SAMPLE_RATE, data.astype(np.float32), id=name, channels=1)
