from fractions import Fraction
import xml.etree.ElementTree as ET

import pytest

from synclab.export import export_xml
from synclab.models import Clip


def timeline_file(tmp_path):
    a, b, silent = [tmp_path / n for n in ['카메라 A.mov', 'B.mov', 'silent.wav']]
    for p in (a, b, silent):
        p.touch()
    clips = [Clip(a, 10, width=1920, height=1080, channels=2, offset=0, included=True),
             Clip(b, 5, width=1920, height=1080, channels=1, offset=0, included=True),
             Clip(silent, 3, channels=1, offset=0, included=True)]
    p = tmp_path / 'input.xml'
    export_xml(clips, p, Fraction(25))
    tree = ET.parse(p)
    seq = tree.getroot().find('sequence')
    seq.find('name').text = '테스트 시퀀스'
    ET.SubElement(seq, 'custom-data').text = 'keep sequence metadata'
    ci = seq.find('media/video/track/clipitem')
    ci.find('name').text = 'renamed camera'
    effect = ET.SubElement(ET.SubElement(ci, 'filter'), 'effect')
    ET.SubElement(effect, 'effectid').text = 'basic'
    ET.SubElement(effect, 'custom').text = 'keep effect'
    tree.write(p, encoding='utf-8', xml_declaration=True)
    return p


def read(path):
    from synclab.interchange import read_timeline
    return read_timeline(path)


def test_read_tracks_links_renamed_clip_and_roundtrip_metadata(tmp_path):
    source = timeline_file(tmp_path)
    source.write_text(source.read_text(encoding='utf-8').replace('file://localhost/', 'file:///'), encoding='utf-8')
    doc = read(source)
    assert doc.fps == 25 and doc.title == '테스트 시퀀스'
    assert len(doc.items) == 6 and len(doc.clips) == 3
    assert doc.clips[0].name == 'renamed camera'
    assert [c.track for c in doc.clips] == ['V1', 'V2', 'A4']
    assert {i.track for i in doc.items} == {'V1', 'V2', 'A1', 'A2', 'A3', 'A4'}
    before = doc.source_path.read_bytes()
    doc.clips[0].offset = -2
    doc.clips[1].offset = 3
    doc.clips[2].offset = 9
    doc.clips[2].status = '미일치'
    out = tmp_path / 'out.xml'
    doc.write(out, doc.clips)
    root = ET.parse(out).getroot()
    assert root.findtext('sequence/custom-data') == 'keep sequence metadata'
    assert root.findtext('sequence/media/video/track/clipitem/filter/effect/custom') == 'keep effect'
    assert [int(c.findtext('start')) for c in root.findall('sequence/media/video/track/clipitem')] == [0, 125]
    assert all(int(c.findtext('start')) == 0 for c in root.findall('sequence/media/audio/track')[:2] for c in c.findall('clipitem'))
    assert root.findtext('sequence/media/audio/track[4]/clipitem/labels/label2') == 'Rose'
    assert before == doc.source_path.read_bytes()
    assert len(read(out).items) == 6
    assert all(n.text.startswith('file://localhost/') for n in root.iter('pathurl'))
    with pytest.raises(ValueError, match='XML'):
        doc.write(doc.source_path, doc.clips)


def test_shared_file_definition_survives_excluding_definition_owner(tmp_path):
    doc = read(timeline_file(tmp_path))
    # The first source's full file definition is on its video item.
    tree = ET.parse(doc.source_path)
    v = tree.getroot().find('sequence/media/video/track/clipitem')
    # Make audio independent, so excluding the video group must rehydrate file refs.
    for ci in tree.getroot().iter('clipitem'):
        for link in list(ci.findall('link')):
            ci.remove(link)
    tree.write(doc.source_path, encoding='utf-8')
    doc = read(doc.source_path)
    doc.clips[0].included = False
    out = tmp_path / 'excluded.xml'
    doc.write(out, doc.clips)
    reread = read(out)
    assert len(reread.items) == 5
    assert all(c.path.is_file() for c in reread.clips)
    ids = {i.id for i in reread.items}
    assert v.attrib['id'] not in ids


