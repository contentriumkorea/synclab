from fractions import Fraction
import json
import wave
import numpy as np
import pytest
from conftest import sound, clip
from synclab.project import save_project, load_project
from synclab.preview import render_preview


def test_project_roundtrip_and_missing_source_excludes_clip(tmp_path):
    a = clip(sound(3), "카메라.wav")
    a.path = tmp_path/a.path
    a.path.touch()
    a.offset, a.included, a.status = -.125, True, "수동 보정"
    path = tmp_path/"project.synclab"
    save_project([a], a.id, Fraction(30000,1001), path)
    restored, ref, fps = load_project(path)
    assert restored[0].offset == -.125
    assert restored[0].included
    assert restored[0].status == "수동 보정"
    assert len(restored[0].audio) == 0
    assert ref == a.id and fps == Fraction(30000,1001)
    a.path.unlink()
    restored, _, _ = load_project(path)
    assert not restored[0].included
    assert restored[0].status == "파일 없음"


def test_malformed_project_fails_cleanly(tmp_path):
    path = tmp_path/"bad.synclab"
    for payload in [{"version":99}, {"version":1, "clips":[{"offset":float("nan")}]}]:
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            load_project(path)


def test_preview_aligns_reference_left_selected_right(tmp_path):
    data = sound(10)
    a = clip(data[:8*4000], "a")
    b = clip(data[2*4000:], "b")
    a.offset, b.offset = 0., 2.
    out = tmp_path/"preview.wav"
    render_preview(a,b,out,start=3.,duration=3.)
    with wave.open(str(out),"rb") as f:
        assert f.getnchannels() == 2
        decoded = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").reshape(-1,2)
    assert len(decoded) == 12000
    assert np.max(np.abs(decoded[:,0].astype(float)-decoded[:,1])) <= 1
