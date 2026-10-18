"""Exercise a frozen package on its native OS without requiring an audio device."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
exe=Path(sys.argv[1]).resolve()
folder=ROOT/'validation/ci-smoke';folder.mkdir(parents=True,exist_ok=True)
env={**os.environ,'QT_QPA_PLATFORM':'offscreen','PYTHONPATH':'','PYINSTALLER_RESET_ENVIRONMENT':'1'}
health=folder/'health.json'
subprocess.run([str(exe),'--update-health-check',str(health)],env=env,check=True,timeout=60)
assert json.loads(health.read_text(encoding='utf-8'))['success']
network_env={**env,'SYNCLAB_UPDATE_HEALTH_NETWORK':'1'}
if sys.platform=='darwin':
    network_env.update(SSL_CERT_FILE='/no-system-ca.pem',SSL_CERT_DIR='/no-system-ca')
network_report=folder/'network-health.json'
for attempt in range(3):
    result=subprocess.run([str(exe),'--update-health-check',str(network_report)],env=network_env,timeout=60)
    network=json.loads(network_report.read_text(encoding='utf-8'))
    if result.returncode==0:break
    print(f"Network health attempt {attempt+1}: {network.get('error', 'unknown error')!a}",flush=True)
    if attempt<2:time.sleep(3)
assert result.returncode==0,network
assert network['success'] and 'github.com/contentriumkorea/synclab/releases/download/' in network['update_asset']
if sys.platform=='darwin':assert network['certificate_bundle_present']
subprocess.run([str(exe),'--smoke-test',str(ROOT/'validation/ci-fixture/Groups.xml'),str(folder)],env=env,check=True,timeout=120)
report=json.loads((folder/'startup-report.json').read_text(encoding='utf-8'))
assert report['success'] and report['frozen']
assert report['sync_groups']==dict(zip(['reference.wav','camera.wav','group-a.wav','group-b.wav','alone.wav'],[1,1,2,2,0]))
print(json.dumps({'native':sys.platform,'success':True,'groups':2,'sources':5,'xml_items':report['xml_items']}))
