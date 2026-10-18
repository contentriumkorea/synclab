"""Read source media without modifying it; decoding uses the bundled FFmpeg libraries."""
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import os
import tempfile

import av
import numpy as np

from .engine import check_cancel
from .models import Clip, SAMPLE_RATE
from .storage import atomic_write
from .platforms import audio_cache

EXTENSIONS = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".wav",
              ".mp3", ".flac", ".m4a", ".aac", ".aif", ".aiff", ".ogg", ".webm"}
MAX_SECONDS = 6 * 3600
BLOCK_SAMPLES = 262144


def audio_peak(audio):
    """Scan bounded pages without allocating a full-size abs() array."""
    return max((float(np.max(np.abs(audio[i:i+BLOCK_SAMPLES]),initial=0))
                for i in range(0,len(audio),BLOCK_SAMPLES)),default=0.)


def _cache_paths(path,fingerprint):
    directory=audio_cache()
    directory.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(json.dumps([str(path),fingerprint,SAMPLE_RATE,1],sort_keys=True).encode()).hexdigest()
    return directory/(key+'.f32'),directory/(key+'.json')


def _cached(path,fingerprint,data_path,meta_path):
    try:
        m=json.loads(meta_path.read_text(encoding='utf-8'))
        count=m['samples']
        if not isinstance(count,int) or not 0<count<=MAX_SECONDS*SAMPLE_RATE or data_path.stat().st_size!=count*4:
            return None
        clip=Clip(path,m['duration'],fps=Fraction(m['fps']),width=m['width'],height=m['height'],
                  channels=m['channels'],source_sample_rate=m['source_sample_rate'],
                  audio_start=m['audio_start'],channel_used=m['channel_used'],status=m['status'],
                  warnings=m['warnings'],fingerprint=fingerprint)
        clip.audio=np.memmap(data_path,dtype=np.float32,mode='r',shape=(count,))
        return clip
    except (OSError,ValueError,KeyError,TypeError,ZeroDivisionError):
        return None


def _store_audio(clip,spool,total,channels,data_path,meta_path,cancelled):
    """Extract a mono channel in chunks and publish only a complete cache entry."""
    descriptor,name=tempfile.mkstemp(prefix='.decode-',suffix='.tmp',dir=data_path.parent)
    try:
        mm=np.memmap(spool,dtype=np.float32,mode='r',shape=(total,channels))
        try:
            with os.fdopen(descriptor,'wb') as out:
                for start in range(0,total,BLOCK_SAMPLES):
                    check_cancel(cancelled)
                    out.write(np.ascontiguousarray(mm[start:start+BLOCK_SAMPLES,clip.channel_used]).tobytes())
        finally:
            del mm
        check_cancel(cancelled)
        if file_fingerprint(clip.path)!=clip.fingerprint:
            raise ValueError('읽는 동안 원본 파일이 변경되었습니다. 다시 열어 주세요.')
        os.replace(name,data_path)
        clip.audio=np.memmap(data_path,dtype=np.float32,mode='r',shape=(total,))
        if audio_peak(clip.audio)<1e-5:clip.status='무음'
        meta={key:getattr(clip,key) for key in ['duration','width','height','channels','source_sample_rate',
              'audio_start','channel_used','status','warnings']}
        meta.update(samples=total,fps=str(clip.fps))
        atomic_write(meta_path,json.dumps(meta,ensure_ascii=False).encode('utf-8'))
    finally:
        if os.path.exists(name):os.unlink(name)


