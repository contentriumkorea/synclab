import numpy as np
import pytest
from scipy import signal
from conftest import sound, clip
from synclab.engine import match_pair, synchronize
from synclab.models import SAMPLE_RATE as SR, Cancelled


@pytest.mark.parametrize("start", [3.217, -4.081])
def test_signed_offset_survives_gain_noise_and_polarity(start):
    source = sound()
    ia, ib = (0, round(start * SR)) if start > 0 else (round(-start * SR), 0)
    a = clip(source[ia:ia + 20 * SR], "a")
    data = source[ib:ib + 20 * SR]
    b = clip(-data * .45 + np.random.default_rng(9).normal(0, .015, len(data)), "b")
    result = match_pair(a, b)
    assert result is not None
    assert result.offset == pytest.approx(start, abs=.002)
    assert result.score > .5


def test_partial_overlap_links_through_a_bridge():
    data = sound(50)
    clips = [clip(data[:20*SR], "a"), clip(data[12*SR:32*SR], "b"), clip(data[27*SR:45*SR], "c")]
    result = synchronize(clips, "a")
    assert result.placements == pytest.approx({"a": 0, "b": 12, "c": 27}, abs=.003)


def test_unrelated_silence_and_periodic_signals_are_not_matches():
    a = clip(sound(15), "a")
    t = np.arange(15*SR) / SR
    for data in [sound(15, 910), np.zeros(15*SR), np.sin(2*np.pi*440*t)]:
        assert match_pair(a, clip(data, "b")) is None
    assert match_pair(clip(np.sin(2*np.pi*440*t), "a"), clip(np.sin(2*np.pi*440*t), "b")) is None


def test_repeated_identical_events_are_ambiguous():
    pattern = sound(6)
    assert match_pair(clip(np.tile(pattern, 5), "a"), clip(pattern, "b")) is None


def test_audio_stream_start_offsets_are_included():
    source = sound(20)
    a = clip(source[:12*SR], "a")
    b = clip(source[3*SR:15*SR], "b")
    a.audio_start, b.audio_start = .2, .5
    assert match_pair(a, b).offset == pytest.approx(2.7, abs=.003)


def test_disconnected_clips_not_placed_and_cancel_honored():
    a, b = clip(sound(10), "a"), clip(sound(10, 1), "b")
    assert synchronize([a, b], "a").placements == {"a": 0.0}
    with pytest.raises(Cancelled):
        synchronize([a, b], "a", cancelled=lambda: True)


def test_reference_disconnected_matching_cluster_is_aligned_before_singletons():
    main=sound(35,1);other=sound(45,2)
    clips=[clip(main[:25*SR],'ref'),clip(main[4*SR:29*SR],'camera'),
           clip(other[:30*SR],'other-a'),clip(other[7*SR:37*SR],'other-b'),
           clip(sound(8,3),'unmatched')]
    result=synchronize(clips,'ref')
    assert set(result.placements)=={'ref','camera','other-a','other-b'}
    assert result.placements['other-b']-result.placements['other-a']==pytest.approx(7,abs=.003)
    assert result.group_ids['ref']==result.group_ids['camera']==1
    assert result.group_ids['other-a']==result.group_ids['other-b']==2
    assert min(result.placements[k] for k in ['other-a','other-b'])>=29
    assert 'unmatched' not in result.group_ids


def test_drift_is_reported_instead_of_silently_stretching():
    source = sound(70)
    a = clip(source, "a")
    # Device b accumulates ~42 ms difference over 70 seconds.
    b = clip(signal.resample_poly(source, 10006, 10000), "b")
    result = match_pair(a, b)
    assert result is not None
    assert abs(result.drift_ms) > 20


def test_local_interference_does_not_reject_other_consistent_windows():
    source=sound(80)
    a=clip(source,'a')
    bdata=source[round(3.217*SR):round(63.217*SR)].copy()
    # Different mic/echo interference spoils one probe window, not the whole take.
    bdata[5*SR:9*SR]=sound(4,290)*.5
    b=clip(bdata,'b')
    result=match_pair(a,b)
    assert result is not None
    assert result.offset==pytest.approx(3.217,abs=.003)


def test_in_recording_time_jump_is_explicitly_reported():
    source=sound(80)
    bdata=source[3*SR:63*SR].copy()
    bdata[49*SR:]=source[round(52.2*SR):round(63.2*SR)]
    result=match_pair(clip(source,'a'),clip(bdata,'b'))
    assert result is not None
    assert result.offset==pytest.approx(3.,abs=.003)
    assert result.jitter_ms>100
    synced=synchronize([clip(source,'a'),clip(bdata,'b')],'a')
    assert any('편차' in w for w in synced.warnings['b'])
    # A clean short bridge must not hide a discontinuity seen against the reference.
    bridged=synchronize([clip(source,'a'),clip(bdata,'b'),clip(source[3*SR:23*SR],'bridge')],'a')
    assert any('편차' in w for w in bridged.warnings['b'])


def test_same_envelope_unrelated_audio_is_still_rejected():
    rng=np.random.default_rng(191)
    env=np.repeat(rng.uniform(.03,1,200),int(.25*SR))
    a=clip(rng.normal(size=len(env))*env,'a')
    b=clip(rng.normal(size=len(env))*env,'b')
    assert match_pair(a,b) is None
