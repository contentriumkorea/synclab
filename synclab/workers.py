from PySide6.QtCore import QThread, Signal
from .models import Cancelled


class Worker(QThread):
    progress = Signal(int,str)
    completed = Signal(object)
    failed = Signal(str)
    aborted = Signal()

    def __init__(self,fn,parent=None):
        super().__init__(parent)
        self.fn=fn

    def run(self):
        try:
            result=self.fn(self.isInterruptionRequested,self.progress.emit)
            if self.isInterruptionRequested():
                raise Cancelled()
            self.completed.emit(result)
        except Cancelled:
            self.aborted.emit()
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
