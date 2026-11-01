from __future__ import annotations

import os
from pathlib import Path
import shutil
from PIL import Image

from tushu.domain.entities import uid
from tushu.imaging.normalize import SUPPORTED, inspect, normalize, pixel_hash
from tushu.infrastructure.files import require_space, sha256, write_json
from tushu.infrastructure.tasks import TaskContext


def scan(folder, recursive=True, context=None):
    context = context or TaskContext()
    root = Path(folder).resolve()
    if not root.is_dir():
        raise ValueError('请选择有效文件夹')
    report = []
    for directory, directories, files in os.walk(root,followlinks=False):
        directories[:] = sorted(d for d in directories if not Path(directory,d).is_symlink())
        for name in sorted(files):
            context.checkpoint()
            path = Path(directory,name)
            if path.suffix.lower() not in SUPPORTED:
                continue
            row = {'path':str(path),'name':name,'accepted':False}
            try:
                row.update(inspect(path))
                row['hash'] = sha256(path)
                row['accepted'] = True
                row['reason'] = ''
            except Exception as error:
                row['reason'] = str(error)
            report.append(row)
            context.callback(len(report),0,name)
        if not recursive:
            break
    return report


def cache_image(project, image, version_hash):
    for folder,edge in (('thumbnails',256),('previews',2048)):
        preview = image.copy()
        preview.thumbnail((edge,edge),Image.Resampling.LANCZOS)
        preview.save(project.root/folder/f'{version_hash}.png')


def import_files(project, candidates, context=None):
    context = context or TaskContext(project,'import')
    valid = [row for row in candidates if row.get('accepted')]
    if len(valid)>2000:
        raise ValueError('单次最多导入 2000 张，请分批导入')
    if len(project.assets())+len(valid)>10000:
        raise ValueError('项目最多 10000 张，请新建项目')
    require_space(project.root,sum(row['size']+row['width']*row['height']*4 for row in valid))
    report = {'added':[],'duplicate':[],'rejected':[{'name':r['name'],'reason':r['reason']} for r in candidates if not r.get('accepted')],
              'failed':[],'cancelled':[]}
    try:
        for index,row in enumerate(valid):
            if context.cancel.is_set():
                report['cancelled'] = [r['name'] for r in valid[index:]]
                break
            source = Path(row['path'])
            asset_id,version_id = uid(),uid()
            source_dir = project.root/'sources'/asset_id
            work_dir = project.root/'working'/asset_id
            try:
                if project.rows('SELECT id FROM assets WHERE file_hash=? AND removed=0',(row['hash'],)):
                    report['duplicate'].append(row['name'])
                    continue
                require_space(project.root,row['size']+row['width']*row['height']*8)
                source_dir.mkdir()
                work_dir.mkdir()
                snapshot = source_dir/f'original{source.suffix.lower()}'
                shutil.copyfile(source,snapshot)
                actual_hash = sha256(snapshot)
                if actual_hash != row['hash']:
                    raise ValueError('扫描后源文件发生变化，请重新扫描')
                image,color = normalize(snapshot)
                phash = pixel_hash(image)
                version_path = work_dir/f'{version_id}.png'
                image.save(version_path)
                vhash = sha256(version_path)
                cache_image(project,image,vhash)
                group_rows = project.rows('SELECT group_id FROM assets WHERE pixel_hash=? AND removed=0',(phash,))
                group = group_rows[0]['group_id'] if group_rows else uid()
                with project.transaction() as db:
                    db.execute('''INSERT INTO assets(id,display_name,source_path,file_hash,pixel_hash,
                        root_asset_id,parent_asset_id,group_id,active_version_id,state)
                        VALUES(?,?,?,?,?,?,NULL,?,?,'unlabeled')''',
                        (asset_id,row['name'],str(snapshot.relative_to(project.root)),actual_hash,phash,asset_id,group,version_id))
                    import json
                    db.execute('INSERT INTO image_versions VALUES(?,?,?,?,?,?,?,?,?,1,0,?)',
                        (version_id,asset_id,str(version_path.relative_to(project.root)),image.width,image.height,
                         image.mode,vhash,None,json.dumps({'op':'normalize','color':color}),'unlabeled'))
                    project.invalidate_plans(db,'新增图片')
                context.completed += 1
                report['added'].append(asset_id)
            except Exception as error:
                shutil.rmtree(source_dir,ignore_errors=True)
                shutil.rmtree(work_dir,ignore_errors=True)
                item = {'name':row['name'],'reason':str(error)}
                report['failed'].append(item)
                context.failures.append(item)
            finally:
                context.progress(index+1,len(valid),row['name'])
    finally:
        write_json(project.root/'logs'/f'import-{context.id}.json',report)
    if report['cancelled']:
        from tushu.infrastructure.tasks import Cancelled
        raise Cancelled(f"导入已取消：新增 {len(report['added'])} 张；未处理 {len(report['cancelled'])} 张。报告已保存。")
    return report
