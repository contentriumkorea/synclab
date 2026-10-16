"""Conservative two-stage audio matching and reference-connected alignment."""
import heapq
from itertools import combinations

import numpy as np
from scipy import signal

from .models import Cancelled, Clip, PairMatch, SAMPLE_RATE, SyncResult

HOP = 64
FEATURE_RATE = SAMPLE_RATE / HOP
FEATURE_CHUNK_FRAMES = 4096


def check_cancel(cancelled):
    if cancelled():
        raise Cancelled("작업이 취소되었습니다.")


def features(clip: Clip, cancelled=lambda: False):
    if clip.features is not None:
        return clip.features
    x = clip.audio
    if len(x) < SAMPLE_RATE * 2 or np.max(np.abs(x), initial=0) < 1e-5:
        return None
    bands = [(80, 200), (200, 400), (400, 650), (650, 1000), (1000, 1450), (1450, 1950)]
    count = 1+(len(x)-256)//HOP
    energy = np.empty((len(bands), count), dtype=np.float32)
    for start in range(0, count, FEATURE_CHUNK_FRAMES):
        check_cancel(cancelled)
        stop = min(count, start+FEATURE_CHUNK_FRAMES)
        f, _, z = signal.stft(x[start*HOP:(stop-1)*HOP+256], fs=SAMPLE_RATE,
                             nperseg=256, noverlap=256-HOP, boundary=None, padded=False)
        power = np.abs(z)**2
        energy[:, start:stop] = [power[(f >= lo) & (f < hi)].mean(axis=0) for lo, hi in bands]
    # Constant tones and silence have no usable temporal fingerprint.
    variation = np.std(energy, axis=1) / (np.mean(energy, axis=1) + 1e-12)
    if np.count_nonzero(variation > .04) < 3:
        return None
    log = np.log(energy + np.maximum(np.mean(energy, axis=1, keepdims=True)*.01, 1e-12))
    log -= np.mean(log, axis=1, keepdims=True)
    log /= np.maximum(np.std(log, axis=1, keepdims=True), .1)
    clip.features = log.astype(np.float32)
    return clip.features


def _overlap_sums(values, starts, ends):
    cs = np.concatenate(([0.0], np.cumsum(values, dtype=np.float64)))
    return cs[ends] - cs[starts]


def _candidates(a, b, cancelled=lambda: False):
    fa, fb = features(a, cancelled), features(b, cancelled)
    if fa is None or fb is None:
        return []
    na, nb = fa.shape[1], fb.shape[1]
    lags = signal.correlation_lags(na, nb)
    aa, ab = np.maximum(0, lags), np.minimum(na, lags + nb)
    ba, bb = aa-lags, ab-lags
    overlap = ab-aa
    num = sum(signal.correlate(x, y, method="fft") for x, y in zip(fa, fb))
    ea = _overlap_sums(np.sum(fa**2, axis=0), aa, ab)
    eb = _overlap_sums(np.sum(fb**2, axis=0), ba, bb)
    score = num / np.sqrt(np.maximum(ea*eb, 1e-18))
    score[overlap < max(2*FEATURE_RATE, min(na, nb)*.15)] = -1
    peaks, _ = signal.find_peaks(score, distance=round(.4*FEATURE_RATE))
    peaks = sorted(peaks, key=lambda i: score[i], reverse=True)[:5]
    return [(float(lags[i]/FEATURE_RATE), float(score[i])) for i in peaks if score[i] > .2]


def _refine(a, b, rough, cancelled):
    # Several longer windows survive local interference and different room/mic sound.
    sr = SAMPLE_RATE
    lo, hi = max(0.0, -rough), min(len(b.audio)/sr, len(a.audio)/sr-rough)
    if hi-lo < 2:
        return None
    window, radius = min(3., (hi-lo)/3), .3
    offsets, strengths, times = [], [], []
    for fraction in np.linspace(.1,.9,9):
        check_cancel(cancelled)
        tb = lo + (hi-lo-window)*fraction
        ib = round(tb*sr)
        n = round(window*sr)
        left = max(0, round((tb+rough-radius)*sr))
        right = min(len(a.audio), round((tb+rough+window+radius)*sr))
        x = a.audio[left:right].astype(np.float64)
        y = b.audio[ib:ib+n].astype(np.float64)
        if len(x) < len(y) or len(y) < sr*.25:
            continue
        y -= y.mean()
        ey = np.dot(y, y)
        if ey < 1e-9:
            continue
        corr = signal.correlate(x, y, mode="valid", method="fft")
        cs = np.concatenate(([0.], np.cumsum(x)))
        cs2 = np.concatenate(([0.], np.cumsum(x*x)))
        ex = cs2[n:] - cs2[:-n] - (cs[n:]-cs[:-n])**2/n
        scores = np.abs(corr) / np.sqrt(np.maximum(ex*ey, 1e-18))
        index = int(np.argmax(scores))
        if scores[index] >= .2:
            offsets.append((left+index-ib)/sr)
            strengths.append(float(min(scores[index], 1.)))
            times.append(tb)
    if len(offsets) < 3:
        return None
    offsets,times,strengths=np.array(offsets),np.array(times),np.array(strengths)
    best=None
    # Fit a consensus instead of rejecting a take because of a single bad window.
    for i in range(len(offsets)):
        check_cancel(cancelled)
        for j in range(i+1,len(offsets)):
            slope=(offsets[j]-offsets[i])/(times[j]-times[i])
            if abs(slope)>.005:continue
            predicted=offsets[i]+slope*(times-times[i])
            mask=np.abs(offsets-predicted)<=.015
            rank=(int(mask.sum()),float(np.ptp(times[mask])),float(strengths[mask].sum()))
            if best is None or rank>best[0]:best=(rank,mask)
    if best is None:return None
    mask=best[1]
    if mask.sum()<max(3,int(np.ceil(.7*len(offsets)))) or np.ptp(times[mask])<.4*(hi-lo-window):
        return None
    slope,intercept=np.polyfit(times[mask],offsets[mask],1)
    residual=np.abs(offsets-(slope*times+intercept))
    if abs(slope)>.005 or residual[mask].max()>.02:return None
    drift_ms = float(slope*(hi-lo)*1000)
    jitter_ms=float(residual.max()*1000)
    # Align near the overlap midpoint without changing playback speed.
    return float(np.median(offsets[mask])),float(np.median(strengths[mask])),hi-lo,drift_ms,jitter_ms


