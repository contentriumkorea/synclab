from fractions import Fraction

import numpy as np
import pytest
from scipy import signal

from conftest import clip, sound
from synclab.engine import features
from synclab.export import export_xml
from synclab.media import file_fingerprint


def test_changed_source_blocks_export(tmp_path):
    c = clip(sound(3), 'a.wav')
    c.path = tmp_path/c.path
    c.path.write_bytes(b'original')
    c.fingerprint = file_fingerprint(c.path)
    c.included, c.offset = True, 0
    c.path.write_bytes(b'changed data')
    with pytest.raises(ValueError, match='변경'):
        export_xml([c], tmp_path/'out.xml', Fraction(25))


def test_features_chunk_boundaries_match_full_transform(monkeypatch):
    import synclab.engine as engine
    monkeypatch.setattr(engine, 'FEATURE_CHUNK_FRAMES', 211, raising=False)
    data = sound(20)[:int(19.37*4000)]
    f, _, z = signal.stft(data, fs=4000, nperseg=256, noverlap=192, boundary=None, padded=False)
    power = np.abs(z)**2
    bands = [(80,200), (200,400), (400,650), (650,1000), (1000,1450), (1450,1950)]
    energy = np.array([power[(f>=lo)&(f<hi)].mean(axis=0) for lo,hi in bands])
    expected = np.log(energy+np.maximum(energy.mean(axis=1,keepdims=True)*.01, 1e-12))
    expected -= expected.mean(axis=1,keepdims=True)
    expected /= np.maximum(expected.std(axis=1,keepdims=True),.1)
    calls = []
    real = engine.signal.stft
    def bounded(x, *args, **kwargs):
        calls.append(len(x))
        return real(x, *args, **kwargs)
    monkeypatch.setattr(engine.signal, 'stft', bounded)
    actual = features(clip(data, 'long'))
    assert max(calls) <= 211*64+256
    assert np.allclose(actual, expected, atol=2e-5)
