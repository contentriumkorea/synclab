import sys
from pathlib import Path
import json
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QProcess
from .ui import MainWindow


def main():
    app=QApplication(sys.argv)
    if getattr(sys,'frozen',False) and not any(a in sys.argv for a in ['--smoke-test','--update-health-check']):
        from .updates import find_installed_update
        newer=find_installed_update()
        if newer:
            os.environ['PYINSTALLER_RESET_ENVIRONMENT']='1'
            started,_=QProcess.startDetached(str(newer),sys.argv[1:],str(newer.parent))
            if started:return 0
    app.setApplicationName("SyncLab")
    app.setOrganizationName("SyncLab")
    app.setFont(QFont("Malgun Gothic",10))
    window=MainWindow()
    if len(sys.argv)==3 and sys.argv[1]=='--update-health-check':
        from .version import VERSION
        Path(sys.argv[2]).write_text(json.dumps({'success':True,'version':VERSION}),encoding='utf-8')
        window.close()
        return 0
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