def test_trimmed_duplicate_instances_stay_separate(tmp_path):
    p = timeline_file(tmp_path)
    tree = ET.parse(p)
    root = tree.getroot()
    tracks = root.findall('sequence/media/video/track')
    first = tracks[0].find('clipitem')
    duplicate = ET.fromstring(ET.tostring(first))
    duplicate.attrib['id'] = 'duplicate-instance'
    for link in list(duplicate.findall('link')):
        duplicate.remove(link)
    duplicate.find('start').text = '300'
    duplicate.find('end').text = '425'
    duplicate.find('in').text = '50'
    duplicate.find('out').text = '175'
    tracks[0].append(duplicate)
    tree.write(p, encoding='utf-8')
    doc = read(p)
    assert len(doc.clips) == 4
    dup = next(c for c in doc.clips if c.id == 'duplicate-instance')
    assert dup.source_in == 2 and dup.duration == 5 and dup.offset == 12
    out = tmp_path / 'trim.xml'
    dup.offset = 20
    doc.write(out, doc.clips)
    ci = next(c for c in ET.parse(out).getroot().iter('clipitem') if c.get('id') == dup.id)
    assert [ci.findtext(k) for k in ['start', 'end', 'in', 'out']] == ['500', '625', '50', '175']


def test_output_sorts_track_and_rejects_overlapping_manual_edits(tmp_path):
    p=timeline_file(tmp_path)
    tree=ET.parse(p)
    track=tree.getroot().find('sequence/media/video/track')
    original=track.find('clipitem')
    second=ET.fromstring(ET.tostring(original))
    second.set('id','later')
    for link in list(second.findall('link')): second.remove(link)
    second.find('start').text='300'
    second.find('end').text='550'
    track.append(second)
    tree.write(p,encoding='utf-8')
    doc=read(p)
    next(c for c in doc.clips if c.id=='later').offset=-12
    out=tmp_path/'reordered.xml'
    doc.write(out,doc.clips)
    assert [ci.get('id') for ci in ET.parse(out).getroot().findall('sequence/media/video/track[1]/clipitem')]==['later',original.get('id')]
    next(c for c in doc.clips if c.id=='later').offset=5
    with pytest.raises(ValueError, match='겹'):
        doc.write(tmp_path/'overlap.xml',doc.clips)


def test_auto_sync_separates_collisions_preserving_items_links_and_offsets(tmp_path):
    p=timeline_file(tmp_path)
    tree=ET.parse(p);track=tree.getroot().find('sequence/media/video/track')
    original=track.find('clipitem')
    other=ET.fromstring(ET.tostring(original));other.set('id','extra-camera')
    for link in list(other.findall('link')):other.remove(link)
    other.find('start').text='300';other.find('end').text='550'
    track.append(other);tree.write(p,encoding='utf-8')
    doc=read(p)
    extra=next(c for c in doc.clips if c.id=='extra-camera');extra.offset=5
    before={c.id:c.offset for c in doc.clips};count=len(doc.items)
    assert doc.separate_overlaps(doc.clips)==1
    assert {c.id:c.offset for c in doc.clips}==before
    assert len(doc.items)==count
    assert doc.separate_overlaps(doc.clips)==0
    shown={c.track for c in doc.display_clips(doc.clips)}
    target=tmp_path/'split.xml';doc.write(target,doc.clips)
    loaded=read(target)
    assert len(loaded.items)==count
    assert {i.track for i in loaded.items}==shown
    root=ET.parse(target).getroot();indices={}
    assert all('synclab-primary' not in ci.attrib for ci in root.iter('clipitem'))
    for kind in ['video','audio']:
        for ti,t in enumerate(root.findall(f'sequence/media/{kind}/track'),1):
            end=-1
            for ci_index,ci in enumerate(t.findall('clipitem'),1):
                assert int(ci.findtext('start'))>=end
                end=int(ci.findtext('end'));indices[ci.get('id')]=(kind,ti,ci_index)
    for ci in root.iter('clipitem'):
        for link in ci.findall('link'):
            assert (link.findtext('mediatype'),int(link.findtext('trackindex')),int(link.findtext('clipindex')))==indices[link.findtext('linkclipref')]


