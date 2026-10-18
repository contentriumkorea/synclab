import io
import math
import wave
import numpy as np
from scipy.signal import resample_poly

from .models import SAMPLE_RATE
from .storage import atomic_write, protect_sources


def render_preview(reference, selected, path, start=0., duration=15.):
    path = protect_sources(path,[reference,selected])
    if not math.isfinite(start) or not math.isfinite(duration) or not 0 < duration <= 30:
        raise ValueError("비교 청취 길이는 0~30초 사이여야 합니다.")
    stereo = np.zeros((round(duration*SAMPLE_RATE),2),dtype=np.float32)
    for channel,c in enumerate([reference,selected]):
        if c.offset is None or not len(c.audio):
            raise ValueError("분석된 오디오와 시작 시간이 필요합니다. 먼저 자동 싱크를 실행하세요.")
        shift = round((c.offset+c.audio_start-start)*SAMPLE_RATE)
        dst, src = max(0,shift), max(0,-shift)
        count = min(len(stereo)-dst,len(c.audio)-src)
        if count > 0:
            data = c.audio[src:src+count]
            scale = .7/max(float(np.max(np.abs(data))),1e-6)
            stereo[dst:dst+count,channel] = data*scale
    if not np.any(stereo):
        raise ValueError("선택한 시간에 비교할 오디오가 없습니다.")
    # CoreAudio devices need a standard playback rate; analysis remains 4 kHz.
    output_rate=48000
    stereo=resample_poly(stereo,output_rate//SAMPLE_RATE,1,axis=0)
    buf = io.BytesIO()
    with wave.open(buf,"wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(output_rate)
        out.writeframes((np.clip(stereo,-1,1)*32767).astype("<i2").tobytes())
    atomic_write(path,buf.getvalue())
    return path
