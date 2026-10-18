import sys
from pathlib import Path
import json
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QProcess
from .ui import MainWindow
from .branding import app_icon


def main():
    app=QApplication(sys.argv)
    if getattr(sys,'frozen',False) and not any(a in sys.argv for a in ['--smoke-test','--update-health-check']):
        from .updates import find_installed_update
        newer=find_installed_update()
        if newer:
            os.environ['PYINSTALLER_RESET_ENVIRONMENT']='1'
            started,_=QProcess.startDetached(str(newer),sys.argv[1:],str(newer.parent))
            if started:return 0
    app.setApplicationName("SyncForge")
    app.setWindowIcon(app_icon())
    app.setOrganizationName("SyncLab")
    app.setFont(QFont("Apple SD Gothic Neo" if sys.platform=='darwin' else "Malgun Gothic",10))
    window=MainWindow()
    if len(sys.argv)==3 and sys.argv[1]=='--update-health-check':
        from .version import VERSION
        report={'success':True,'version':VERSION}
        if os.environ.get('SYNCLAB_UPDATE_HEALTH_NETWORK')=='1':
            from .updates import fetch_latest
            try:
                info=fetch_latest('0.0.0')
                report['update_asset']=info.url
                if sys.platform=='darwin':
                    import certifi
                    report['certificate_bundle_present']=Path(certifi.where()).is_file()
            except Exception as exc:
                report.update(success=False,error=str(exc))
        Path(sys.argv[2]).write_text(json.dumps(report),encoding='utf-8')
        window.close()
        return 0 if report['success'] else 1
    window.show()
    if len(sys.argv)==4 and sys.argv[1]=='--smoke-test':
        from .diagnostics import run_smoke
        window._smoke_timer=run_smoke(app,window,sys.argv[2],sys.argv[3])
        return app.exec()
    if len(sys.argv)>1:
        if len(sys.argv)==2 and Path(sys.argv[1]).suffix.lower() in {'.synclab','.xml'}:
            try:
                if Path(sys.argv[1]).suffix.lower()=='.xml': window.load_xml(sys.argv[1])
                else: window.load_from(sys.argv[1])
            except (ValueError,OSError) as exc: window.notice(str(exc))
        else:
            window.add_paths(sys.argv[1:])
    return app.exec()


if __name__=="__main__":
    raise SystemExit(main())
