"""FCP 7 XML interchange; originals remain external and read-only."""
import csv
from fractions import Fraction
from io import StringIO
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .storage import atomic_write, protect_sources
from .media import file_fingerprint

FPS_CHOICES = {"23.976": Fraction(24000,1001), "24": Fraction(24), "25": Fraction(25),
               "29.97": Fraction(30000,1001), "30": Fraction(30), "50": Fraction(50),
               "59.94": Fraction(60000,1001), "60": Fraction(60)}


def media_uri(path):
    # Premiere on Windows treats an empty file-URI host as a UNC path.
    uri = Path(path).resolve().as_uri()
    return 'file://localhost/' + uri[len('file:///'):] if uri.startswith('file:///') else uri


def selected(clips):
    for c in clips:
        if not c.included and not c.excluded:
            invalid=(not c.path.is_file() or
                     bool(c.fingerprint and c.fingerprint != file_fingerprint(c.path)) or
                     c.status in {'파일 없음','원본 변경됨','읽기 실패','원본 재지정'})
            if invalid:
                raise ValueError(f'해결되지 않은 원본이 있습니다. 다시 지정/분석하거나 명시적으로 제외하세요: {c.name}')
    chosen = [c for c in clips if c.included]
    if not chosen:
        raise ValueError("내보낼 클립을 선택해 주세요.")
    for c in chosen:
        if c.offset is None or not math.isfinite(c.offset):
            raise ValueError(f"시작 시간이 정해지지 않았습니다: {c.name}")
        if not math.isfinite(c.duration) or c.duration <= 0:
            raise ValueError(f"길이를 확인할 수 없습니다: {c.name}")
        if not c.path.is_file():
            raise ValueError(f"원본 파일이 없습니다: {c.name}")
        if c.fingerprint and c.fingerprint != file_fingerprint(c.path):
            raise ValueError(f"분석 이후 원본 파일이 변경되었습니다. 다시 분석하세요: {c.name}")
    return chosen


def _tag(parent, name, value):
    el = ET.SubElement(parent, name)
    el.text = str(value)
    return el


def _rate(parent, fps):
    fps = Fraction(fps)
    nominal = round(float(fps))
    ntsc = fps == Fraction(nominal*1000,1001)
    if not ntsc and fps.denominator != 1:
        raise ValueError(f"XML에서 정확히 표현할 수 없는 프레임레이트: {fps}. 고정 FPS 변환 후 사용해 주세요.")
    rate = ET.SubElement(parent,"rate")
    _tag(rate,"timebase",nominal)
    _tag(rate,"ntsc","TRUE" if ntsc else "FALSE")


def frames(seconds, fps):
    return math.floor(Fraction(str(seconds))*fps + Fraction(1,2))


def _characteristics(parent, clip, fps):
    sc = ET.SubElement(parent,"samplecharacteristics")
    _rate(sc, fps)
    for key, value in [("width",clip.width),("height",clip.height),("anamorphic","FALSE"),
                       ("pixelaspectratio","square"),("fielddominance","none")]:
        _tag(sc,key,value)


def _file(parent, clip, number, source_fps):
    file = ET.SubElement(parent, "file", id=f"file-{number}")
    _tag(file,"name",clip.name)
    _tag(file,"pathurl",media_uri(clip.path))
    _rate(file,source_fps)
    _tag(file,"duration",frames(clip.duration,source_fps))
    media = ET.SubElement(file,"media")
    if clip.has_video:
        _characteristics(ET.SubElement(media,"video"),clip,source_fps)
    if clip.channels:
        audio = ET.SubElement(media,"audio")
        sc = ET.SubElement(audio,"samplecharacteristics")
        _tag(sc,"depth",16)
        _tag(sc,"samplerate",clip.source_sample_rate)
        _tag(audio,"channelcount",clip.channels)


