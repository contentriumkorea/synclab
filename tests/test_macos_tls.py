import io
import ssl
import sys
from urllib.request import HTTPSHandler
from synclab import updates


def test_mac_https_has_verified_roots_without_a_python_installation(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'platform','darwin')
    monkeypatch.setenv('SSL_CERT_FILE',str(tmp_path/'no-system-ca.pem'))
    monkeypatch.setenv('SSL_CERT_DIR',str(tmp_path/'no-system-ca'))
    handlers=[]
    class Opener:
        def open(self,*a,**kw):return io.BytesIO(b'{}')
    def build(*args):handlers.extend(args);return Opener()
    monkeypatch.setattr(updates,'build_opener',build)
    with updates._open('https://api.github.com/repos/contentriumkorea/synclab/releases/latest',None):pass
    https=next((x for x in handlers if isinstance(x,HTTPSHandler)),None)
    assert https is not None
    assert https._context.check_hostname
    assert https._context.verify_mode==ssl.CERT_REQUIRED
    assert https._context.cert_store_stats()['x509_ca']>50
