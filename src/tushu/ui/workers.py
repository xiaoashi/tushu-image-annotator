from __future__ import annotations

from threading import Event
import traceback
from PySide6.QtCore import QThread, Signal
from tushu.infrastructure.tasks import Cancelled, TaskContext


class Worker(QThread):
    progress = Signal(int,int,str)
    result = Signal(object)
    error = Signal(str)
    cancelled = Signal(str)

    def __init__(self,project,kind,action,parent=None):
        super().__init__(parent)
        self.cancel_event=Event()
        self.project=project
        self.kind=kind
        self.action=action

    def run(self):
        context=TaskContext(self.project,self.kind,self.progress.emit,self.cancel_event)
        try:
            self.result.emit(context.run(self.action))
        except Cancelled as error:
            self.cancelled.emit(str(error))
        except Exception as error:
            traceback.print_exc()
            self.error.emit(str(error))
