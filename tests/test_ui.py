import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import time
from fractions import Fraction
import pytest
from PySide6.QtWidgets import QApplication
from conftest import sound
from test_media import write_wav
from synclab.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_job(window, app):
    deadline = time.monotonic()+20
    while window.busy and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.01)
    assert not window.busy
    app.processEvents()


def test_timeline_workspace_review_and_return_to_xml_start(app,tmp_path):
    from synclab.models import Clip
    from synclab.export import export_xml
    paths=[tmp_path/n for n in ['reference.wav','camera.wav']]
    for p in paths: write_wav(p,sound(4))
    xml=tmp_path/'timeline.xml'
    export_xml([Clip(p,4,channels=1,offset=0,included=True) for p in paths],xml,Fraction(25))
    w=MainWindow()
    w.show()
    app.processEvents()
    assert w.empty_state.isVisible() and not w.workspace_page.isVisible()
    w.load_xml(xml)
    wait_job(w,app)
    assert w.workspace_page.isVisible() and not w.empty_state.isVisible()
    assert not w.inspector.isVisible()
    w.timeline.selected.emit(1)
    app.processEvents()
    assert w.selected_clip().path==paths[1] and w.inspector.isVisible()
    w.plus_button.click()
    assert w.clips[1].offset==pytest.approx(.04)
    w.zoom_slider.setValue(4)
    w.fit_button.click()
    assert w.timeline.minimumWidth()<=w.scroll.viewport().width()
    w.dirty=False
    w.new_workspace()
    app.processEvents()
    assert w.empty_state.isVisible() and not w.workspace_page.isVisible()
    w.close()


def test_add_sync_manual_save_and_export_flow(app,tmp_path):
    source = sound(20)
    a,b = tmp_path/"reference.wav",tmp_path/"camera.wav"
    write_wav(a,source[:15*4000])
    write_wav(b,source[3*4000:18*4000])
    w = MainWindow()
    w.add_paths([str(a),str(b),str(a)])
    wait_job(w,app)
    assert len(w.clips) == 2
    w.start_sync()
    wait_job(w,app)
    assert w.clips[1].offset == pytest.approx(3.,abs=.003)
    assert all(c.included for c in w.clips)
    w.table.selectRow(1)
    app.processEvents()
    w.offset_spin.setValue(3.04)
    w.apply_offset()
    assert w.clips[1].offset == pytest.approx(3.04)
    assert w.clips[1].status == "수동 보정"
    project,xml = tmp_path/"work.synclab",tmp_path/"work.xml"
    w.save_to(project)
    w.export_to(xml)
    assert xml.exists()
    w.load_from(project)
    wait_job(w,app)
    assert w.clips[1].offset == pytest.approx(3.04)
    w.dirty = False
    w.close()


def test_busy_cancel_does_not_apply_partial_state(app,tmp_path):
    a = tmp_path/"a.wav"
    write_wav(a,sound(5))
    w = MainWindow()
    w.add_paths([str(a)])
    w.cancel_work()
    wait_job(w,app)
    assert len(w.clips) in (0,1)
    assert w.add_button.isEnabled()
    w.dirty = False
    w.close()


def test_xml_sync_preserves_unmatched_and_project_roundtrip(app, tmp_path):
    from synclab.models import Clip
    from synclab.export import export_xml
    from synclab.interchange import read_timeline
    a, b, other = [tmp_path/n for n in ['a.wav', 'b.wav', 'other.wav']]
    source = sound(20)
    for path, data in [(a, source[:15*4000]), (b, source[3*4000:18*4000]), (other, sound(4, 294))]:
        write_wav(path, data)
    clips = [Clip(p, d, channels=1, included=True, offset=0) for p, d in [(a,15), (b,15), (other,4)]]
    xml = tmp_path/'input.xml'
    export_xml(clips, xml, Fraction(25))
    w = MainWindow()
    w.load_xml(xml)
    wait_job(w, app)
    assert w.timeline_document is not None
    w.start_sync()
    wait_job(w, app)
    assert w.clips[1].offset == pytest.approx(3, abs=.003)
    assert w.clips[2].status == '미일치'
    assert w.clips[2].included and w.clips[2].offset >= 18
    w.remove_gaps_check.setChecked(True)
    w.table.selectRow(1)
    w.offset_spin.setValue(3.04)
    w.apply_offset()
    project = tmp_path/'saved.synclab'
    w.save_to(project)
    w.load_from(project)
    wait_job(w, app)
    assert w.timeline_document is not None and w.remove_gaps_check.isChecked()
    assert w.clips[1].offset == pytest.approx(3.04)
    assert len(w.clips[0].audio) > 0
    w.export_to(tmp_path/'result.xml')
    result = read_timeline(tmp_path/'result.xml')
    assert len(result.clips) == 3
    w.dirty = False
    w.close()


