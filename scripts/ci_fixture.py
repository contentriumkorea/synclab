"""Generated, non-private recordings for native package integration checks."""
from pathlib import Path
from fractions import Fraction
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from conftest import sound
from test_media import write_wav
from synclab.models import Clip
from synclab.export import export_xml

folder=ROOT/'validation/ci-fixture';folder.mkdir(parents=True,exist_ok=True)
a,b=sound(80,1),sound(45,2)
names=['reference.wav','camera.wav','group-a.wav','group-b.wav','alone.wav']
data=[a[:60*4000],a[4*4000:34*4000],b[:30*4000],b[7*4000:37*4000],sound(8,3)]
clips=[]
for name,x in zip(names,data):
    path=folder/name;write_wav(path,x)
    clips.append(Clip(path,len(x)/4000,channels=1,included=True,offset=0))
export_xml(clips,folder/'Groups.xml',Fraction(25),'Independent groups fixture')
(folder/'Groups.expected.json').write_text(json.dumps({'offsets':dict(zip(names[:4],[0,4,61,68])),
    'unmatched':['alone.wav'],'groups':dict(zip(names,[1,1,2,2,0]))}),encoding='utf-8')
print(folder/'Groups.xml')
