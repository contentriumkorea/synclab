"""Opt-in local integration test, used by developers and the packaged smoke test."""
import json
import hashlib
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

from PySide6.QtCore import QTimer, qVersion, qInstallMessageHandler
from PySide6.QtMultimedia import QMediaDevices

from .interchange import read_timeline


def run_smoke(app, window, xml_path, output):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    manifest=Path(xml_path).with_suffix('.expected.json')
    expected=json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    report={'frozen':bool(getattr(sys,'frozen',False)),'qt':qVersion(),
            'input_xml':str(Path(xml_path).resolve()),'success':False}
    if report['frozen']:
        report['executable_sha256']=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    start=time.monotonic()
    stage='load'
    timer=QTimer(window)
    timer.setInterval(50)
    errors=[]
    def qt_message(kind,context,message):
        if 'QAudioSink::start' in message and 'not supported' in message:errors.append(message)
        if previous_handler:previous_handler(kind,context,message)
        else:sys.stderr.write(message+'\n')
    previous_handler=qInstallMessageHandler(qt_message)
    window.player.errorOccurred.connect(lambda code,message:errors.append(message))

    def finish(code,error=None):
        timer.stop()
        qInstallMessageHandler(previous_handler)
        report['elapsed_seconds']=round(time.monotonic()-start,3)
        report['success']=code==0
        if error: report['error']=str(error)
        (output/'startup-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.dirty=False
        window.close()
        app.exit(code)

    def tick():
        nonlocal stage
        try:
            if time.monotonic()-start>90:
                raise RuntimeError('스모크 검사가 90초를 초과했습니다: '+window.status_label.text())
            if window.busy: return
            if stage=='load':
                window.load_xml(xml_path)
                stage='sync'
            elif stage=='sync':
                if not window.clips: raise RuntimeError('XML 클립이 없습니다.')
                window.start_sync()
                stage='save'
            elif stage=='save':
                for c in window.clips:
                    if c.name in expected.get('offsets',{}):
                        wanted=expected['offsets'][c.name]
                        if c.offset is None or abs(c.offset-wanted)>.003:
                            raise AssertionError(f'{c.name}: {c.offset} != {wanted}')
                    elif c.name in expected.get('unmatched',[]):
                        if c.status!='미일치' or not c.included:
                            raise AssertionError('미일치 보존 실패: '+c.name)
                report['offsets']={c.name:c.offset for c in window.clips}
                report['statuses']={c.name:c.status for c in window.clips}
                report['sync_groups']={c.name:c.sync_group for c in window.clips}
                for c in window.clips:
                    if c.name in expected.get('groups',{}):
                        if c.sync_group!=expected['groups'][c.name]:raise AssertionError('싱크 그룹 불일치: '+c.name)
                window.save_to(output/'Smoke.synclab')
                window.load_from(output/'Smoke.synclab')
                stage='play'
            elif stage=='play':
                target=next((c for c in window.clips if c.id!=window.reference_id and c.status in {'싱크 완료','확인 필요'}),None)
                if target is None: raise AssertionError('비교 청취할 일치 클립이 없습니다.')
                window.table.selectRow(window.clips.index(target))
                window.preview_start.setValue(max(0,target.offset)+2)
                window.audio_out.setVolume(0)
                report['audio_hardware']=not QMediaDevices.defaultAudioOutput().isNull()
                if not report['audio_hardware']:window.player.setAudioOutput(None)
                window.preview()
                stage='verify_playback'
            elif stage=='verify_playback':
                if errors: raise RuntimeError('비교 청취 실패: '+'; '.join(errors))
                if window.player.position()<250: return
                report['playback_position_ms']=window.player.position()
                report['playback_duration_ms']=window.player.duration()
                report['audio_device']=window.audio_out.device().description()
                window.player.stop()
                window.export_to(output/'Smoke_Synced.xml')
                result=read_timeline(output/'Smoke_Synced.xml')
                if len(result.items)!=len(window.timeline_document.items):
                    raise AssertionError('XML 왕복 중 clipitem 개수가 달라졌습니다.')
                root=ET.parse(output/'Smoke_Synced.xml').getroot()
                report['xml_items']=len(result.items)
                report['display_tracks']=len(window.timeline.track_keys)
                if report['display_tracks']!=len(set(i.track for i in result.items)):
                    raise AssertionError('화면의 XML 트랙 개수가 출력과 다릅니다.')
                report['rose_items']=len(root.findall('.//clipitem/labels/[label2="Rose"]'))
                window.notice('로컬 통합 테스트 완료 · XML 왕복 / 싱크 / 프로젝트 복구 / 재생 확인')
                app.processEvents()
                if not window.grab().save(str(output/'SyncLab.png')):
                    raise RuntimeError('앱 화면 저장에 실패했습니다.')
                finish(0)
        except Exception as exc:
            finish(1,exc)
    timer.timeout.connect(tick)
    timer.start()
    return timer