def test_split_stereo_audio_keeps_group_identity_in_saved_project(tmp_path):
    from synclab.project import save_project,load_project_timeline
    paths=[tmp_path/n for n in ['stereo.wav','mono.wav']]
    for p in paths:p.touch()
    source=tmp_path/'stereo.xml'
    export_xml([Clip(paths[0],10,channels=2,included=True,offset=0),
                Clip(paths[1],10,channels=1,included=True,offset=12)],source,Fraction(25))
    tree=ET.parse(source);tracks=tree.getroot().findall('sequence/media/audio/track')
    mono=tracks[2].find('clipitem');tracks[2].remove(mono);tracks[0].append(mono)
    tree.write(source,encoding='utf-8');doc=read(source)
    next(c for c in doc.clips if c.path==paths[0]).offset=5
    next(c for c in doc.clips if c.path==paths[1]).offset=0
    doc.separate_overlaps(doc.clips)
    project=tmp_path/'split.synclab'
    save_project(doc.clips,doc.clips[0].id,doc.fps,project,doc)
    loaded,_=load_project_timeline(project)
    assert {c.id for c in loaded.clips}=={c.id for c in doc.clips}


def test_remove_global_gaps_is_reversible_and_retains_overlap(tmp_path):
    from synclab.interchange import display_offsets
    doc = read(timeline_file(tmp_path))
    for c, offset in zip(doc.clips, [0, 3, 20]):
        c.offset = offset
    original = [c.offset for c in doc.clips]
    compact = display_offsets(doc.clips, True)
    assert [compact[c.id] for c in doc.clips] == [0, 3, 10]
    assert [c.offset for c in doc.clips] == original
    assert list(display_offsets(doc.clips, False).values()) == original


def test_missing_media_is_visible_and_export_blocks(tmp_path):
    p = timeline_file(tmp_path)
    (tmp_path / 'B.mov').unlink()
    doc = read(p)
    assert doc.clips[1].status == '파일 없음'
    assert doc.clips[1].included
    with pytest.raises(ValueError, match='원본'):
        doc.write(tmp_path / 'out.xml', doc.clips)


@pytest.mark.parametrize('change',['missing','changed'])
def test_saved_project_never_silently_omits_invalid_sources(tmp_path,change):
    from synclab.project import save_project,load_project,load_project_timeline
    doc=read(timeline_file(tmp_path))
    project=tmp_path/'work.synclab'
    save_project(doc.clips,doc.clips[0].id,doc.fps,project,doc)
    if change=='missing': doc.clips[1].path.unlink()
    else: doc.clips[1].path.write_bytes(b'different')
    clips,_,_=load_project(project)
    restored,_=load_project_timeline(project)
    with pytest.raises(ValueError,match='원본'):
        restored.write(tmp_path/'must-not-omit.xml',clips)


def test_relink_updates_all_shared_references(tmp_path):
    doc = read(timeline_file(tmp_path))
    old = doc.clips[0].path
    new = tmp_path/'relocated camera.mov'
    old.rename(new)
    doc.relink(old, new)
    assert doc.clips[0].path == new
    out = tmp_path/'relinked.xml'
    doc.write(out, doc.clips)
    again = read(out)
    assert again.clips[0].path == new
    assert all(i.path != old for i in again.items)
    from synclab.project import save_project, load_project_timeline
    project=tmp_path/'relinked.synclab'
    save_project(doc.clips,doc.clips[0].id,doc.fps,project,doc)
    restored,_=load_project_timeline(project)
    assert restored.clips[0].path==new


@pytest.mark.parametrize('change', ['nested', 'transition', 'speed', 'entity'])
def test_unsupported_edits_and_entities_reject_without_output(tmp_path, change):
    p = timeline_file(tmp_path)
    tree = ET.parse(p)
    ci = tree.getroot().find('sequence/media/video/track/clipitem')
    if change == 'nested':
        ET.SubElement(ci, 'sequence', id='nested')
    elif change == 'transition':
        ET.SubElement(tree.getroot().find('sequence/media/video/track'), 'transitionitem')
    elif change == 'speed':
        ci.find('filter/effect/effectid').text = 'timeremap'
    tree.write(p, encoding='utf-8')
    if change == 'entity':
        p.write_text('<!DOCTYPE xmeml [<!ENTITY x "expanded">]><xmeml/>', encoding='utf-8')
    with pytest.raises(ValueError):
        read(p)
