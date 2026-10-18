"""FCP 7 XML round trip: preserve edits and references, change placement only."""
from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

import numpy as np

from .export import FPS_CHOICES, frames, selected, media_uri
from .media import decode_media, file_fingerprint
from .models import Clip, SAMPLE_RATE
from .storage import atomic_write, protect_sources

MAX_XML_BYTES = 20 * 1024 * 1024
UNMATCHED = {"미일치", "오디오 없음", "무음", "읽기 실패"}


def read_rate(node, fallback=None):
    rate = node.find('rate') if node is not None else None
    if rate is None:
        if fallback is not None:
            return fallback
        raise ValueError('XML에 프레임률이 없습니다.')
    try:
        nominal = int(rate.findtext('timebase', '0'))
        fps = Fraction(nominal * 1000, 1001) if rate.findtext('ntsc', '').upper() == 'TRUE' else Fraction(nominal)
        if not 0 < fps <= 240:
            raise ValueError()
        return fps
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('XML의 프레임률이 유효하지 않습니다.') from exc


def media_path(value, base):
    if not value or not value.strip():
        raise ValueError('XML 미디어 경로가 비어 있습니다.')
    value = value.strip()
    if value.lower().startswith('file:'):
        uri = urlsplit(value)
        if uri.query or uri.fragment:
            raise ValueError('XML 파일 URI의 query/fragment는 지원하지 않습니다.')
        path = unquote(uri.path)
        if uri.netloc and uri.netloc.lower() != 'localhost':
            path = '//' + uri.netloc + path
        elif re.match(r'^/[A-Za-z]:', path):
            path = path[1:]
        result = Path(path)
    elif '://' in value:
        raise ValueError('XML은 로컬 또는 네트워크 파일 경로만 지원합니다.')
    else:
        result = Path(value)
    return (base / result).resolve() if not result.is_absolute() else result.resolve()


def _set(node, tag, value):
    child = node.find(tag)
    if child is None:
        child = ET.SubElement(node, tag)
    child.text = str(value)


@dataclass(frozen=True)
class TimelineItem:
    id: str
    group_id: str
    track: str
    start: int
    end: int
    source_in: int
    source_out: int
    source_fps: Fraction
    file_id: str
    path: Path


def display_offsets(clips, remove_gaps=False):
    """Derive a view from unmodified offsets, closing only globally empty time."""
    placed = [c for c in clips if c.included and c.offset is not None]
    result = {c.id: c.offset for c in clips}
    if not remove_gaps or not placed:
        return result
    intervals = sorted((c.offset, c.offset + c.duration) for c in placed)
    gaps, end = [], intervals[0][0]
    for start, stop in intervals:
        if start > end + 1e-8:
            gaps.append((end, start))
        end = max(end, stop)
    for c in placed:
        result[c.id] = c.offset - sum(b-a for a, b in gaps if b <= c.offset + 1e-8)
    return result


def retain_unmatched(clips, placements, scores, warnings, reference_id,group_ids=None):
    """Keep every source, placing unconfirmed sources in a separate tail area."""
    end = max((placements[c.id] + c.duration for c in clips if c.id in placements), default=0)
    tail = end + 1.0
    for c in clips:
        c.score = scores.get(c.id, 0.)
        c.sync_group=(group_ids or {}).get(c.id,1 if c.id in placements else 0)
        c.warnings = [w for w in c.warnings if not any(t in w for t in ['드리프트','오프셋 편차','매칭 경로','자동 일치','다시 분석','별도 싱크 그룹','낮은 파형 점수'])]
        c.warnings.extend(warnings.get(c.id, []))
        if c.id in placements:
            c.offset = placements[c.id]
            c.status = '기준' if c.id == reference_id else ('확인 필요' if c.id in warnings else '싱크 완료')
            if c.sync_group>1:
                if c.status=='싱크 완료':c.status='그룹 싱크'
                c.warnings.append(f'별도 싱크 그룹 {c.sync_group}: 그룹 안의 상대 싱크만 확인했습니다. 다른 그룹과 실제 시간 관계는 미확인이라 별도 영역에 배치했습니다.')
        else:
            c.offset = tail
            tail += c.duration + .25
            if c.status not in {'읽기 실패', '파일 없음'}:
                c.status = '미일치' if len(c.audio) else '오디오 없음'
            c.warnings.append('자동 일치를 확인하지 못해 결과 끝에 보존했습니다. 수동 확인이 필요합니다.')
        c.included = not c.excluded