def match_pair(a: Clip, b: Clip, cancelled=lambda: False):
    check_cancel(cancelled)
    matches = []
    for rough, coarse in _candidates(a, b, cancelled):
        refined = _refine(a, b, rough, cancelled)
        if refined is None:
            continue
        offset, fine, overlap, drift, jitter = refined
        score = .7*fine + .3*max(0, coarse)
        if score >= .4:
            matches.append(PairMatch(a.id, b.id, offset+a.audio_start-b.audio_start,
                                     min(score, 1.), overlap, drift,jitter))
    if not matches:
        return None
    matches.sort(key=lambda m: m.score, reverse=True)
    best = matches[0]
    if any(abs(m.offset-best.offset) > .1 and m.score >= best.score*.9 for m in matches[1:]):
        return None
    return best


def synchronize(clips, reference_id, progress=lambda p, m: None, cancelled=lambda: False):
    check_cancel(cancelled)
    if reference_id not in {c.id for c in clips}:
        raise ValueError("기준 클립을 선택해 주세요.")
    pairs = list(combinations(clips, 2))
    matches = []
    for i, (a, b) in enumerate(pairs):
        check_cancel(cancelled)
        progress(i/max(1, len(pairs)), f"{a.name} ↔ {b.name}")
        match = match_pair(a, b, cancelled)
        if match:
            matches.append(match)
    edges = {c.id: [] for c in clips}
    for m in matches:
        edges[m.a].append((m.b,m.offset,m.score,m.drift_ms,m.jitter_ms))
        edges[m.b].append((m.a,-m.offset,m.score,-m.drift_ms,m.jitter_ms))
    placements, scores, warnings = {reference_id: 0.0}, {reference_id: 1.0}, {}
    group_ids={reference_id:1}
    queue = []

    def push(node):
        for other, delta, score, drift, jitter in edges[node]:
            if other not in placements:
                # Prefer stable recordings as bridges over sources with a time jump.
                quality=score*(.7 if jitter>40 else 1.)
                heapq.heappush(queue,(-min(scores[node],quality),node,other,delta,drift,jitter))
    def expand(anchor,group):
        push(anchor)
        while queue:
            check_cancel(cancelled)
            weight,parent,node,delta,drift,jitter=heapq.heappop(queue)
            if node in placements:continue
            placements[node]=placements[parent]+delta
            scores[node]=-weight;group_ids[node]=group
            inherited=list(warnings.get(parent,[]))
            if abs(drift)>10:
                inherited.append(f'시간 드리프트 약 {abs(drift):.0f} ms — 구간별 싱크를 확인하세요.')
            if jitter>10:
                inherited.append(f'구간별 오프셋 편차 약 {jitter:.0f} ms — 간섭 또는 녹음 중 시간 불연속 가능, 구간별 수동 확인 필요')
            if inherited:warnings[node]=inherited
            push(node)
    expand(reference_id,1)
    # Every accepted connected component can be aligned internally, even when it
    # shares no audio with the chosen reference. Its absolute placement is unknown.
    for c in sorted(clips,key=lambda c:(-c.duration,c.id)):
        if c.id in placements or not edges[c.id]:continue
        group=max(group_ids.values())+1
        tail=max(placements[x.id]+x.duration for x in clips if x.id in placements)+1.
        placements[c.id]=0.;scores[c.id]=1.;group_ids[c.id]=group
        expand(c.id,group)
        members=[key for key,value in group_ids.items() if value==group]
        origin=min(placements[key] for key in members)
        for key in members:placements[key]+=tail-origin
    for m in matches:
        if m.a in placements and m.b in placements:
            if m.jitter_ms>40:
                for node,other in [(m.a,m.b),(m.b,m.a)]:
                    other_name=next(c.name for c in clips if c.id==other)
                    warnings.setdefault(node,[]).append(f'{other_name}와 구간별 오프셋 편차 약 {m.jitter_ms:.0f} ms — 녹음 중 시간 불연속 가능, 구간별 수동 확인 필요')
            if abs(placements[m.b]-placements[m.a]-m.offset) > .04:
                for node in [m.a, m.b]:
                    warnings.setdefault(node, []).append("다른 매칭 경로와 40 ms 이상 차이 — 수동 확인 필요")
    warnings={key:list(dict.fromkeys(value)) for key,value in warnings.items()}
    progress(1., "동기화 분석 완료")
    return SyncResult(placements,scores,matches,warnings,group_ids)
