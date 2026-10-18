import wave
import numpy as np
from synclab.models import Clip, SAMPLE_RATE
from synclab.preview import render_preview


def test_comparison_uses_device_supported_rate_without_changing_timing(tmp_path):
    t=np.arange(SAMPLE_RATE*2)/SAMPLE_RATE
    audio=np.sin(2*np.pi*440*t).astype(np.float32)*.5
    ref=Clip(tmp_path/'reference.wav',2,audio,offset=0)
    other=Clip(tmp_path/'camera.wav',2,audio,offset=.5)
    path=render_preview(ref,other,tmp_path/'compare.wav',duration=2)
    with wave.open(str(path),'rb') as wav:
        assert wav.getframerate()==48000
        assert wav.getnchannels()==2
        assert wav.getnframes()==96000
        stereo=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').reshape(-1,2)
    assert np.max(np.abs(stereo[:23800,1]))==0
    onset=np.flatnonzero(np.abs(stereo[:,1])>5000)[0]
    assert abs(onset-24000)<120
    assert np.max(np.abs(stereo[25000:,1]))>10000
    assert np.max(np.abs(stereo[1000:2000,0]))>10000
