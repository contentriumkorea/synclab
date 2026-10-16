from pathlib import Path
import wave
import numpy as np
import pytest
from conftest import sound
from synclab.media import decode_media
from synclab.models import SAMPLE_RATE, Cancelled


def write_wav(path, audio, rate=SAMPLE_RATE):
    audio = np.asarray(audio)
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.clip(audio, -1, 1)*32767).astype("<i2").tobytes())


def test_decode_korean_path_preserves_loud_channel_without_phase_cancellation(tmp_path):
    source = sound(8)
    path = tmp_path / "카메라 녹음.wav"
    write_wav(path, np.column_stack([source*.2, -source]))
    before = path.read_bytes()
    result = decode_media(path)
    assert result.channels == 2
    assert result.channel_used == 1
    assert result.duration == pytest.approx(8, abs=.01)
    assert np.corrcoef(result.audio, -source)[0, 1] > .999
    assert path.read_bytes() == before


def test_resampling_and_invalid_file(tmp_path):
    source = np.sin(np.arange(48000*3) * 2*np.pi*500/48000)*.5
    path = tmp_path / "48k.wav"
    write_wav(path, source, 48000)
    result = decode_media(path)
    assert len(result.audio) == pytest.approx(12000, abs=2)
    bad = tmp_path / "bad.mp4"
    bad.write_text("not media")
    with pytest.raises(ValueError):
        decode_media(bad)
    with pytest.raises(Cancelled):
        decode_media(path, cancelled=lambda: True)


def test_decode_is_disk_backed_reused_and_invalidated(tmp_path, monkeypatch):
    import synclab.media as media
    monkeypatch.setenv('SYNCLAB_CACHE_DIR', str(tmp_path/'cache'))
    path=tmp_path/'source.wav'
    write_wav(path,sound(4))
    first=decode_media(path)
    assert isinstance(first.audio,np.memmap)
    assert not first.audio.flags.writeable
    real_open=media.av.open
    def no_decode(*args,**kwargs):
        raise AssertionError('same source decoded twice')
    monkeypatch.setattr(media.av,'open',no_decode)
    again=decode_media(path)
    assert np.array_equal(first.audio,again.audio)
    monkeypatch.setattr(media.av,'open',real_open)
    write_wav(path,sound(5,78))
    changed=decode_media(path)
    assert len(changed.audio)==5*SAMPLE_RATE
    assert changed.fingerprint!=first.fingerprint


def test_decode_reports_in_file_progress_and_cancel_does_not_publish_cache(tmp_path,monkeypatch):
    monkeypatch.setenv('SYNCLAB_CACHE_DIR',str(tmp_path/'cache'))
    path=tmp_path/'progress.wav'
    write_wav(path,sound(8))
    seen=[]
    with pytest.raises(Cancelled):
        decode_media(path,cancelled=lambda:bool(seen),progress=lambda value:seen.append(value))
    assert not list((tmp_path/'cache').glob('*.json'))
    seen=[]
    result=decode_media(path,progress=seen.append)
    assert len(result.audio)==8*SAMPLE_RATE
    assert len(seen)>2 and seen==sorted(seen) and seen[-1]==1