def export_xml(clips, path, fps, title="SyncLab"):
    path = protect_sources(path, clips)
    chosen = selected(clips)
    fps = Fraction(fps)
    if fps not in FPS_CHOICES.values():
        raise ValueError("지원하는 시퀀스 FPS를 선택해 주세요.")
    origin = min(c.offset for c in chosen)
    root = ET.Element("xmeml",version="5")
    seq = ET.SubElement(root,"sequence",id="synclab-sequence")
    _tag(seq,"name",title)
    starts = [frames(c.offset-origin, fps) for c in chosen]
    ends = [start+max(1,frames(c.duration,fps)) for c,start in zip(chosen,starts)]
    _tag(seq,"duration",max(ends))
    _rate(seq,fps)
    timecode = ET.SubElement(seq,"timecode")
    _rate(timecode,fps)
    _tag(timecode,"string","00:00:00:00")
    _tag(timecode,"frame",0)
    _tag(timecode,"displayformat","NDF")
    media = ET.SubElement(seq,"media")
    video, audio = ET.SubElement(media,"video"), ET.SubElement(media,"audio")
    representative = next((c for c in chosen if c.has_video),None)
    if representative:
        _characteristics(ET.SubElement(video,"format"),representative,fps)
    asc = ET.SubElement(ET.SubElement(audio,"format"),"samplecharacteristics")
    _tag(asc,"depth",16)
    _tag(asc,"samplerate",48000)
    vi, ai = 0, 0
    for number,(c,start,end) in enumerate(zip(chosen,starts,ends),1):
        source_fps = c.fps if c.has_video else fps
        refs = []
        if c.has_video:
            vi += 1
            refs.append((f"clip-{number}-v", "video", vi, 0))
        for channel in range(c.channels):
            ai += 1
            refs.append((f"clip-{number}-a{channel+1}", "audio", ai, channel+1))
        for index,(ref,kind,track_index,channel) in enumerate(refs):
            track = ET.SubElement(video if kind == "video" else audio, "track")
            ci = ET.SubElement(track,"clipitem",id=ref)
            _tag(ci,"name",c.name)
            _tag(ci,"enabled","TRUE")
            if c.status in {"미일치", "오디오 없음", "무음", "읽기 실패", "확인 필요"}:
                _tag(ET.SubElement(ci, "labels"), "label2", "Rose")
            _tag(ci,"duration",max(1,frames(c.duration,source_fps)))
            _rate(ci,source_fps)
            source_in = frames(c.source_in, source_fps)
            for key,value in [("start",start),("end",end),("in",source_in),("out",source_in+max(1,frames(c.duration,source_fps)))]:
                _tag(ci,key,value)
            if index == 0:
                _file(ci,c,number,source_fps)
            else:
                ET.SubElement(ci,"file",id=f"file-{number}")
            if kind == "video":
                _tag(ci,"pixelaspectratio","square")
                _tag(ci,"anamorphic","FALSE")
            else:
                sourcetrack = ET.SubElement(ci,"sourcetrack")
                _tag(sourcetrack,"mediatype","audio")
                _tag(sourcetrack,"trackindex",channel)
            for lr,lk,lt,lc in refs:
                link = ET.SubElement(ci,"link")
                _tag(link,"linkclipref",lr)
                _tag(link,"mediatype",lk)
                _tag(link,"trackindex",lt)
                _tag(link,"clipindex",1)
                if lk == "audio":
                    _tag(link,"groupindex",1)
            _tag(track,"enabled","TRUE")
            _tag(track,"locked","FALSE")
    ET.indent(root, space="  ")
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'+ET.tostring(root,encoding="utf-8")
    atomic_write(path,xml)
    return path


def export_csv(clips, path):
    path = protect_sources(path,clips)
    chosen = selected(clips)
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["file","path","offset_seconds","timeline_seconds","duration_seconds","match_score","status","warnings"])
    origin = min(c.offset for c in chosen)
    def safe(value):
        value = str(value)
        return "'"+value if value.startswith(("=","+","-","@","\t","\r","\n")) else value
    for c in chosen:
        writer.writerow([safe(c.name),safe(c.path),f"{c.offset:.6f}",f"{c.offset-origin:.6f}",
                         f"{c.duration:.6f}",f"{c.score:.3f}",safe(c.status),safe(" | ".join(c.warnings))])
    atomic_write(path,stream.getvalue().encode("utf-8-sig"))
    return path