def decode_clip(c, cancelled=lambda: False, progress=lambda value:None):
    """Read only the source interval represented by an XML/project clip instance."""
    fresh = decode_media(c.path, cancelled,progress)
    if not c.track:  # Direct media input uses its full source duration.
        fresh.id = c.id
        return fresh
    left = max(0, round((c.source_in-fresh.audio_start)*SAMPLE_RATE))
    right = max(left, round((c.source_in+c.duration-fresh.audio_start)*SAMPLE_RATE))
    audio = fresh.audio[left:right]
    if c.source_in+c.duration > fresh.duration + max(.1, 2/float(c.fps)):
        raise ValueError(f'XML 소스 구간이 원본 길이를 초과합니다: {c.name}')
    return replace(c, audio=audio, audio_start=fresh.audio_start+left/SAMPLE_RATE-c.source_in,
                   channel_used=fresh.channel_used, channels=fresh.channels,
                   source_sample_rate=fresh.source_sample_rate, fingerprint=fresh.fingerprint,
                   width=fresh.width, height=fresh.height, features=None,
                   warnings=list(dict.fromkeys(c.warnings+fresh.warnings)))


@dataclass
class TimelineDocument:
    root: ET.Element
    source_path: Path
    fps: Fraction
    title: str
    items: list[TimelineItem]
    clips: list[Clip]
    files: dict[str, ET.Element]

    def original_offsets(self):
        return {gid: min(i.start for i in self.items if i.group_id == gid)/float(self.fps)
                for gid in {i.group_id for i in self.items}}

    def separate_overlaps(self,clips):
        """After auto sync, spill colliding items into appended tracks, without trimming."""
        by_group={c.id:c for c in clips if c.included and c.offset is not None}
        by_id={i.id:i for i in self.items};original=self.original_offsets()
        seq=next(s for s in self.root.iter('sequence') if s.find('media') is not None)
        moved={};added=0
        for kind,letter in [('video','V'),('audio','A')]:
            media=seq.find(f'media/{kind}')
            if media is None:continue
            originals=list(media.findall('track'));next_track=len(originals)+1
            for track in originals:
                selected_items=[]
                for ci in track.findall('clipitem'):
                    item=by_id[ci.get('id')];c=by_group.get(item.group_id)
                    if c is None:continue
                    shift=frames(c.offset-original[c.id],self.fps)
                    selected_items.append((item.start+shift,item.end+shift,ci))
                lanes=[(track,float('-inf'),None)]
                for start,end,ci in sorted(selected_items,key=lambda row:row[0]):
                    lane=next((n for n,(_,stop,_) in enumerate(lanes) if stop<=start),None)
                    if lane is None:
                        extra=deepcopy(track)
                        for child in list(extra.findall('clipitem')):extra.remove(child)
                        media.append(extra)
                        lanes.append((extra,float('-inf'),f'{letter}{next_track}'))
                        next_track+=1;added+=1;lane=len(lanes)-1
                    target,_,key=lanes[lane]
                    if target is not track:
                        track.remove(ci);target.append(ci);moved[ci.get('id')]=key
                    lanes[lane]=(target,end,key)
        if moved:
            self.items=[replace(i,track=moved.get(i.id,i.track)) for i in self.items]
            # Internal project XML retains audio-group identity after track reordering.
            # This marker is stripped from the public Premiere XML below.
            primary_ids={c.id for c in self.clips}
            for ci in seq.iter('clipitem'):
                if ci.get('id') in primary_ids:ci.set('synclab-primary','true')
            # Saved projects must also contain valid original link indices.
            indices={}
            for kind in ['video','audio']:
                for ti,track in enumerate(seq.findall(f'media/{kind}/track'),1):
                    for index,ci in enumerate(track.findall('clipitem'),1):indices[ci.get('id')]=(kind,ti,index)
            for ci in seq.iter('clipitem'):
                for link in ci.findall('link'):
                    if link.findtext('linkclipref') in indices:
                        kind,ti,index=indices[link.findtext('linkclipref')]
                        _set(link,'mediatype',kind);_set(link,'trackindex',ti);_set(link,'clipindex',index)
        return added

    def relink(self, old, new):
        old, new = Path(old).resolve(), Path(new).resolve()
        if not new.is_file():
            raise ValueError('다시 지정할 원본 파일이 없습니다.')
        for file in self.files.values():
            if media_path(file.findtext('pathurl'), self.source_path.parent) == old:
                _set(file, 'pathurl', media_uri(new))
        for file in self.root.iter('file'):
            if file.find('pathurl') is not None and file.get('id') in self.files:
                _set(file, 'pathurl', self.files[file.get('id')].findtext('pathurl'))
        self.items = [replace(i, path=new) if i.path == old else i for i in self.items]
        for c in self.clips:
            if c.path == old:
                c.path = new
                c.fingerprint = file_fingerprint(new)

    def display_clips(self, clips, remove_gaps=False):
        by_id = {c.id: c for c in clips}
        original = self.original_offsets()
        offsets = display_offsets(clips, remove_gaps)
        view = []
        for item in self.items:
            c = by_id.get(item.group_id)
            if c is None:
                continue
            delta = item.start/float(self.fps) - original[c.id]
            start = offsets[c.id]
            cut = item.source_in/float(item.source_fps)-c.source_in
            left = max(0, round((cut-c.audio_start)*SAMPLE_RATE))
            duration = (item.end-item.start)/float(self.fps)
            data = c.audio[left:max(left, round((cut+duration-c.audio_start)*SAMPLE_RATE))]
            view.append(replace(c, track=item.track, offset=None if start is None else start+delta,
                                duration=duration, audio=data,
                                audio_start=c.audio_start+left/SAMPLE_RATE-cut))
        return view

    def write(self, path, clips, remove_gaps=False):
        path = protect_sources(path, clips)
        if path == self.source_path.resolve() or (path.exists() and self.source_path.exists() and path.samefile(self.source_path)):
            raise ValueError('입력 XML에 덮어쓸 수 없습니다. 다른 이름으로 저장하세요.')
        chosen = selected(clips)
        unknown = {c.id for c in chosen} - {c.id for c in self.clips}
        if unknown:
            raise ValueError('입력 XML에 없는 클립입니다.')
        by_id, originals = {c.id: c for c in chosen}, self.original_offsets()
        offsets = display_offsets(clips, remove_gaps)
        root = deepcopy(self.root)
        for file in root.iter('file'):
            if file.find('pathurl') is not None and file.get('id') in self.files:
                _set(file, 'pathurl', self.files[file.get('id')].findtext('pathurl'))
        seq = next(s for s in root.iter('sequence') if s.find('media') is not None)
        original_items = {i.id: i for i in self.items}
        retained = []
        for kind in ['video', 'audio']:
            for track in seq.findall(f'media/{kind}/track'):
                for ci in list(track.findall('clipitem')):
                    item = original_items[ci.get('id')]
                    c = by_id.get(item.group_id)
                    if c is None:
                        track.remove(ci)
                        continue
                    shift = frames(offsets[c.id]-originals[c.id], self.fps)
                    retained.append((ci, item.start+shift, item.end+shift, c))
        if not retained:
            raise ValueError('내보낼 XML 클립이 없습니다.')
        origin = min(start for _, start, _, _ in retained)
        for ci, start, end, c in retained:
            _set(ci, 'start', start-origin)
            _set(ci, 'end', end-origin)
            if c.status in UNMATCHED or c.status == '확인 필요':
                labels = ci.find('labels')
                if labels is None:
                    labels = ET.SubElement(ci, 'labels')
                _set(labels, 'label2', 'Rose')
        # Exclusions can remove the only full definition of a shared file.
        defined = set()
        for ci, _, _, _ in retained:
            file = ci.find('file')
            fid = file.get('id')
            if fid not in defined:
                index = list(ci).index(file)
                ci.remove(file)
                ci.insert(index, deepcopy(self.files[fid]))
                defined.add(fid)
        # Recompute link indices after exclusions, preserving unrelated metadata.
        indices = {}
        for kind in ['video', 'audio']:
            for ti, track in enumerate(seq.findall(f'media/{kind}/track'), 1):
                ordered=sorted(track.findall('clipitem'),key=lambda ci:int(ci.findtext('start')))
                previous_end=-1
                for ci in ordered:
                    if int(ci.findtext('start'))<previous_end:
                        raise ValueError(f'{kind} {ti}번 트랙의 클립이 겹칩니다. 수동 배치를 확인하세요.')
                    previous_end=int(ci.findtext('end'))
                for ci in ordered: track.remove(ci)
                for index, ci in enumerate(ordered, 1):
                    track.insert(index-1,ci)
                    indices[ci.get('id')] = (kind, ti, index)
        for ci, _, _, _ in retained:
            for link in list(ci.findall('link')):
                ref = link.findtext('linkclipref')
                if ref not in indices:
                    ci.remove(link)
                else:
                    kind, ti, index = indices[ref]
                    _set(link, 'mediatype', kind)
                    _set(link, 'trackindex', ti)
                    _set(link, 'clipindex', index)
        _set(seq, 'duration', max(end-origin for _, _, end, _ in retained))
        _set(seq, 'name', self.title+' · Synced')
        for node in root.iter('pathurl'):
            node.text = media_uri(media_path(node.text, self.source_path.parent))
        for ci in root.iter('clipitem'):ci.attrib.pop('synclab-primary',None)
        ET.indent(root, space='  ')
        atomic_write(path, b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'+ET.tostring(root, encoding='utf-8'))
        return path


def read_timeline(path, raw=None):
    path = Path(path).resolve()
    if raw is None:
        if path.stat().st_size > MAX_XML_BYTES:
            raise ValueError('XML 파일은 최대 20 MB까지 읽을 수 있습니다.')
        raw = path.read_bytes()
    if len(raw) > MAX_XML_BYTES:
        raise ValueError('XML 파일은 최대 20 MB까지 읽을 수 있습니다.')
    if b'<!ENTITY' in raw.replace(b'\x00', b'').upper():
        raise ValueError('엔티티 선언이 있는 XML은 지원하지 않습니다.')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f'XML 형식이 올바르지 않습니다: {exc}') from exc
    if root.tag != 'xmeml':
        raise ValueError('Final Cut Pro 7 XML(xmeml)이 필요합니다. FCPXML은 지원하지 않습니다.')
    sequences = [s for s in root.iter('sequence') if s.find('media') is not None]
    if len(sequences) != 1:
        raise ValueError('하나의 시퀀스 XML만 지원합니다. 중첩 시퀀스를 풀고 다시 내보내세요.')
    seq = sequences[0]
    fps = read_rate(seq)
    if fps not in FPS_CHOICES.values():
        raise ValueError('지원하지 않는 시퀀스 FPS입니다.')
    if seq.find('.//transitionitem') is not None or seq.find('.//generatoritem') is not None:
        raise ValueError('전환/생성기 클립을 제거한 싱크용 시퀀스가 필요합니다.')
    if seq.find('.//clipitem/sequence') is not None:
        raise ValueError('중첩 시퀀스는 지원하지 않습니다.')
    for effect in seq.iter('effect'):
        key = (effect.findtext('effectid', '')+' '+effect.findtext('name', '')).lower()
        if any(x in key for x in ['timeremap', 'time remap', 'timewarp', 'speed']):
            raise ValueError('속도 변경 클립을 원래 속도로 복원한 뒤 싱크하세요.')
    files = {}
    for file in root.iter('file'):
        fid = file.get('id')
        if fid and file.find('pathurl') is not None:
            if fid in files and files[fid].findtext('pathurl') != file.findtext('pathurl'):
                raise ValueError('같은 파일 ID가 서로 다른 미디어를 참조합니다.')
            files[fid] = deepcopy(file)
    raw_items, elements = [], {}
    for kind, letter in [('video', 'V'), ('audio', 'A')]:
        for ti, track in enumerate(seq.findall(f'media/{kind}/track'), 1):
            for ci in track.findall('clipitem'):
                cid = ci.get('id')
                if not cid or cid in elements:
                    raise ValueError('XML 클립 ID가 없거나 중복됩니다.')
                file = ci.find('file')
                fid = file.get('id') if file is not None else None
                if fid not in files:
                    raise ValueError(f'클립의 원본 파일 참조가 없습니다: {cid}')
                definition = files[fid]
                sfps = read_rate(ci, read_rate(definition, fps))
                try:
                    start, end, si, so = [int(ci.findtext(k, '-1')) for k in ['start', 'end', 'in', 'out']]
                    if start < 0 or end <= start or si < 0 or so <= si:
                        raise ValueError()
                    if abs((so-si)/float(sfps)-(end-start)/float(fps)) > max(2/float(sfps), 2/float(fps)):
                        raise ValueError()
                    if (end-start)/float(fps) > 6*3600 or end/float(fps) > 7*86400:
                        raise ValueError()
                except (TypeError, ValueError) as exc:
                    raise ValueError(f'클립 시간/속도가 유효하지 않습니다: {cid}') from exc
                source = media_path(definition.findtext('pathurl'), path.parent)
                raw_items.append(TimelineItem(cid, cid, f'{letter}{ti}', start, end, si, so, sfps, fid, source))
                elements[cid] = ci
    if not raw_items or len(raw_items) > 2000:
        raise ValueError('XML은 1~2000개 clipitem을 지원합니다.')
    # Explicit link groups only. Repeated instances of a file must stay separate.
    parents = {i.id: i.id for i in raw_items}
    by_id = {i.id: i for i in raw_items}
    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key
    for item in raw_items:
        for link in elements[item.id].findall('link'):
            other = by_id.get(link.findtext('linkclipref'))
            if other is None:
                continue
            if item.path != other.path:
                raise ValueError('서로 다른 원본을 수동 연결한 클립은 먼저 연결 해제해 주세요.')
            if abs((item.start-other.start)/float(fps)-(item.source_in/float(item.source_fps)-other.source_in/float(other.source_fps))) > 2/float(fps):
                raise ValueError('연결된 영상/오디오의 소스 시간이 다릅니다. 먼저 연결을 확인하세요.')
            parents[find(other.id)] = find(item.id)
    groups = {}
    for item in raw_items:
        groups.setdefault(find(item.id), []).append(item)
    clips, items = [], []
    for group in groups.values():
        primary = next((i for i in group if elements[i.id].get('synclab-primary')=='true'),
                       next((i for i in group if i.track.startswith('V')),group[0]))
        cid = primary.id
        start, end = min(i.start for i in group), max(i.end for i in group)
        file = files[primary.file_id]
        width = int(file.findtext('media/video/samplecharacteristics/width', '0'))
        height = int(file.findtext('media/video/samplecharacteristics/height', '0'))
        channels = int(file.findtext('media/audio/channelcount', '0'))
        sample_rate = int(file.findtext('media/audio/samplecharacteristics/samplerate', '48000'))
        exists = primary.path.is_file()
        c = Clip(primary.path, (end-start)/float(fps), id=cid, fps=primary.source_fps,
                 width=width, height=height, channels=channels, source_sample_rate=sample_rate,
                 offset=start/float(fps), included=True, status='대기' if exists else '파일 없음',
                 fingerprint=file_fingerprint(primary.path) if exists else {},
                 source_in=primary.source_in/float(primary.source_fps)+(start-primary.start)/float(fps),
                 track=primary.track, display_name=elements[primary.id].findtext('name', primary.path.name))
        if not exists:
            c.warnings.append('XML이 참조하는 원본 파일이 없습니다. 원본 위치를 다시 지정하세요.')
        clips.append(c)
        items.extend(replace(i, group_id=cid) for i in group)
    if len(clips) > 200:
        raise ValueError('현재 버전은 최대 200개 클립 그룹을 지원합니다.')
    # Stable timeline order, independent of union traversal.
    order = {i.id: n for n, i in enumerate(raw_items)}
    items.sort(key=lambda i: order[i.id])
    return TimelineDocument(root, path, fps, seq.findtext('name', path.stem), items, clips, files)
