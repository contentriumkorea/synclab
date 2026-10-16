from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import tempfile
import os
import numpy as np
from PySide6.QtCore import Qt, QUrl, QProcess
from PySide6.QtGui import QColor, QShortcut, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QMainWindow, QFileDialog, QMessageBox, QTableWidgetItem
from .engine import synchronize, check_cancel
from .export import export_xml, export_csv
from .layout import build_ui
from .media import decode_media, EXTENSIONS, file_fingerprint, audio_peak
from .preview import render_preview
from .project import save_project, load_project, load_project_timeline
from .interchange import read_timeline, decode_clip, display_offsets, retain_unmatched
from .style import STYLE
from .workers import Worker
from .version import VERSION
from .branding import app_icon


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.clips=[]
        self.reference_id=None
        self.project_path=None
        self.timeline_document=None
        self.dirty=False
        self.busy=False
        self.worker=None
        self._refreshing=False
        self._close_pending=False
        self._preview_dir=tempfile.TemporaryDirectory(prefix="synclab-preview-")
        self._preview_count=0
        self.setWindowTitle(f'SyncLab {VERSION}')
        self.setWindowIcon(app_icon())
        self.resize(1400,900)
        self.setMinimumSize(1040,740)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        build_ui(self)
        self.player=QMediaPlayer(self)
        self.audio_out=QAudioOutput(self)
        self.audio_out.setVolume(.65)
        self.player.setAudioOutput(self.audio_out)
        self.player.errorOccurred.connect(lambda error,message:self.notice("비교 청취: "+message))
        self.player.positionChanged.connect(self._playhead)
        self.preview_origin=0.
        for keys,slot in [("Ctrl+O",self.open_dialog),("Ctrl+S",self.save_dialog),("Ctrl+I",self.add_dialog),("Escape",self.cancel_work)]:
            QShortcut(QKeySequence(keys),self,activated=slot)
        self.refresh()

    @property
    def fps(self):
        return Fraction(self.fps_combo.currentData())

    def notice(self,message):
        self.status_label.setText(message)
        self.status_label.setToolTip(message)

    def selected_clip(self):
        row=self.table.currentRow()
        return self.clips[row] if 0<=row<len(self.clips) else None

    def preview_reference(self,c):
        ref=next((x for x in self.clips if x.id==self.reference_id),None)
        if c and c.sync_group>0 and ref and c.sync_group!=ref.sync_group:
            members=[x for x in self.clips if x.sync_group==c.sync_group and x.id!=c.id]
            return max(members,key=lambda x:x.duration,default=None)
        return ref

    def refresh(self):
        current=self.selected_clip()
        selected_id=current.id if current else None
        self._refreshing=True
        self.table.setRowCount(len(self.clips))
        self.reference_combo.clear()
        for row,c in enumerate(self.clips):
            self.reference_combo.addItem(c.name,c.id)
            values=["",c.name,f"{int(c.duration//60):02}:{c.duration%60:04.1f}",
                    f"{c.offset:+.4f}" if c.offset is not None else "—",
                    f"{c.score:.2f}" if c.score else "—",c.status]
            for col,text in enumerate(values):
                item=QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable)
                if col==0:
                    item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if c.included else Qt.CheckState.Unchecked)
                if col==1: item.setToolTip(str(c.path))
                if col==5:
                    attention=c.status in {'미일치','오디오 없음','무음','읽기 실패','파일 없음','확인 필요','원본 변경됨'}
                    item.setForeground(QColor('#eea5be' if attention else '#c2a8f5' if c.included else '#e0bd86'))
                    item.setToolTip("\n".join(c.warnings))
                self.table.setItem(row,col,item)
        if self.clips and self.reference_id not in {c.id for c in self.clips}:
            self.reference_id=self.clips[0].id
        self.reference_combo.setCurrentIndex(self.reference_combo.findData(self.reference_id))
        self._refreshing=False
        if self.clips:
            self.table.selectRow(next((i for i,c in enumerate(self.clips) if c.id==selected_id),0))
        included=sum(c.included for c in self.clips)
        tracks=len(set(i.track for i in self.timeline_document.items)) if self.timeline_document else len(self.clips)
        self.count_label.setText(f'{len(self.clips)}개 클립  ·  {tracks}개 트랙  ·  {float(self.fps):g} fps')
        title=self.timeline_document.source_path.name if self.timeline_document else '미디어 직접 입력'
        self.source_label.setText(title)
        self.source_label.setToolTip(str(self.timeline_document.source_path) if self.timeline_document else title)
        confirmed=sum(c.status in {'싱크 완료','기준','수동 보정','그룹 싱크','확인 필요'} for c in self.clips)
        unmatched=sum(c.status in {'미일치','오디오 없음','무음','읽기 실패','파일 없음','확인 필요','원본 변경됨'} for c in self.clips)
        groups=len({c.sync_group for c in self.clips if c.sync_group>0})
        self.result_label.setText(f'정렬 {confirmed}개  ·  {groups}개 그룹  ·  확인 필요 {unmatched}개  ·  포함 {included}개' if confirmed or unmatched else '클립을 클릭하면 상세 정보와 수동 보정을 확인할 수 있습니다.')
        self.page_stack.setCurrentWidget(self.workspace_page if self.clips else self.empty_state)
        if not self.clips:
            self.details_button.setChecked(False)
            self.list_button.setChecked(False)
        offsets=display_offsets(self.clips,self.remove_gaps_check.isChecked())
        view=self.timeline_document.display_clips(self.clips,self.remove_gaps_check.isChecked()) if self.timeline_document else [replace(c,offset=offsets[c.id]) for c in self.clips]
        self.timeline.set_clips(view,self.selected_clip().id if self.selected_clip() else None,[c.id for c in self.clips])
        self.update_inspector()
        self.set_controls()

    def set_controls(self):
        idle=not self.busy
        for w in [self.open_button,self.xml_open_button,self.reset_button,self.reference_combo,self.reload_button,self.remove_gaps_check,self.update_button]:
            w.setEnabled(idle)
        self.browse_button.setEnabled(idle)
        self.direct_button.setEnabled(idle)
        self.add_button.setEnabled(idle and self.timeline_document is None)
        self.folder_button.setEnabled(idle and self.timeline_document is None)
        self.fps_combo.setEnabled(idle and self.timeline_document is None)
        self.relink_button.setEnabled(idle and self.selected_clip() is not None)
        self.save_button.setEnabled(idle and bool(self.clips))
        self.remove_button.setEnabled(idle and bool(self.clips))
        self.sync_button.setEnabled(idle and bool(self.clips))
        ready=idle and any(c.included and c.offset is not None for c in self.clips)
        self.export_button.setEnabled(ready)
        self.csv_button.setEnabled(ready)
        self.table.setEnabled(idle)
        for w in [self.offset_spin,self.minus_button,self.plus_button,self.include_check]:
            w.setEnabled(idle and self.selected_clip() is not None)
        c=self.selected_clip()
        ref=self.preview_reference(c)
        self.preview_button.setEnabled(bool(idle and c and ref and len(c.audio) and len(ref.audio) and c.offset is not None and ref.offset is not None))
        self.cancel_button.setVisible(self.busy)

    def _run(self,fn,done,finished=None):
        if self.busy: return
        self.player.stop()
        self.busy=True
        self.progress.setValue(0)
        self.set_controls()
        self.worker=Worker(fn,self)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(done)
        self.worker.failed.connect(lambda message:self.notice("작업 실패 · "+message))
        self.worker.aborted.connect(lambda:self.notice("취소됨 · 이전 결과를 유지했습니다."))
        self.worker.finished.connect(self._finished)
        if finished is not None:self.worker.finished.connect(finished)
        self.worker.start()

    def check_updates(self):
        if self.busy:return
        from .updates import fetch_latest
        result={}
        self.notice('업데이트 확인 중…')
        self._run(lambda cancel,progress:fetch_latest(),lambda info:result.update(info=info),
                  lambda:self._offer_update(result['info']) if 'info' in result else None)

    def _offer_update(self,info):
        if info is None:
            self.notice(f'최신 버전입니다 · SyncLab {VERSION}')
            QMessageBox.information(self,'업데이트',f'최신 버전입니다.\nSyncLab {VERSION}')
            return
        answer=QMessageBox.question(self,'업데이트',
            f'SyncLab {info.version}을 설치하고 다시 시작할까요?\n현재 버전: {VERSION}\n\n'+info.notes,
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
        if answer!=QMessageBox.StandardButton.Yes or not self.confirm_replace():return
        from .updates import install_update
        result={}
        self._run(lambda cancel,progress:install_update(info,cancel,progress),lambda exe:result.update(exe=exe),
                  lambda:self._restart_updated(result['exe']) if 'exe' in result else None)

    def _restart_updated(self,exe):
        args=[str(self.project_path)] if self.project_path and self.project_path.is_file() else []
        os.environ['PYINSTALLER_RESET_ENVIRONMENT']='1'
        started,_=QProcess.startDetached(str(exe),args,str(Path(exe).parent))
        if not started:
            self.notice('새 버전을 시작하지 못했습니다. 현재 창과 작업은 유지합니다.')
            return
        self.dirty=False
        self.close()

    def _progress(self,value,message):
        self.progress.setValue(value)
        self.notice(message)

    def _finished(self):
        old=self.worker
        self.worker=None
        self.busy=False
        self.set_controls()
        if old: old.deleteLater()
        if self._close_pending:
            self._close_pending=False
            self.close()

    def cancel_work(self):
        if self.worker and self.busy:
            self.worker.requestInterruption()
            self.notice("취소 중… 현재 연산이 끝나면 중단합니다.")

    def add_dialog(self):
        paths,_=QFileDialog.getOpenFileNames(self,"미디어 추가","","미디어 ("+" ".join("*"+x for x in sorted(EXTENSIONS))+");;모든 파일 (*)")
        if paths: self.add_paths(paths)

    def folder_dialog(self):
        folder=QFileDialog.getExistingDirectory(self,"미디어 폴더")
        if folder: self.add_paths([folder])

    def add_paths(self,paths):
        if self.busy: return
        if self.timeline_document is not None:
            self.notice('XML 모드입니다. 새 작업을 시작하면 미디어 파일을 직접 추가할 수 있습니다.')
            return
        existing={c.path.resolve() for c in self.clips}
        files=[]
        for name in paths:
            path=Path(name).resolve()
            candidates=path.rglob("*") if path.is_dir() else [path]
            for candidate in candidates:
                if candidate.is_file() and candidate.suffix.lower() in EXTENSIONS and candidate not in existing:
                    files.append(candidate)
                    existing.add(candidate)
                    if len(existing)>200:
                        self.notice("한 프로젝트에는 최대 200개 파일을 추가할 수 있습니다.")
                        return
        if not files:
            self.notice("새로 추가할 지원 미디어 파일이 없습니다.")
            return
        def work(cancel,progress):
            loaded,errors=[],[]
            for i,path in enumerate(files):
                check_cancel(cancel)
                progress(round(i/len(files)*100),f"읽는 중 {i+1}/{len(files)} · {path.name}")
                try:
                    c=decode_media(path,cancel,lambda p:progress(round((i+p)/len(files)*100),f'오디오 준비 {i+1}/{len(files)} · {path.name} · {p:.0%}'))
                    c.included=True
                    loaded.append(c)
                except (ValueError,OSError) as exc:
                    errors.append(str(exc))
            return loaded,errors
        def done(result):
            loaded,errors=result
            self.clips.extend(loaded)
            self.dirty|=bool(loaded)
            self.refresh()
            self.progress.setValue(100)
            self.notice(f"{len(loaded)}개 추가됨"+(" · "+" / ".join(errors) if errors else " · 기준 클립을 선택하고 자동 싱크를 실행하세요."))
        self._run(work,done)

    def start_sync(self):
        if self.busy or not self.clips: return
        snapshot=[replace(c,warnings=list(c.warnings)) for c in self.clips]
        reference=self.reference_id
        def work(cancel,progress):
            prepared=self._prepare(snapshot,cancel,lambda p,m:progress(round(p*.2),m))
            usable=[c for c in prepared if len(c.audio) and audio_peak(c.audio)>=1e-5]
            ref=next((c for c in usable if c.id==reference),None)
            if ref is None and usable:
                ref=max(usable,key=lambda c:c.duration)
            if ref is None:
                return prepared,None,reference
            result=synchronize(usable,ref.id,lambda p,m:progress(20+round(p*80),m),cancel)
            return prepared,result,ref.id
        def done(payload):
            prepared,result,ref_id=payload
            retain_unmatched(prepared,result.placements if result else {},result.scores if result else {},result.warnings if result else {},ref_id,result.group_ids if result else {})
            self.clips=prepared
            self.reference_id=ref_id
            added=self.timeline_document.separate_overlaps(self.clips) if self.timeline_document else 0
            self.dirty=True
            self.refresh()
            self.progress.setValue(100)
            count=len(result.placements) if result else 0
            groups=len(set(result.group_ids.values())) if result else 0
            self.notice(f"분석 완료 · {groups}개 그룹 / {count}개 정렬 / {len(prepared)-count}개 미일치 뒤로 보존."+(f' 겹치는 클립을 추가 {added}개 트랙에 분리했습니다.' if added else '')+' 별도 그룹 간 실제 시간 관계는 미확인입니다.')
        self._run(work,done)

    def _prepare(self,snapshot,cancel,progress):
        prepared=[]
        for i,c in enumerate(snapshot):
            check_cancel(cancel)
            original=c
            progress(round(100*i/len(snapshot)),f'오디오 준비 {i+1}/{len(snapshot)} · {c.name} · 0%')
            if not c.path.is_file():
                c=replace(c,audio=np.empty(0,dtype=np.float32),features=None,status='파일 없음',sync_group=0)
            elif not len(c.audio) or c.fingerprint != file_fingerprint(c.path):
                try:
                    changed=bool(c.fingerprint and c.fingerprint != file_fingerprint(c.path))
                    fresh=decode_clip(c,cancel,lambda p:progress(round(100*(i+p)/len(snapshot)),f'오디오 준비 {i+1}/{len(snapshot)} · {c.name} · {p:.0%}'))
                    c=replace(fresh,offset=original.offset,included=original.included,
                              score=original.score,status=original.status,
                              excluded=original.excluded,sync_group=original.sync_group,
                              warnings=list(dict.fromkeys(original.warnings+fresh.warnings)))
                    if changed:
                        c.offset,c.score,c.included,c.status=None,0.,False,'원본 변경됨'
                        c.sync_group=0
                        c.warnings.append('분석 이후 원본이 변경되었습니다. 자동 싱크를 다시 실행하세요.')
                except (ValueError,OSError) as exc:
                    c=replace(c,audio=np.empty(0,dtype=np.float32),features=None,status='읽기 실패',sync_group=0,warnings=list(c.warnings)+[str(exc)])
            prepared.append(c)
            progress(round(100*(i+1)/len(snapshot)),f'오디오 준비 {i+1}/{len(snapshot)} · {c.name} · 100%')
        return prepared

    def reload_audio(self):
        if self.busy or not self.clips: return
        snapshot=[replace(c,warnings=list(c.warnings)) for c in self.clips]
        def done(clips):
            self.dirty|=any(a.offset!=b.offset or a.included!=b.included for a,b in zip(self.clips,clips))
            self.clips=clips
            self.refresh()
            self.progress.setValue(100)
            self.notice('파형 읽기 완료 · 저장한 배치와 수동 보정값을 유지했습니다.')
        self._run(lambda cancel,progress:self._prepare(snapshot,cancel,progress),done)

    def load_xml(self,path):
        doc=read_timeline(path)
        self.player.stop()
        self.player.setSource(QUrl())
        self.timeline_document=doc
        self.clips=[replace(c,warnings=list(c.warnings)) for c in doc.clips]
        self.reference_id=max(self.clips,key=lambda c:c.duration).id
        self.project_path=None
        self._refreshing=True
        self.fps_combo.setCurrentIndex(self.fps_combo.findData(str(doc.fps)))
        self.remove_gaps_check.setChecked(False)
        self._refreshing=False
        self.dirty=False
        self.refresh()
        missing=sum(not c.path.is_file() for c in self.clips)
        self.notice(f'XML 열림 · {doc.title} · {float(doc.fps):.3f} fps · {len(doc.items)}개 항목 / {len(set(i.track for i in doc.items))}개 트랙 · 원본 누락 {missing}개')
        self.reload_audio()

    def xml_dialog(self):
        if self.busy or not self.confirm_replace(): return
        path,_=QFileDialog.getOpenFileName(self,'타임라인 XML 열기','','Final Cut Pro 7 XML (*.xml)')
        if path:
            try: self.load_xml(path)
            except (ValueError,OSError) as exc: self.notice(str(exc))

    def new_workspace(self):
        if self.busy or not self.confirm_replace(): return
        self.player.stop()
        self.player.setSource(QUrl())
        self.clips=[]
        self.reference_id=None
        self.timeline_document=None
        self.project_path=None
        self.dirty=False
        self._refreshing=True
        self.remove_gaps_check.setChecked(False)
        self._refreshing=False
        self.progress.setValue(0)
        self.timeline.cursor=0.
        self.set_preview_start(0.)
        self.zoom_slider.setValue(1)
        self.refresh()
        self.notice('새 작업 · XML을 열거나 미디어를 추가하세요.')

    def gaps_changed(self):
        if not self._refreshing:
            self.dirty=True
            self.player.stop()
            self.refresh()

    def relink_dialog(self):
        if self.busy: return
        c=self.selected_clip()
        if c is None: return
        path,_=QFileDialog.getOpenFileName(self,'원본 위치 다시 지정',str(c.path.parent),'미디어 파일 (*)')
        if path:
            try:
                new=Path(path).resolve()
                if not new.is_file(): raise ValueError('원본 파일을 찾을 수 없습니다.')
                old=c.path
                if self.timeline_document: self.timeline_document.relink(old,new)
                for clip in self.clips:
                    if clip.path==old:
                        clip.path=new
                        clip.audio=np.empty(0,dtype=np.float32)
                        clip.features=None
                        clip.fingerprint={}
                        clip.status='원본 재지정'
                        clip.offset,clip.score,clip.included=None,0.,False
                        clip.warnings=['원본 위치를 다시 지정했습니다. 같은 촬영 원본인지 확인하고 자동 싱크를 실행하세요.']
                self.dirty=True
                self.refresh()
                self.reload_audio()
            except (OSError,ValueError) as exc: self.notice(str(exc))

    def update_inspector(self):
        if self._refreshing: return
        c=self.selected_clip()
        self._refreshing=True
        if c:
            self.clip_label.setText(c.name)
            video=f"{c.width} × {c.height} · {float(c.fps):.3f} fps" if c.has_video else "오디오 파일"
            self.metadata_label.setText(f"{video}\n{c.duration:.2f}초 · {c.channels}채널 · 분석 CH {c.channel_used+1}\n{c.status}"+(f' · 그룹 {c.sync_group}' if c.sync_group else ''))
            self.offset_spin.setValue(c.offset or 0.)
            self.offset_spin.setSingleStep(1/float(self.fps))
            self.include_check.setChecked(c.included)
            self.warning_label.setText("\n".join(c.warnings) or ("싱크를 찾지 못하면 시작 시간을 직접 입력해 배치할 수 있습니다." if c.offset is None else "원본은 유지하고 타임라인의 시작 위치만 조정합니다."))
            ref=self.preview_reference(c)
            if ref and ref.offset is not None and c.offset is not None:
                offsets=display_offsets(self.clips,self.remove_gaps_check.isChecked())
                self.preview_start.setValue(max(offsets[ref.id]+ref.audio_start,offsets[c.id]+c.audio_start))
            self.timeline.selected_id=c.id
            self.timeline.update()
        else:
            self.clip_label.setText("클립을 선택하세요")
            self.metadata_label.setText("파일을 추가하면 상세 정보가 표시됩니다.")
            self.warning_label.clear()
            self.include_check.setChecked(False)
        self._refreshing=False
        self.set_controls()

    def apply_offset(self):
        if self.busy or self._refreshing: return
        c=self.selected_clip()
        if c and (c.offset is None or abs(c.offset-self.offset_spin.value())>1e-7):
            c.offset=self.offset_spin.value()
            c.status="수동 보정"
            c.included=c.path.is_file()
            c.excluded=False
            self.dirty=True
            self.player.stop()
            self.refresh()

    def nudge(self,direction):
        self.offset_spin.setValue(self.offset_spin.value()+direction/float(self.fps))
        self.apply_offset()

    def inspector_include(self,value):
        if self._refreshing or self.busy: return
        c=self.selected_clip()
        if c: self._set_included(c,value)

    def toggle_included(self,item):
        if not self._refreshing and not self.busy and item.column()==0:
            self._set_included(self.clips[item.row()],item.checkState()==Qt.CheckState.Checked)

    def _set_included(self,c,value):
        if value and not c.path.is_file():
            self.notice('먼저 원본 파일의 위치를 다시 지정하세요.')
        else:
            c.included=value
            c.excluded=not value
            self.dirty=True
        self.refresh()

    def change_reference(self,index):
        if self._refreshing or self.busy or index<0: return
        self.reference_id=self.reference_combo.itemData(index)
        ref=next(c for c in self.clips if c.id==self.reference_id)
        if ref.offset is not None:
            shift=ref.offset
            for c in self.clips:
                if c.offset is not None: c.offset-=shift
                if c.id==ref.id: c.status='기준'
                elif c.status=='기준': c.status='싱크 완료'
        else:
            for c in self.clips:
                c.offset=None
                c.included=False
                c.score=0.
                c.status="대기"
                c.sync_group=0
            self.notice("새 기준으로 자동 싱크를 다시 실행하세요.")
        self.dirty=True
        self.player.stop()
        self.refresh()

    def remove_selected(self):
        if self.busy: return
        c=self.selected_clip()
        if c:
            self.clips.remove(c)
            if c.id==self.reference_id:
                self.reference_id=None
                if self.clips:
                    ref=next((x for x in self.clips if x.offset is not None),self.clips[0])
                    self.reference_id=ref.id
                    shift=ref.offset or 0.
                    for x in self.clips:
                        if x.offset is not None: x.offset-=shift
                    if ref.offset is not None: ref.status='기준'
            self.player.stop()
            self.dirty=True
            self.refresh()

    def fps_changed(self):
        if not self._refreshing:
            self.dirty=True
            self.update_inspector()

    def set_preview_start(self,time):
        self.preview_start.setValue(time)
        self._set_timecode(time)

    def _set_timecode(self,time):
        total=max(0,round(time*float(self.fps)))
        nominal=round(float(self.fps))
        seconds,frame=divmod(total,nominal)
        minutes,second=divmod(seconds,60)
        hour,minute=divmod(minutes,60)
        self.timecode_label.setText(f'{hour:02}:{minute:02}:{second:02}:{frame:02}')

    def select_timeline_clip(self,row):
        self.table.selectRow(row)
        self.details_button.setChecked(True)

    def show_guide(self):
        QMessageBox.information(self,'프리미어에서 사용하기',
            '1. 프리미어 시퀀스에 영상과 오디오를 소스별 트랙으로 배치합니다.\n'
            '2. 파일 → 내보내기 → Final Cut Pro XML을 선택합니다.\n'
            '3. SyncLab에서 XML을 열고 자동 싱크를 실행합니다.\n'
            '4. 타임라인에서 결과를 확인하고 XML 저장을 누릅니다.\n'
            '5. 프리미어에서 결과 XML을 가져오면 새 시퀀스가 생깁니다.\n\n'
            '클립을 클릭하면 수동 보정과 비교 듣기를 사용할 수 있습니다.\n'
            '원본 영상·오디오는 기존 위치에 그대로 둡니다.')

    def zoom_timeline(self,value):
        self.timeline.setMinimumWidth(0 if value==1 else max(600,self.scroll.viewport().width())*value)
        self.timeline.update()

    def preview(self):
        c=self.selected_clip()
        ref=self.preview_reference(c)
        if not c or not ref: return
        try:
            self.player.stop()
            self.player.setSource(QUrl())
            self._preview_count+=1
            path=Path(self._preview_dir.name)/f"comparison-{self._preview_count}.wav"
            self.preview_origin=self.preview_start.value()
            offsets=display_offsets(self.clips,self.remove_gaps_check.isChecked())
            render_preview(replace(ref,offset=offsets[ref.id]),replace(c,offset=offsets[c.id]),path,start=self.preview_origin,duration=15.)
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.player.play()
            self.notice(f'비교 청취 · 왼쪽 {ref.name} / 오른쪽 {c.name} · 분석용 4 kHz 오디오입니다.')
        except (ValueError,OSError) as exc:
            self.notice(str(exc))

    def _playhead(self,ms):
        self.timeline.cursor=self.preview_origin+ms/1000
        self._set_timecode(self.timeline.cursor)
        self.timeline.update()

    def confirm_replace(self):
        if not self.dirty: return True
        answer=QMessageBox.question(self,"저장하지 않은 변경","변경 사항을 저장할까요?",
            QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
        if answer==QMessageBox.StandardButton.Save: return self.save_dialog()
        return answer==QMessageBox.StandardButton.Discard

    def save_to(self,path):
        save_project(self.clips,self.reference_id,self.fps,path,self.timeline_document,self.remove_gaps_check.isChecked())
        self.project_path=Path(path)
        self.dirty=False
        self.notice("프로젝트 저장됨 · "+str(path))

    def save_dialog(self):
        if self.busy or not self.clips: return False
        path,_=QFileDialog.getSaveFileName(self,"프로젝트 저장",str(self.project_path or "Untitled.synclab"),"SyncLab 프로젝트 (*.synclab)")
        if not path: return False
        try:
            self.save_to(path)
            return True
        except (ValueError,OSError) as exc:
            self.notice(str(exc))
            return False

    def load_from(self,path):
        clips,ref,fps=load_project(path)
        timeline,gaps=load_project_timeline(path)
        if timeline and not {c.id for c in clips}.issubset({c.id for c in timeline.clips}):
            raise ValueError('저장된 XML과 클립 ID가 일치하지 않습니다.')
        if timeline and timeline.fps != fps:
            raise ValueError('저장된 XML과 시퀀스 FPS가 다릅니다.')
        self.player.stop()
        self.player.setSource(QUrl())
        self.clips,self.reference_id=clips,ref
        self.timeline_document=timeline
        self._refreshing=True
        self.fps_combo.setCurrentIndex(self.fps_combo.findData(str(fps)))
        self.remove_gaps_check.setChecked(gaps)
        self._refreshing=False
        self.project_path=Path(path)
        self.dirty=False
        self.progress.setValue(0)
        self.refresh()
        self.notice('프로젝트 열림 · 저장한 배치를 유지하며 파형을 읽습니다.')
        self.reload_audio()

    def open_dialog(self):
        if self.busy or not self.confirm_replace(): return
        path,_=QFileDialog.getOpenFileName(self,"프로젝트 열기","","SyncLab 프로젝트 (*.synclab)")
        if path:
            try: self.load_from(path)
            except (OSError,ValueError) as exc: self.notice(str(exc))

    def export_to(self,path):
        if self.timeline_document:
            self.timeline_document.write(path,self.clips,self.remove_gaps_check.isChecked())
        else:
            offsets=display_offsets(self.clips,self.remove_gaps_check.isChecked())
            export_xml([replace(c,offset=offsets[c.id]) for c in self.clips],path,self.fps,Path(path).stem)
        self.notice('XML 저장됨 · '+str(path)+' · 프리미어에서 파일 → 가져오기로 열어주세요.')

    def export_dialog(self):
        path,_=QFileDialog.getSaveFileName(self,"프리미어용 XML 저장","Synced.xml","Final Cut Pro 7 XML (*.xml)")
        if path:
            try: self.export_to(path)
            except (OSError,ValueError) as exc: self.notice(str(exc))

    def csv_dialog(self):
        path,_=QFileDialog.getSaveFileName(self,"싱크 보고서 저장","Sync-report.csv","CSV (*.csv)")
        if path:
            try:
                self.csv_to(path)
                self.notice("CSV 저장됨 · "+path)
            except (OSError,ValueError) as exc: self.notice(str(exc))

    def csv_to(self,path):
        target=Path(path).resolve()
        if self.timeline_document:
            source=self.timeline_document.source_path
            if target==source or (target.exists() and source.exists() and target.samefile(source)):
                raise ValueError('입력 XML에 CSV를 덮어쓸 수 없습니다.')
        return export_csv(self.clips,target)

    def dragEnterEvent(self,event):
        if not self.busy and event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self,event):
        if not self.busy:
            paths=[url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if len(paths)==1 and Path(paths[0]).suffix.lower() in {'.xml','.synclab'}:
                if self.confirm_replace():
                    try:
                        if Path(paths[0]).suffix.lower()=='.xml': self.load_xml(paths[0])
                        else: self.load_from(paths[0])
                    except (OSError,ValueError) as exc: self.notice(str(exc))
            else: self.add_paths(paths)
            event.acceptProposedAction()

    def closeEvent(self,event):
        if self.busy:
            self._close_pending=True
            self.cancel_work()
            event.ignore()
            return
        if not self.confirm_replace():
            event.ignore()
            return
        self.player.stop()
        self.player.setSource(QUrl())
        try: self._preview_dir.cleanup()
        except PermissionError: pass
        event.accept()