def test_reference_change_and_removal_rebase_labels(app, tmp_path):
    from synclab.models import Clip
    w = MainWindow()
    w.clips = [Clip(tmp_path/f'{i}.wav', 5, id=str(i), offset=float(i*3), status='기준' if i==0 else '싱크 완료') for i in range(3)]
    w.reference_id = '0'
    w.refresh()
    w.change_reference(1)
    assert w.reference_id == '1' and w.clips[1].offset == 0
    assert [c.status for c in w.clips].count('기준') == 1
    assert w.clips[1].status == '기준'
    w.table.selectRow(1)
    w.remove_selected()
    assert w.reference_id in {c.id for c in w.clips}
    assert next(c for c in w.clips if c.id == w.reference_id).offset == 0
    w.dirty = False
    w.close()


def test_reload_after_source_change_invalidates_old_alignment(app, tmp_path):
    path=tmp_path/'source.wav'
    write_wav(path,sound(5))
    w=MainWindow()
    w.add_paths([str(path)])
    wait_job(w,app)
    w.start_sync()
    wait_job(w,app)
    assert w.clips[0].offset == 0
    write_wav(path,sound(6,421))
    w.reload_audio()
    wait_job(w,app)
    assert w.clips[0].offset is None
    assert not w.clips[0].included
    assert w.clips[0].status == '원본 변경됨'
    w.dirty=False
    w.close()


def test_user_exclusion_survives_resync(app,tmp_path):
    p=tmp_path/'excluded.wav'
    write_wav(p,sound(5))
    w=MainWindow()
    w.add_paths([str(p)])
    wait_job(w,app)
    w.start_sync()
    wait_job(w,app)
    w._set_included(w.clips[0],False)
    w.start_sync()
    wait_job(w,app)
    assert not w.clips[0].included
    w.dirty=False
    w.close()


def test_inspector_selection_keeps_xml_tracks_and_gap_view(app,tmp_path):
    from test_interchange import timeline_file
    w=MainWindow()
    w.load_xml(timeline_file(tmp_path))
    wait_job(w,app)
    assert len(w.timeline.clips)==len(w.timeline_document.items)==6
    w.clips[2].offset=20
    w.remove_gaps_check.setChecked(True)
    w.table.selectRow(2)
    app.processEvents()
    assert len(w.timeline.track_keys)==6
    displayed=next(c for c in w.timeline.clips if c.id==w.clips[2].id)
    assert displayed.offset==10
    assert w.clips[2].offset==20
    w.dirty=False
    w.close()


def test_corrupted_source_after_project_reload_cannot_disappear_from_export(app,tmp_path):
    w=MainWindow()
    paths=[tmp_path/name for name in ['valid.wav','will-corrupt.wav']]
    for p in paths: write_wav(p,sound(5))
    w.add_paths([str(p) for p in paths])
    wait_job(w,app)
    w.start_sync()
    wait_job(w,app)
    project=tmp_path/'work.synclab'
    w.save_to(project)
    paths[1].write_bytes(b'broken container')
    w.load_from(project)
    wait_job(w,app)
    assert w.clips[1].status=='읽기 실패'
    assert not w.clips[1].included and not w.clips[1].excluded
    with pytest.raises(ValueError,match='원본'):
        w.export_to(tmp_path/'must-not-omit.xml')
    w.dirty=False
    w.close()


