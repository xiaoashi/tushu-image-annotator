from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock

from tushu.domain.entities import Box, uid, utcnow
from tushu.infrastructure.files import digest, safe_path, write_json

SCHEMA = '''
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,schema_version INTEGER,
 created_at TEXT,updated_at TEXT,archived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,display_name TEXT NOT NULL,source_path TEXT,
 file_hash TEXT,pixel_hash TEXT,root_asset_id TEXT,parent_asset_id TEXT,group_id TEXT NOT NULL,
 active_version_id TEXT,state TEXT NOT NULL,excluded_reason TEXT DEFAULT '',removed INTEGER DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS source_hash_unique ON assets(file_hash) WHERE parent_asset_id IS NULL AND removed=0;
CREATE INDEX IF NOT EXISTS asset_state ON assets(state);
CREATE INDEX IF NOT EXISTS asset_group ON assets(group_id);
CREATE TABLE IF NOT EXISTS image_versions(id TEXT PRIMARY KEY,asset_id TEXT REFERENCES assets(id),path TEXT,
 width INTEGER CHECK(width>0),height INTEGER CHECK(height>0),mode TEXT,sha256 TEXT,
 parent_version_id TEXT,transform_json TEXT,is_active INTEGER,revision INTEGER DEFAULT 0,state TEXT DEFAULT 'unlabeled');
CREATE UNIQUE INDEX IF NOT EXISTS single_active ON image_versions(asset_id) WHERE is_active=1;
CREATE TABLE IF NOT EXISTS categories(id TEXT PRIMARY KEY,display_name TEXT,export_name TEXT UNIQUE COLLATE NOCASE,
 color TEXT,sort_order INTEGER,enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS annotations(id TEXT PRIMARY KEY,version_id TEXT REFERENCES image_versions(id),
 category_id TEXT REFERENCES categories(id),data_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS annotation_version ON annotations(version_id);
CREATE TABLE IF NOT EXISTS annotation_revisions(id TEXT PRIMARY KEY,version_id TEXT,revision INTEGER,
 snapshot_hash TEXT,created_at TEXT,UNIQUE(version_id,revision));
CREATE TABLE IF NOT EXISTS edit_actions(id TEXT PRIMARY KEY,version_id TEXT,command_type TEXT,
 before_json TEXT,after_json TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS review_records(id TEXT PRIMARY KEY,version_id TEXT,annotation_revision INTEGER,
 result TEXT,note TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS model_packages(id TEXT PRIMARY KEY,name TEXT,sha256 TEXT,manifest_json TEXT,
 license_path TEXT,status TEXT);
CREATE TABLE IF NOT EXISTS class_mappings(id TEXT PRIMARY KEY,model_package_id TEXT,model_class_id INTEGER,
 category_id TEXT REFERENCES categories(id),ignored INTEGER,revision INTEGER,
 UNIQUE(model_package_id,model_class_id));
CREATE TABLE IF NOT EXISTS inference_runs(id TEXT PRIMARY KEY,model_package_id TEXT,input_snapshot_json TEXT,
 params_json TEXT,status TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS inference_items(id TEXT PRIMARY KEY,run_id TEXT,version_id TEXT,status TEXT,
 error_code TEXT,output_revision INTEGER,UNIQUE(run_id,version_id));
CREATE TABLE IF NOT EXISTS lineage(id TEXT PRIMARY KEY,parent_asset_id TEXT,child_asset_id TEXT,
 operation_json TEXT,seed INTEGER,source_revision INTEGER,source_version_id TEXT,
 acknowledged INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS split_plans(id TEXT PRIMARY KEY,seed INTEGER,algorithm_version TEXT,
 ratio_json TEXT,input_hash TEXT,status TEXT,created_at TEXT,data_json TEXT);
CREATE TABLE IF NOT EXISTS split_assignments(id TEXT PRIMARY KEY,plan_id TEXT,group_id TEXT,split TEXT,
 UNIQUE(plan_id,group_id));
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,type TEXT,status TEXT,progress_json TEXT,error_json TEXT,
 created_at TEXT,finished_at TEXT);
CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,snapshot_json TEXT,format TEXT,output_path TEXT,
 manifest_hash TEXT,validation_json TEXT,status TEXT);
CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,event TEXT,data_json TEXT,created_at TEXT);
'''


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        info = json.loads((self.root / 'project.json').read_text('utf-8'))
        if info.get('schema_version') != 1:
            raise ValueError('项目版本不受支持，请使用匹配的软件版本')
        self._lock = RLock()
        self._lockfile = self.root / '.writer.lock'
        self._closed = True
        self._acquire_lock()
        try:
            self.db = sqlite3.connect(self.root / 'project.sqlite3', check_same_thread=False,
                                      isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript(SCHEMA)
            self.db.execute("UPDATE tasks SET status='interrupted' WHERE status IN ('running','queued','cancelling')")
            self.db.execute("UPDATE inference_runs SET status='interrupted' WHERE status='running'")
            self._closed = False
            import time
            cutoff=time.time()-30*24*60*60
            for log in (self.root/'logs').glob('*.json'):
                if log.stat().st_mtime<cutoff: log.unlink(missing_ok=True)
        except Exception:
            self._lockfile.unlink(missing_ok=True)
            raise

    def _acquire_lock(self):
        # Never remove a lock whose process still exists, including a reused PID.
        for _ in range(2):
            try:
                descriptor = os.open(self._lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, 'w') as stream:
                    json.dump({'pid': os.getpid()}, stream)
                return
            except FileExistsError:
                try:
                    pid = int(json.loads(self._lockfile.read_text())['pid'])
                    os.kill(pid, 0)
                except ProcessLookupError:
                    self._lockfile.unlink()
                    continue
                except (PermissionError, ValueError, KeyError, json.JSONDecodeError):
                    raise RuntimeError('项目锁无法验证，请确认其他实例已关闭后检查 .writer.lock')
                raise RuntimeError('此项目已在另一个窗口打开，请先关闭该窗口')
        raise RuntimeError('无法取得项目写入锁')

    @classmethod
    def create(cls, parent: str | Path, name: str):
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise ValueError('项目名称须为 1—80 个字符')
        identifier = uid()
        root = Path(parent).resolve() / f'tushu-project-{identifier}'
        root.mkdir(parents=True)
        for folder in ('sources','working','thumbnails','previews','models','plans','exports','backups','trash','logs'):
            (root / folder).mkdir()
        write_json(root / 'project.json', {'id': identifier, 'name': name, 'schema_version': 1,
                                          'version': '1.1.0', 'created_at': utcnow()})
        project = cls(root)
        with project.transaction() as db:
            db.execute('INSERT INTO projects VALUES(?,?,?,?,?,0)', (identifier,name,1,utcnow(),utcnow()))
        return project

    @contextmanager
    def transaction(self):
        with self._lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def rows(self, sql, args=()) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self.db.execute(sql, args)]

    def one(self, sql, args=()) -> dict:
        rows = self.rows(sql, args)
        if not rows:
            raise ValueError('记录不存在或已移除')
        return rows[0]

    @property
    def name(self):
        return self.one('SELECT name FROM projects')['name']

    def assets(self):
        return self.rows('''SELECT a.*,v.width,v.height,v.path,v.mode,v.sha256,v.revision
            FROM assets a JOIN image_versions v ON a.active_version_id=v.id
            WHERE a.removed=0 ORDER BY a.display_name COLLATE NOCASE,a.id''')

    def asset(self, asset_id):
        return self.one('''SELECT a.*,v.width,v.height,v.path,v.mode,v.sha256,v.revision
            FROM assets a JOIN image_versions v ON a.active_version_id=v.id WHERE a.id=? AND removed=0''',
                        (asset_id,))

    def boxes(self, version_id):
        return [Box(**json.loads(row['data_json'])) for row in self.rows(
            'SELECT data_json FROM annotations WHERE version_id=? ORDER BY rowid', (version_id,))]

    def categories(self):
        return self.rows('SELECT * FROM categories ORDER BY sort_order,id')

    def path(self, relative):
        return safe_path(self.root, relative)

    def invalidate_plans(self, db, reason):
        db.execute("UPDATE split_plans SET status=? WHERE status='valid'", ('invalid: '+reason,))

    def audit(self, db, event, data):
        db.execute('INSERT INTO audit VALUES(?,?,?,?)', (uid(),event,json.dumps(data,ensure_ascii=False),utcnow()))

    def save_boxes(self, asset_id, boxes, expected_revision, command='edit', state='pending', note=''):
        with self.transaction() as db:
            asset = self.asset(asset_id)
            if asset['state'] == 'excluded':
                raise ValueError('请先重新纳入图片')
            if asset['revision'] != expected_revision:
                raise ValueError('标注修订已变化，已拒绝覆盖；请重新载入图片')
            category_ids = {c['id'] for c in self.categories() if c['enabled']}
            for box in boxes:
                box.validate(asset['width'], asset['height'])
                if box.category_id not in category_ids:
                    raise ValueError('类别无效或已停用')
            before = [b.to_dict() for b in self.boxes(asset['active_version_id'])]
            after = [b.to_dict() for b in boxes]
            if len({b.id for b in boxes}) != len(boxes):
                raise ValueError('检测框 ID 重复')
            version = asset['active_version_id']
            revision = expected_revision + 1
            db.execute('DELETE FROM annotations WHERE version_id=?',(version,))
            db.executemany('INSERT INTO annotations VALUES(?,?,?,?)',
                           [(b.id,version,b.category_id,json.dumps(b.to_dict(),allow_nan=False)) for b in boxes])
            db.execute('UPDATE image_versions SET revision=?,state=? WHERE id=?',(revision,state,version))
            db.execute('UPDATE assets SET state=? WHERE id=?',(state,asset_id))
            db.execute('UPDATE lineage SET acknowledged=0 WHERE parent_asset_id=?',(asset_id,))
            db.execute('INSERT INTO annotation_revisions VALUES(?,?,?,?,?)',
                       (uid(),version,revision,digest(after),utcnow()))
            db.execute('INSERT INTO edit_actions VALUES(?,?,?,?,?,?)',
                       (uid(),version,command,json.dumps(before),json.dumps(after),utcnow()))
            if state in ('reviewed','negative'):
                if (state == 'negative') != (len(boxes) == 0):
                    raise ValueError('负样本状态与框数量不一致')
                db.execute('INSERT INTO review_records VALUES(?,?,?,?,?,?)',
                           (uid(),version,revision,state,note,utcnow()))
        return revision

    def rename(self, name):
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise ValueError('项目名称须为 1—80 字')
        with self.transaction() as db:
            db.execute('UPDATE projects SET name=?,updated_at=?',(name,utcnow()))
        info = json.loads((self.root/'project.json').read_text('utf-8'))
        info['name'] = name
        write_json(self.root/'project.json',info)

    def close(self):
        if not self._closed:
            with self._lock:
                self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                self.db.close()
                self._lockfile.unlink(missing_ok=True)
                self._closed = True
