from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from PIL import Image

from tushu.domain.entities import uid
from tushu.imaging.geometry import transform
from tushu.imaging.normalize import encode, pixel_hash
from tushu.infrastructure.files import require_space, sha256, write_json
from tushu.infrastructure.tasks import TaskContext
from tushu.services.importing import cache_image
from tushu.services.quality import check_files


def preview(project,asset_id,operations):
    asset = project.asset(asset_id)
    check_files(project,asset)
    with Image.open(project.path(asset['path'])) as image:
        output,boxes,info = transform(image,project.boxes(asset['active_version_id']),operations)
    return output,boxes,info


def apply(project,asset_ids,operations,context=None,augment=False,seed=42):
    context = context or TaskContext(project,'augment' if augment else 'transform')
    if not operations:
        raise ValueError('请先添加至少一项处理操作')
    if augment and len(project.assets())+len(asset_ids)>10000:
        raise ValueError('增强后将超过项目 10000 张上限')
    report = {'success':[],'failed':[],'operations':operations}
    plan = None
    if augment:
        from tushu.services.splitting import current_plan
        plan = current_plan(project)
    try:
        for index,identifier in enumerate(asset_ids):
            context.checkpoint()
            version_id = uid()
            child_id = uid() if augment else identifier
            output_path = None
            try:
                asset = project.asset(identifier)
                if asset['state']=='excluded':
                    raise ValueError('已排除图片不能处理')
                if augment and (asset['state'] not in ('reviewed','negative') or plan['assignments'].get(asset['group_id'])!='train'):
                    raise ValueError('只能增强有效划分中已复核的训练组图片；验证组禁止增强')
                check_files(project,asset)
                require_space(project.root,asset['width']*asset['height']*8)
                old_boxes = project.boxes(asset['active_version_id'])
                with Image.open(project.path(asset['path'])) as source:
                    image,boxes,info = transform(source,old_boxes,operations)
                codec = next((op for op in reversed(operations) if op['op']=='encode'),{})
                fmt = codec.get('format','PNG')
                suffix = {'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}[fmt]
                folder = project.root/'working'/child_id
                folder.mkdir(exist_ok=True)
                output_path = folder/f'{version_id}{suffix}'
                temp = output_path.with_suffix('.tmp')
                encode(image,temp,fmt,codec.get('quality',90),codec.get('background','#ffffff'),
                       codec.get('lossless',False),codec.get('compress_level',6))
                temp.replace(output_path)
                with Image.open(output_path) as decoded:
                    phash = pixel_hash(decoded)
                    mode = decoded.mode
                    cache_image(project,decoded,sha256(output_path))
                info.update({'bytes_in':project.path(asset['path']).stat().st_size,
                             'bytes_out':output_path.stat().st_size,'seed':seed if augment else None})
                new_boxes = [replace(b,id=uid()) for b in boxes]
                with project.transaction() as db:
                    fresh = project.asset(identifier)
                    if fresh['revision']!=asset['revision'] or fresh['active_version_id']!=asset['active_version_id']:
                        raise ValueError('输入版本变化，处理结果未接收')
                    if augment:
                        db.execute('''INSERT INTO assets(id,display_name,source_path,file_hash,pixel_hash,root_asset_id,
                            parent_asset_id,group_id,active_version_id,state) VALUES(?,?,?,?,?,?,?,?,?,'pending')''',
                            (child_id,f"{Path(asset['display_name']).stem}_aug_{child_id[:6]}",asset['source_path'],
                             asset['file_hash'],phash,asset['root_asset_id'],identifier,asset['group_id'],version_id))
                        db.execute('INSERT INTO lineage VALUES(?,?,?,?,?,?,?,0)',
                                   (uid(),identifier,child_id,json.dumps(operations),seed,asset['revision'],asset['active_version_id']))
                    else:
                        db.execute('UPDATE image_versions SET is_active=0 WHERE asset_id=?',(identifier,))
                        db.execute("UPDATE assets SET active_version_id=?,state='pending',pixel_hash=? WHERE id=?",
                                   (version_id,phash,identifier))
                        db.execute('UPDATE lineage SET acknowledged=0 WHERE parent_asset_id=?',(identifier,))
                        project.invalidate_plans(db,'活动工作版本改变，需重检精确重复组')
                    db.execute('INSERT INTO image_versions VALUES(?,?,?,?,?,?,?,?,?,1,0,?)',
                        (version_id,child_id,str(output_path.relative_to(project.root)),image.width,image.height,mode,
                         sha256(output_path),asset['active_version_id'],json.dumps(info),'pending'))
                    db.executemany('INSERT INTO annotations VALUES(?,?,?,?)',
                                   [(b.id,version_id,b.category_id,json.dumps(b.to_dict())) for b in new_boxes])
                    # Exact pixel duplicates join the same group, including results of transforms.
                    duplicates = project.rows('SELECT group_id FROM assets WHERE pixel_hash=? AND id<>? AND removed=0',
                                              (phash,child_id))
                    for duplicate in duplicates:
                        if duplicate['group_id']!=asset['group_id']:
                            db.execute('UPDATE assets SET group_id=? WHERE group_id=?',
                                       (asset['group_id'],duplicate['group_id']))
                            project.invalidate_plans(db,'工作图像素重复组合并')
                    project.audit(db,'augment' if augment else 'transform',
                                  {'asset_id':child_id,'version_id':version_id,'parameters':info})
                report['success'].append({'id':child_id,'version':version_id,**info})
                context.completed += 1
            except Exception as error:
                if output_path:
                    output_path.unlink(missing_ok=True)
                    output_path.with_suffix('.tmp').unlink(missing_ok=True)
                item = {'id':identifier,'reason':str(error)}
                context.failures.append(item)
                report['failed'].append(item)
            context.progress(index+1,len(asset_ids),asset['display_name'])
        if augment and plan:
            from tushu.services.splitting import refresh_plan
            refresh_plan(project,plan)
        return report
    finally:
        write_json(project.root/'logs'/f'{context.kind}-{context.id}.json',report)


def activate_version(project,asset_id,version_id):
    with project.transaction() as db:
        version = project.one('SELECT * FROM image_versions WHERE id=? AND asset_id=?',(version_id,asset_id))
        path = project.path(version['path'])
        if not path.exists() or sha256(path)!=version['sha256']:
            raise ValueError('历史工作版本缺失或摘要变化')
        with Image.open(path) as image:
            phash = pixel_hash(image)
        db.execute('UPDATE image_versions SET is_active=0 WHERE asset_id=?',(asset_id,))
        db.execute('UPDATE image_versions SET is_active=1 WHERE id=?',(version_id,))
        db.execute('UPDATE assets SET active_version_id=?,state=?,pixel_hash=? WHERE id=?',
                   (version_id,version['state'],phash,asset_id))
        db.execute('UPDATE lineage SET acknowledged=0 WHERE parent_asset_id=?',(asset_id,))
        for row in project.rows('SELECT group_id FROM assets WHERE pixel_hash=? AND id<>? AND removed=0',(phash,asset_id)):
            own = project.asset(asset_id)['group_id']
            db.execute('UPDATE assets SET group_id=? WHERE group_id=?',(own,row['group_id']))
        project.invalidate_plans(db,'活动版本切换')


def remove_assets(project,asset_ids):
    with project.transaction() as db:
        for identifier in asset_ids:
            asset = project.asset(identifier)
            db.execute('UPDATE assets SET removed=1 WHERE id=?',(identifier,))
            project.audit(db,'trash',{'id':identifier,'display_name':asset['display_name']})
        project.invalidate_plans(db,'项目回收区范围变化')
