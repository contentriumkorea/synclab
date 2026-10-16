from dataclasses import fields
from fractions import Fraction
from pathlib import Path
import json
import math

from .media import file_fingerprint
from .models import Clip
from .storage import atomic_write, protect_sources
from .export import FPS_CHOICES


def save_project(clips, reference_id, fps, path, timeline=None, remove_gaps=False):
    path = protect_sources(path,clips)
    if timeline is not None and (path == timeline.source_path.resolve() or (path.exists() and timeline.source_path.exists() and path.samefile(timeline.source_path))):
        raise ValueError('입력 XML에 프로젝트를 덮어쓸 수 없습니다.')
    records = []
    for c in clips:
        record = {f.name: getattr(c,f.name) for f in fields(c) if f.name not in {"audio","features","path","fps","fingerprint"}}
        record.update(path=str(c.path.resolve()), fps=str(c.fps),
                      fingerprint=c.fingerprint or (file_fingerprint(c.path) if c.path.is_file() else {}))
        records.append(record)
    doc = {"version":1,"reference_id":reference_id,"fps":str(fps),"clips":records}
    if timeline is not None:
        import xml.etree.ElementTree as ET
        doc['timeline'] = {'source_path': str(timeline.source_path),
                           'xml': ET.tostring(timeline.root, encoding='unicode')}
    doc['remove_gaps'] = bool(remove_gaps)
    atomic_write(path,json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8"))


def load_project(path):
    path = Path(path)
    try:
        if path.stat().st_size > 30*1024*1024:
            raise ValueError("프로젝트 파일이 너무 큽니다.")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("version") != 1 or not isinstance(doc.get("clips"),list) or len(doc["clips"]) > 200:
            raise ValueError("지원하지 않는 프로젝트 형식입니다.")
        fps = Fraction(doc["fps"])
        if fps not in FPS_CHOICES.values():
            raise ValueError("지원하지 않는 시퀀스 FPS입니다.")
        clips, ids = [], set()
        for raw in doc["clips"]:
            data = dict(raw)
            data["path"] = Path(data["path"])
            if not data["path"].is_absolute():
                data["path"] = (path.parent/data["path"]).resolve()
            data["fps"] = Fraction(data["fps"])
            for key in ["duration","audio_start","score"]:
                if not isinstance(data[key],(float,int)) or not math.isfinite(data[key]):
                    raise ValueError("잘못된 시간 또는 일치도 값입니다.")
            source_in = data.get('source_in', 0.)
            if not isinstance(source_in, (float,int)) or not math.isfinite(source_in) or not 0 <= source_in <= 6*3600:
                raise ValueError('잘못된 소스 시작 시간입니다.')
            if not all(isinstance(data.get(k, ''), str) for k in ['track', 'display_name']):
                raise ValueError('잘못된 트랙 또는 클립 이름입니다.')
            if not 0 < data["duration"] <= 6*3600 or not 0 < data["fps"] <= 240:
                raise ValueError("클립의 길이나 FPS가 유효하지 않습니다.")
            if data.get("offset") is not None and (not isinstance(data["offset"],(int,float)) or not math.isfinite(data["offset"]) or abs(data["offset"])>7*86400):
                raise ValueError("잘못된 시작 시간입니다.")
            for key,upper in [("width",32768),("height",32768),("channels",32),("source_sample_rate",768000),("channel_used",31)]:
                if type(data[key]) is not int or not 0 <= data[key] <= upper:
                    raise ValueError("잘못된 미디어 메타데이터입니다.")
            if type(data["included"]) is not bool or not isinstance(data["status"],str):
                raise ValueError("잘못된 클립 상태입니다.")
            if type(data.get('excluded',False)) is not bool:
                raise ValueError('잘못된 클립 제외 상태입니다.')
            if type(data.get('sync_group',0)) is not int or not 0<=data.get('sync_group',0)<=200:
                raise ValueError('잘못된 싱크 그룹 번호입니다.')
            if not isinstance(data["warnings"],list) or not all(isinstance(w,str) for w in data["warnings"]):
                raise ValueError("잘못된 경고 목록입니다.")
            c = Clip(**data)
            if not isinstance(c.id,str) or not c.id or c.id in ids:
                raise ValueError("클립 ID가 중복되거나 유효하지 않습니다.")
            ids.add(c.id)
            if not c.path.is_file():
                c.status, c.included = "파일 없음", False
                c.sync_group=0
                c.warnings.append("원본 위치를 확인하고 파일을 다시 추가하세요.")
            elif c.fingerprint and c.fingerprint != file_fingerprint(c.path):
                c.status, c.included, c.offset, c.score = "원본 변경됨", False, None, 0.
                c.sync_group=0
                c.warnings.append("저장 이후 원본이 바뀌었습니다. 다시 분석하세요.")
            if c.offset is None:
                c.included = False
            clips.append(c)
        reference = doc.get("reference_id")
        if clips and reference not in ids:
            raise ValueError("프로젝트의 기준 클립이 없습니다.")
        return clips, reference, fps
    except (KeyError,TypeError,AttributeError,ZeroDivisionError,json.JSONDecodeError,OverflowError) as exc:
        raise ValueError("프로젝트 파일의 형식이 올바르지 않습니다.") from exc


def load_project_timeline(path):
    from .interchange import read_timeline
    path = Path(path)
    if path.stat().st_size > 30*1024*1024:
        raise ValueError('프로젝트 파일이 너무 큽니다.')
    doc = json.loads(path.read_text(encoding='utf-8'))
    timeline = doc.get('timeline')
    if timeline is None:
        return None, bool(doc.get('remove_gaps', False))
    if not isinstance(timeline, dict) or not isinstance(timeline.get('xml'), str) or not isinstance(timeline.get('source_path'), str):
        raise ValueError('저장된 XML 데이터가 유효하지 않습니다.')
    return read_timeline(timeline['source_path'], timeline['xml'].encode('utf-8')), bool(doc.get('remove_gaps', False))
