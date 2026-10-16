import csv
from fractions import Fraction
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
import pytest
from synclab.models import Clip
from synclab.export import export_xml, export_csv


def media(tmp_path, name, offset, fps=Fraction(25)):
    path = tmp_path/name
    path.touch()
    return Clip(path, 10., fps=fps, width=1920, height=1080, channels=2, offset=offset, included=True)


def test_xml_negative_offsets_file_uri_and_stereo_links(tmp_path):
    a = media(tmp_path, "카메라 A.mov", -2.)
    b = media(tmp_path, "camera B.mov", 3.)
    unresolved = media(tmp_path, "unmatched.mov", None)
    unresolved.included = False
    path = tmp_path/"sync.xml"
    export_xml([a,b,unresolved], path, Fraction(25))
    root = ET.parse(path).getroot()
    assert root.tag == "xmeml" and root.attrib["version"] == "5"
    assert root.findtext("sequence/duration") == "375"
    clips = root.findall("./sequence/media/video/track/clipitem")
    assert [c.findtext("start") for c in clips] == ["0","125"]
    assert [c.findtext("end") for c in clips] == ["250","375"]
    assert len(root.findall("./sequence/media/audio/track/clipitem")) == 4
    assert len(clips[0].findall("link")) == 3
    uri = clips[0].findtext("file/pathurl")
    assert urlparse(uri).netloc == 'localhost'
    assert "%20" in uri and "카메라" in unquote(uri)
    assert all("unmatched" not in (c.text or "") for c in root.iter())
    ids = {c.attrib["id"] for c in root.iter("clipitem")}
    assert all(c.text in ids for c in root.iter("linkclipref"))


def test_fractional_fps_mixed_source_and_subframe_rounding(tmp_path):
    a = media(tmp_path, "a.mov", 0., Fraction(25))
    b = media(tmp_path, "b.mov", 1.001, Fraction(30000,1001))
    path = tmp_path/"sync.xml"
    export_xml([a,b], path, Fraction(30000,1001))
    root = ET.parse(path).getroot()
    assert root.findtext("sequence/rate/timebase") == "30"
    assert root.findtext("sequence/rate/ntsc") == "TRUE"
    items = root.findall("./sequence/media/video/track/clipitem")
    assert items[0].findtext("out") == "250"
    assert items[0].findtext("end") == "300"
    assert items[1].findtext("start") == "30"


def test_invalid_inclusions_missing_source_and_original_overwrite_rejected(tmp_path):
    a = media(tmp_path, "source.mov", None)
    for offset in [None, float("nan"), float("inf")]:
        a.offset = offset
        with pytest.raises(ValueError):
            export_xml([a], tmp_path/"out.xml", Fraction(25))
    a.offset = 0.
    with pytest.raises(ValueError):
        export_xml([a], a.path, Fraction(25))
    a.path.unlink()
    with pytest.raises(ValueError):
        export_xml([a], tmp_path/"out.xml", Fraction(25))


def test_csv_retains_seconds_and_only_exports_included_clips(tmp_path):
    a = media(tmp_path, "=formula.mov", -1.237)
    b = media(tmp_path, "b.mov", 0.)
    b.included = False
    path = tmp_path/"report.csv"
    export_csv([a,b], path)
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert float(rows[0]["offset_seconds"]) == -1.237
    assert rows[0]["file"].startswith("'=")
