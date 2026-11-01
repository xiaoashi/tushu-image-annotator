from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3

from tushu.domain.entities import uid
from tushu.infrastructure.files import sha256, write_json
from tushu.infrastructure.tasks import TaskContext


def backup(project,destination,context=None):
    context = context or TaskContext()
    parent = Path(destination).resolve()
    if parent.is_relative_to(project.root):
        raise ValueError('备份请选择项目目录以外的位置，避免递归备份')
    target = parent/f'tushu-backup-{uid()}'
    target.mkdir(parents=True)
    try:
        with project._lock:
            connection = sqlite3.connect(target/'project.sqlite3')
            try:
                project.db.backup(connection)
            finally:
                connection.close()
        files = [project.root/'project.json']
        for folder in ('sources','working','plans'):
            files.extend(p for p in (project.root/folder).rglob('*') if p.is_file())
        for index,path in enumerate(files):
            context.checkpoint()
            relative = path.relative_to(project.root)
            output = target/relative
            output.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,output)
            context.progress(index+1,len(files),path.name)
        models = project.rows('SELECT id,sha256,manifest_json FROM model_packages')
        write_json(target/'model_references.json',models)
        checksums = {str(p.relative_to(target)):sha256(p) for p in target.rglob('*') if p.is_file()}
        write_json(target/'checksums.json',checksums)
        return str(target)
    except Exception:
        shutil.rmtree(target,ignore_errors=True)
        raise


def restore(source,destination):
    source = Path(source).resolve()
    checksums = json.loads((source/'checksums.json').read_text('utf-8'))
    if json.loads((source/'project.json').read_text('utf-8')).get('schema_version')!=1:
        raise ValueError('备份 schema 不兼容')
    for relative,expected in checksums.items():
        path = (source/relative).resolve()
        if not path.is_relative_to(source) or not path.is_file() or sha256(path)!=expected:
            raise ValueError(f'备份校验失败：{relative}')
    target = Path(destination).resolve()/f'tushu-project-{uid()}'
    if target.is_relative_to(source):
        raise ValueError('不能恢复到备份目录内')
    shutil.copytree(source,target)
    for folder in ('thumbnails','previews','models','exports','backups','trash','logs'):
        (target/folder).mkdir(exist_ok=True)
    return target