def file_fingerprint(path):
    stat = Path(path).stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def decode_media(path, cancelled=lambda: False, progress=lambda value:None):
    check_cancel(cancelled)
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"파일을 찾을 수 없습니다: {path.name}")
    fingerprint=file_fingerprint(path)
    data_path,meta_path=_cache_paths(path,fingerprint)
    cached=_cached(path,fingerprint,data_path,meta_path)
    if cached is not None:
        progress(1.)
        return cached
    progress(0.)
    try:
        with av.open(str(path)) as container:
            videos = [s for s in container.streams.video if not (s.disposition & 1024)]
            video = videos[0] if videos else None
            audio = container.streams.audio[0] if container.streams.audio else None
            main = video or audio
            origin = float(main.start_time * main.time_base) if main and main.start_time is not None else 0.
            duration = float(main.duration * main.time_base) if main and main.duration is not None else float(container.duration or 0)/av.time_base
            if duration > MAX_SECONDS:
                raise ValueError("한 파일은 최대 6시간까지 분석할 수 있습니다.")
            fps = Fraction(video.average_rate or 25) if video else Fraction(25)
            result = Clip(path, duration, fps=fps, width=video.width if video else 0,
                          height=video.height if video else 0, channels=audio.channels if audio else 0,
                          source_sample_rate=audio.rate if audio else 48000,
                          fingerprint=fingerprint)
            if video and video.base_rate and video.average_rate and abs(float(video.base_rate)-float(video.average_rate)) > .05:
                result.warnings.append("가변 프레임레이트 가능성 — XML 가져오기 후 프레임 위치를 확인하세요.")
            if not audio:
                result.status = "오디오 없음"
                result.warnings.append("자동 싱크에 사용할 오디오 스트림이 없습니다.")
                progress(1.)
                return result
            if len(container.streams.audio) > 1:
                result.warnings.append("첫 번째 오디오 스트림을 분석했습니다.")
            channels = audio.channels
            if channels < 1 or channels > 32:
                raise ValueError("오디오 채널 수를 지원하지 않습니다.")
            resampler = av.AudioResampler(format="fltp", layout=audio.layout, rate=SAMPLE_RATE)
            total, first_time, energies, gaps = 0, None, np.zeros(channels), False
            last_progress=0.
            # Both the temporary multichannel stream and retained mono audio live on disk.
            with tempfile.TemporaryFile() as spool:
                def consume(frame):
                    nonlocal total, first_time, gaps,last_progress
                    data = frame.to_ndarray().astype(np.float32, copy=False)
                    stamp = float(frame.pts*frame.time_base) if frame.pts is not None else None
                    if first_time is None:
                        first_time = stamp if stamp is not None else (float(audio.start_time*audio.time_base) if audio.start_time is not None else origin)
                        result.audio_start = first_time-origin
                    wanted = round((stamp-first_time)*SAMPLE_RATE) if stamp is not None else total
                    if wanted > total+2:
                        gaps = True
                        spool.seek(wanted*channels*4)
                        total = wanted
                    elif wanted < total-2:
                        data = data[:, min(total-wanted, data.shape[1]):]
                    if total+data.shape[1] > MAX_SECONDS*SAMPLE_RATE:
                        raise ValueError("한 파일은 최대 6시간까지 분석할 수 있습니다.")
                    energies[:] += np.sum(data.astype(np.float64)**2, axis=1)
                    spool.write(np.ascontiguousarray(data.T).tobytes())
                    total += data.shape[1]
                    fraction=min(.95,total/max(1,duration*SAMPLE_RATE)*.95)
                    if fraction-last_progress>=.005:
                        progress(fraction)
                        last_progress=fraction
                for frame in container.decode(audio):
                    check_cancel(cancelled)
                    for output in resampler.resample(frame):
                        consume(output)
                for output in resampler.resample(None):
                    consume(output)
                if total:
                    spool.flush()
                    result.channel_used = int(np.argmax(energies))
                if not video:
                    result.duration = max(duration, total/SAMPLE_RATE)
                if gaps:
                    result.warnings.append("오디오 타임스탬프 간격을 무음으로 유지했습니다.")
                if total:
                    _store_audio(result,spool,total,channels,data_path,meta_path,cancelled)
                else:
                    result.status = "무음"
                progress(1.)
                return result
    except av.FFmpegError as exc:
        raise ValueError(f"읽을 수 없는 미디어: {path.name} ({exc.strerror})") from exc
