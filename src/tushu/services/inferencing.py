from __future__ import annotations

import json
import time
from PIL import Image

from tushu.domain.entities import Box, uid, utcnow
from tushu.infrastructure.tasks import TaskContext
from tushu.services.quality import check_files


def register(project,model,mapping):
    categories = {c['id'] for c in project.categories() if c['enabled']}
    if set(mapping)!=set(range(len(model.classes))):
        raise ValueError('请为每个模型类别选择映射或明确忽略')
    if not any(v is not None for v in mapping.values()):
        raise ValueError('请至少映射一个模型类别')
    if any(v is not None and v not in categories for v in mapping.values()):
        raise ValueError('映射含无效项目类别')
    with project.transaction() as db:
        previous = {r['model_class_id']:r['category_id'] for r in project.rows(
            'SELECT * FROM class_mappings WHERE model_package_id=?',(model.id,))}
        db.execute('INSERT OR REPLACE INTO model_packages VALUES(?,?,?,?,?,?)',
                   (model.id,model.id,model.manifest['sha256'],json.dumps(model.manifest),
                    str(model.folder/'LICENSE'),'verified_contract'))
        db.execute('DELETE FROM class_mappings WHERE model_package_id=?',(model.id,))
        db.executemany('INSERT INTO class_mappings VALUES(?,?,?,?,?,1)',
                       [(uid(),model.id,key,value,int(value is None)) for key,value in mapping.items()])
        if previous and previous!=mapping:
            for asset in project.assets():
                if any(b.model_id==model.id for b in project.boxes(asset['active_version_id'])):
                    db.execute("UPDATE assets SET state='pending' WHERE id=?",(asset['id'],))
                    db.execute("UPDATE image_versions SET state='pending' WHERE id=?",(asset['active_version_id'],))
            db.execute("UPDATE exports SET status='outdated' WHERE status='success'")


def replacement_counts(project,asset_ids):
    replace_count=0
    retain_count=0
    for identifier in asset_ids:
        asset = project.asset(identifier)
        for box in project.boxes(asset['active_version_id']):
            if box.source=='model' and not box.edited and asset['state'] not in ('reviewed','negative'):
                replace_count += 1
            else:
                retain_count += 1
    return replace_count,retain_count


def run(project,asset_ids,model,mapping,threshold=.3,nms=.45,context=None):
    context = context or TaskContext(project,'inference')
    snapshot = [project.asset(key) for key in asset_ids]
    run_id = uid()
    report = {'run_id':run_id,'success':[],'failed':[],'truncated':[],'seconds':[]}
    with project.transaction() as db:
        db.execute('INSERT INTO inference_runs VALUES(?,?,?,?,?,?)',
                   (run_id,model.id,json.dumps(snapshot),json.dumps({'threshold':threshold,'nms':nms,'mapping':mapping}),
                    'running',utcnow()))
    status = 'success'
    try:
        for index,asset in enumerate(snapshot):
            context.checkpoint()
            started = time.perf_counter()
            try:
                if asset['state']=='excluded':
                    raise ValueError('已排除图片不可推理')
                check_files(project,asset)
                fresh = project.asset(asset['id'])
                if fresh['revision']!=asset['revision'] or fresh['active_version_id']!=asset['active_version_id']:
                    raise ValueError('输入版本变化，请重新确认任务')
                with Image.open(project.path(asset['path'])) as image:
                    predictions,truncated = model.predict(image,threshold,nms)
                context.checkpoint()
                previous = project.boxes(asset['active_version_id'])
                protected = [b for b in previous if b.source!='model' or b.edited or asset['state'] in ('reviewed','negative')]
                new_boxes = []
                for detection in predictions:
                    category = mapping.get(detection['class_id'])
                    if category is None:
                        continue
                    new_boxes.append(Box(category,*detection['xyxy'],source='model',score=detection['score'],
                                         model_id=model.id,model_class=detection['class_id'],run_id=run_id))
                revision = project.save_boxes(asset['id'],protected+new_boxes,asset['revision'],
                                               'inference','pending' if protected else 'predicted')
                with project.transaction() as db:
                    db.execute('INSERT INTO inference_items VALUES(?,?,?,?,?,?)',
                               (uid(),run_id,asset['active_version_id'],'success',None,revision))
                context.completed += 1
                report['success'].append(asset['id'])
                if truncated:
                    report['truncated'].append(asset['id'])
            except Exception as error:
                from tushu.infrastructure.tasks import Cancelled
                if isinstance(error,Cancelled):
                    raise
                item = {'id':asset['id'],'reason':str(error)}
                report['failed'].append(item)
                context.failures.append(item)
                with project.transaction() as db:
                    db.execute('INSERT INTO inference_items VALUES(?,?,?,?,?,?)',
                               (uid(),run_id,asset['active_version_id'],'failed',str(error),None))
            report['seconds'].append(time.perf_counter()-started)
            context.progress(index+1,len(snapshot),asset['display_name'])
        status = ('partial_failure' if report['success'] else 'failed') if report['failed'] else 'success'
        return report
    except Exception:
        status = 'cancelled' if context.cancel.is_set() else 'failed'
        raise
    finally:
        with project.transaction() as db:
            db.execute('UPDATE inference_runs SET status=? WHERE id=?',(status,run_id))