def test_csv_cannot_overwrite_imported_xml(app,tmp_path):
    from test_interchange import timeline_file
    path=timeline_file(tmp_path)
    before=path.read_bytes()
    w=MainWindow()
    w.load_xml(path)
    wait_job(w,app)
    with pytest.raises(ValueError,match='XML'):
        w.csv_to(path)
    assert path.read_bytes()==before
    w.dirty=False
    w.close()


def test_unplaced_added_media_requires_placement_or_explicit_exclusion(app,tmp_path):
    paths=[tmp_path/n for n in ['first.wav','second.wav']]
    for p in paths: write_wav(p,sound(5))
    w=MainWindow()
    w.add_paths([str(p) for p in paths])
    wait_job(w,app)
    w.table.selectRow(0)
    w.offset_spin.setValue(0)
    w.apply_offset()
    with pytest.raises(ValueError):
        w.export_to(tmp_path/'incomplete.xml')
    w._set_included(w.clips[1],False)
    w.export_to(tmp_path/'explicit-only.xml')
    assert (tmp_path/'explicit-only.xml').exists()
    w.dirty=False
    w.close()


def test_xml_prepare_accepts_over_512mb_of_disk_backed_audio(app,tmp_path,monkeypatch):
    from dataclasses import replace
    import numpy as np
    import synclab.ui as ui
    from synclab.models import Clip,SAMPLE_RATE
    source=tmp_path/'source.wav';source.write_bytes(b'fixture')
    # Nine 70-minute intervals previously failed the aggregate 512 MB guard.
    audio=np.memmap(tmp_path/'long.f32',dtype=np.float32,mode='w+',shape=(70*60*SAMPLE_RATE,))
    clips=[Clip(source,70*60,track='A1') for _ in range(9)]
    monkeypatch.setattr(ui,'decode_clip',lambda c,*args,**kwargs:replace(c,audio=audio))
    w=MainWindow()
    prepared=w._prepare(clips,lambda:False,lambda *args:None)
    assert len(prepared)==9 and sum(c.audio.nbytes for c in prepared)>512*1024**2
    assert all(isinstance(c.audio,np.memmap) for c in prepared)
    w.close()


def test_independent_groups_persist_and_preview_with_their_own_partner(app,tmp_path):
    from synclab.interchange import read_timeline
    main,other=sound(80,1),sound(45,2)
    data=[main[:60*4000],main[4*4000:34*4000],other[:30*4000],other[7*4000:37*4000],sound(8,3)]
    paths=[tmp_path/f'{name}.wav' for name in ['reference','camera','group-a','group-b','alone']]
    for p,x in zip(paths,data):write_wav(p,x)
    w=MainWindow();w.add_paths([str(p) for p in paths]);wait_job(w,app)
    w.start_sync();wait_job(w,app)
    by={c.path:c for c in w.clips}
    assert by[paths[2]].sync_group==by[paths[3]].sync_group==2
    assert by[paths[3]].offset-by[paths[2]].offset==pytest.approx(7,abs=.003)
    assert by[paths[4]].status=='미일치' and by[paths[4]].sync_group==0
    assert by[paths[4]].offset>=max(c.offset+c.duration for c in w.clips if c.sync_group>0)
    assert w.preview_reference(by[paths[3]]).path==paths[2]
    groups={c.id:c.sync_group for c in w.clips}
    w.save_to(tmp_path/'groups.synclab');w.load_from(tmp_path/'groups.synclab');wait_job(w,app)
    assert {c.id:c.sync_group for c in w.clips}==groups
    w.export_to(tmp_path/'groups.xml')
    assert len(read_timeline(tmp_path/'groups.xml').clips)==5
    w.dirty=False;w.close()


def test_update_check_button_returns_to_idle_without_changing_work(app,monkeypatch):
    import synclab.updates as updates
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(updates,'fetch_latest',lambda:None)
    monkeypatch.setattr(QMessageBox,'information',lambda *args:None)
    w=MainWindow()
    try:
        w.update_button.click();wait_job(w,app)
        assert w.update_button.isEnabled() and not w.clips and not w.dirty
        assert '최신 버전' in w.status_label.text()
    finally:w.close()
