"""Compact editor timeline; source tracks and linked clip selection are retained."""
import math
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QFont
from PySide6.QtWidgets import QWidget
from .models import SAMPLE_RATE

COLORS=['#ac90f2','#a6b9d5','#dfba7e','#de8da7']
ATTENTION={'미일치','오디오 없음','무음','읽기 실패','파일 없음','확인 필요','원본 변경됨'}


class Timeline(QWidget):
    selected=Signal(int)
    seek=Signal(float)
    LABEL=132
    ROW=52
    TOP=40

    def __init__(self):
        super().__init__()
        self.clips=[]
        self.selected_id=None
        self.cursor=0.
        self.peaks={}
        self.track_keys=[]
        self.selection_ids=[]
        self.setMinimumHeight(220)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('클립 클릭: 상세 정보 · 눈금 클릭: 비교 재생 위치')

    def set_clips(self,clips,selected_id=None,selection_ids=None):
        self.clips=clips
        self.selected_id=selected_id
        self.selection_ids=selection_ids or [c.id for c in clips]
        self.track_keys=list(dict.fromkeys(c.track or c.id for c in clips))
        self.setMinimumHeight(max(220,self.TOP+len(self.track_keys)*self.ROW+8))
        alive={(c.id,c.track) for c in clips}
        self.peaks={k:v for k,v in self.peaks.items() if k in alive}
        self.update()

    def bounds(self):
        placed=[c for c in self.clips if c.offset is not None]
        lo=min([0.]+[c.offset for c in placed])
        hi=max([10.]+[(c.offset or 0)+c.duration for c in self.clips])
        return lo,hi+max(1.,(hi-lo)*.025)

    def point_time(self,x):
        lo,hi=self.bounds()
        return lo+(x-self.LABEL)/max(1,self.width()-self.LABEL-20)*(hi-lo)

    def time_x(self,time):
        lo,hi=self.bounds()
        return self.LABEL+(time-lo)/max(.001,hi-lo)*(self.width()-self.LABEL-20)

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#151519'))
        font=QFont('Malgun Gothic');font.setPixelSize(11);p.setFont(font)
        p.fillRect(QRectF(0,0,self.width(),34),QColor('#222128'))
        p.setPen(QColor('#aba5b6'))
        p.drawText(QRectF(18,0,self.LABEL-24,34),Qt.AlignmentFlag.AlignVCenter,'트랙')
        if not self.clips:
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'타임라인 XML을 불러오세요')
            p.end();return
        for i,key in enumerate(self.track_keys):
            top=self.TOP+i*self.ROW
            p.fillRect(QRectF(self.LABEL,top,self.width()-self.LABEL,self.ROW),QColor('#19181e' if i%2 else '#16151a'))
            members=[c for c in self.clips if (c.track or c.id)==key]
            selected=any(c.id==self.selected_id for c in members)
            p.fillRect(QRectF(0,top,self.LABEL,self.ROW),QColor('#30263e' if selected else '#212027'))
            p.setPen(QPen(QColor('#34303c'),1))
            p.drawLine(QPointF(0,top+self.ROW),QPointF(self.width(),top+self.ROW))
            p.setPen(QColor('#ded6ed' if selected else '#bdb5cc'))
            p.drawText(QRectF(16,top+3,100,22),Qt.AlignmentFlag.AlignVCenter,members[0].track or f'소스 {i+1:02}')
            p.setPen(QColor('#a09aa9'))
            kind='비디오' if members[0].track.startswith('V') else '오디오' if members[0].track.startswith('A') else '미디어'
            p.drawText(QRectF(16,top+24,100,19),Qt.AlignmentFlag.AlignVCenter,kind+f' · {len(members)}개')
        lo,hi=self.bounds()
        target=(hi-lo)/max(2,(self.width()-self.LABEL)/120)
        step=next((x for x in [.1,.25,.5,1,2,5,10,15,30,60,120,300,600,1800,3600] if x>=target),7200)
        for i in range(math.floor(lo/step),math.ceil(hi/step)+1):
            t=i*step;x=self.time_x(t)
            if x<self.LABEL:continue
            p.setPen(QPen(QColor('#302c38'),1))
            p.drawLine(QPointF(x,34),QPointF(x,self.height()))
            p.setPen(QColor('#aaa2b6'))
            text=f'{t:.1f}s' if step<1 else f'{int(t)//60:02}:{int(t)%60:02}'
            p.drawText(QRectF(x+5,0,85,34),Qt.AlignmentFlag.AlignVCenter,text)
        for c in self.clips:
            top=self.TOP+self.track_keys.index(c.track or c.id)*self.ROW+5
            color=QColor('#de8da7' if c.status in ATTENTION else '#a6b9d5' if c.status=='기준' else '#dfba7e' if c.status=='수동 보정' else '#ac90f2')
            fill=QColor('#4d2c3b' if c.status in ATTENTION else '#303b4b' if c.status=='기준' else '#4a3d2b' if c.status=='수동 보정' else '#3b2c50')
            if c.offset is None:fill=QColor('#2a2533')
            if not c.included:fill.setAlpha(90)
            x0=self.time_x(c.offset or 0);x1=self.time_x((c.offset or 0)+c.duration)
            rect=QRectF(x0,top,max(3,x1-x0),40)
            p.setBrush(fill)
            p.setPen(QPen(QColor('#dfcbff') if c.id==self.selected_id else color,1.5 if c.id==self.selected_id else .6))
            p.drawRoundedRect(rect,3,3)
            p.save();p.setClipRect(rect.adjusted(1,1,-1,-1))
            if len(c.audio):
                signature=(id(c.audio),len(c.audio));cache_key=(c.id,c.track)
                cached=self.peaks.get(cache_key)
                if not cached or cached[0]!=signature:
                    stride=max(1,math.ceil(len(c.audio)/1800))
                    samples=np.array([np.max(np.abs(c.audio[j:j+stride]),initial=0) for j in range(0,len(c.audio),stride)])
                    samples/=max(float(samples.max()),1e-7)
                    self.peaks[cache_key]=(signature,samples)
                samples=self.peaks[cache_key][1]
                audio_x=self.time_x((c.offset or 0)+c.audio_start)
                width=(len(c.audio)/SAMPLE_RATE)/(hi-lo)*(self.width()-self.LABEL-20)
                upper=[QPointF(audio_x+j/max(1,len(samples)-1)*width,top+28-v*10) for j,v in enumerate(samples)]
                lower=[QPointF(audio_x+j/max(1,len(samples)-1)*width,top+28+v*10) for j,v in reversed(list(enumerate(samples)))]
                wave=QColor(color);wave.setAlpha(170 if c.included else 55)
                p.setBrush(wave);p.setPen(Qt.PenStyle.NoPen)
                p.drawPolygon(QPolygonF(upper+lower))
            p.setPen(QColor('#eee8f7' if c.included else '#96909e'))
            name=(f'G{c.sync_group} · ' if c.sync_group else '')+c.name+('  ·  '+c.status if x1-x0>235 else '')
            p.drawText(QRectF(x0+7,top,max(1,x1-x0-14),17),Qt.AlignmentFlag.AlignVCenter,p.fontMetrics().elidedText(name,Qt.TextElideMode.ElideRight,max(1,int(x1-x0-14))))
            p.restore()
        p.setPen(QPen(QColor('#4c435b'),1))
        p.drawLine(QPointF(self.LABEL,0),QPointF(self.LABEL,self.height()))
        x=self.time_x(self.cursor)
        if x>=self.LABEL:
            p.setPen(QPen(QColor('#e8d9ff'),1))
            p.drawLine(QPointF(x,30),QPointF(x,self.height()))
            p.setBrush(QColor('#e8d9ff'))
            p.drawPolygon(QPolygonF([QPointF(x-4,27),QPointF(x+4,27),QPointF(x,34)]))
        p.end()

    def mousePressEvent(self,event):
        row=int((event.position().y()-self.TOP)//self.ROW)
        if 0<=row<len(self.track_keys):
            candidates=[c for c in self.clips if (c.track or c.id)==self.track_keys[row]]
            time=self.point_time(event.position().x())
            chosen=next((c for c in reversed(candidates) if (c.offset or 0)<=time<=(c.offset or 0)+c.duration),candidates[0])
            if chosen.id in self.selection_ids:self.selected.emit(self.selection_ids.index(chosen.id))
        if event.position().x()>=self.LABEL:
            self.cursor=self.point_time(event.position().x())
            self.seek.emit(self.cursor)
            self.update()
