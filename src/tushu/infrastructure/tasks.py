from __future__ import annotations

import json
from threading import Event
from tushu.domain.entities import uid, utcnow


class Cancelled(Exception):
    pass


class TaskContext:
    def __init__(self, project=None, kind='operation', progress=None, cancel=None):
        self.project = project
        self.id = uid()
        self.kind = kind
        self.cancel = cancel or Event()
        self.callback = progress or (lambda done,total,name: None)
        self.failures = []
        self.completed = 0

    def checkpoint(self):
        if self.cancel.is_set():
            raise Cancelled('任务已取消；已完整提交的单图结果保留')

    def progress(self, done, total, name=''):
        self.callback(done,total,name)
        if self.project:
            with self.project.transaction() as db:
                db.execute('UPDATE tasks SET progress_json=? WHERE id=?',
                           (json.dumps({'done':done,'total':total,'current':name}),self.id))

    def run(self, action):
        if self.project:
            with self.project.transaction() as db:
                db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',
                           (self.id,self.kind,'running','{}','[]',utcnow(),None))
        status = 'success'
        try:
            value = action(self)
            if self.failures:
                status = 'partial_failure' if self.completed else 'failed'
            return value
        except Cancelled:
            status = 'cancelled'
            raise
        except Exception:
            status = 'failed'
            raise
        finally:
            if self.project:
                with self.project.transaction() as db:
                    db.execute('UPDATE tasks SET status=?,error_json=?,finished_at=? WHERE id=?',
                               (status,json.dumps(self.failures,ensure_ascii=False),utcnow(),self.id))
