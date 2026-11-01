from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import yaml

from tushu.domain.entities import REVIEWED, uid, utcnow
from tushu.infrastructure.files import digest, require_space, sha256, write_json
from tushu.infrastructure.tasks import TaskContext
from tushu.services.quality import check
from tushu.services.splitting import current_plan

RELOCATE = '''from pathlib import Path
import json
root = Path(__file__).resolve().parent
mapping = json.loads((root / "class_mapping.json").read_text(encoding="utf-8"))
names = [c["export_name"] for c in mapping]
# JSON strings and arrays are valid YAML scalars and sequences; no PyYAML dependency.
(root / "data.yaml").write_text("path: " + json.dumps(str(root), ensure_ascii=False) + "\\ntrain: images/train\\nval: images/val\\nnc: " + str(len(names)) + "\\nnames: " + json.dumps(names, ensure_ascii=False) + "\\n", encoding="utf-8")
print("已更新 data.yaml 的 path:", root)
'''


def export(project,destination,fmt='yolo',asset_ids=None,acknowledge_warnings=False,context=None):
    context = context or TaskContext(project,'export')
    if fmt not in ('yolo','coco'):
        raise ValueError('导出格式须为 yolo 或 coco')
    destination = Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    # Never let an output directory become a source/working/model subtree.
    for folder in ('sources','working','thumbnails','previews','models','trash'):
        forbidden = project.root/folder
        if destination==forbidden or destination.is_relative_to(forbidden):
            raise ValueError('不得导出到源图、工作图或缓存目录')
    assets = project.assets()
    if asset_ids is None:
        selected = [a for a in assets if a['state'] in REVIEWED]
    else:
        chosen = set(asset_ids)
        selected = [a for a in assets if a['id'] in chosen]
        if len(selected)!=len(chosen):
            raise ValueError('导出选择包含已移除图片')
    if not selected:
        raise ValueError('没有可导出的已复核图片')
    report = check(project,[a['id'] for a in selected],context=context)
    if report['errors']:
        raise ValueError('质量错误阻止导出：'+report['errors'][0]['message'])
    plan = current_plan(project)
    if {plan['assignments'][a['group_id']] for a in selected}!={'train','val'}:
        raise ValueError('本次导出必须包含训练组和验证组，请调整选择或重新划分')
    categories = [c for c in project.categories() if c['enabled']]
    if not categories:
        raise ValueError('请先建立至少一个启用类别')
    coverage = {split:set() for split in ('train','val')}
    for asset in selected:
        coverage[plan['assignments'][asset['group_id']]].update(
            b.category_id for b in project.boxes(asset['active_version_id']))
    missing_coverage = coverage['train'] ^ coverage['val']
    if missing_coverage:
        report['warnings'].append({'code':'COVERAGE','message':'部分类别只在一个集合中出现'})
    if report['warnings'] and not acknowledge_warnings:
        raise ValueError('请在导出预检中明确确认质量和类别覆盖警告')
    identifier = uid()
    final = destination/f'tushu_{fmt}_{identifier[:12]}'
    temporary = destination/f'.tushu-partial-{identifier}'
    temporary.mkdir()
    mapping = [dict(c,yolo_id=index,coco_id=index+1) for index,c in enumerate(categories)]
    by_id = {c['id']:c for c in mapping}
    manifest = {'id':identifier,'format':fmt,'software':'图枢 V1.1','created_at':utcnow(),
                'plan_id':plan['id'],'images':[],'excluded':[],
                'warnings_acknowledged':report['warnings'],'categories':mapping,'status':'frozen'}
    selected_ids = {a['id'] for a in selected}
    manifest['excluded'] = [{'asset_id':a['id'],'name':a['display_name'],
                             'reason':a['state'] if a['id'] not in selected_ids else ''}
                            for a in assets if a['id'] not in selected_ids]
    with project.transaction() as db:
        db.execute('INSERT INTO exports VALUES(?,?,?,?,?,?,?)',
                   (identifier,json.dumps(manifest),fmt,str(final),None,None,'writing'))
    try:
        needed = sum(project.path(a['path']).stat().st_size for a in selected)
        require_space(destination,needed)
        coco = {split:{'images':[],'annotations':[],
                       'categories':[{'id':c['coco_id'],'name':c['export_name']} for c in mapping]}
                for split in ('train','val')}
        annotation_id = 1
        for index,asset in enumerate(selected):
            context.checkpoint()
            require_space(destination,project.path(asset['path']).stat().st_size)
            split = plan['assignments'][asset['group_id']]
            stem = re.sub(r'[^a-zA-Z0-9_-]+','_',Path(asset['display_name']).stem).strip('_')[:60] or 'image'
            stem = f'{stem}_{asset["id"]}'
            filename = stem+Path(asset['path']).suffix.lower()
            relative = f'images/{split}/{filename}'
            output = temporary/relative
            output.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(project.path(asset['path']),output)
            boxes = project.boxes(asset['active_version_id'])
            width,height = asset['width'],asset['height']
            item = {'asset_id':asset['id'],'version_id':asset['active_version_id'],'revision':asset['revision'],
                    'file':relative,'sha256':sha256(output),'width':width,'height':height,
                    'group_id':asset['group_id'],'pixel_hash':asset['pixel_hash'],'split':split,
                    'root_asset_id':asset['root_asset_id'],'parent_asset_id':asset['parent_asset_id'],
                    'negative':not boxes,'boxes':[b.to_dict() for b in boxes]}
            manifest['images'].append(item)
            if fmt=='yolo':
                labels = temporary/f'labels/{split}/{stem}.txt'
                labels.parent.mkdir(parents=True,exist_ok=True)
                lines = []
                for box in boxes:
                    values = ((box.x1+box.x2)/(2*width),(box.y1+box.y2)/(2*height),
                              (box.x2-box.x1)/width,(box.y2-box.y1)/height)
                    lines.append(str(by_id[box.category_id]['yolo_id'])+' '+ ' '.join(f'{v:.8f}' for v in values))
                labels.write_text('\n'.join(lines)+('\n' if lines else ''),encoding='utf-8')
            else:
                image_id = index+1
                coco[split]['images'].append({'id':image_id,'file_name':relative,'width':width,'height':height})
                for box in boxes:
                    w,h = box.x2-box.x1,box.y2-box.y1
                    coco[split]['annotations'].append({'id':annotation_id,'image_id':image_id,
                        'category_id':by_id[box.category_id]['coco_id'],'bbox':[box.x1,box.y1,w,h],
                        'area':w*h,'iscrowd':0})
                    annotation_id += 1
            context.progress(index+1,len(selected),asset['display_name'])
        for split in ('train','val'):
            (temporary/f'images/{split}').mkdir(parents=True,exist_ok=True)
            if fmt=='yolo':
                (temporary/f'labels/{split}').mkdir(parents=True,exist_ok=True)
            else:
                write_json(temporary/f'annotations/instances_{split}.json',coco[split])
        if fmt=='yolo':
            (temporary/'data.yaml').write_text(yaml.safe_dump({'path':str(final),'train':'images/train',
                'val':'images/val','nc':len(mapping),'names':[c['export_name'] for c in mapping]},allow_unicode=True),encoding='utf-8')
            (temporary/'relocate_dataset.py').write_text(RELOCATE,encoding='utf-8')
        manifest['status']='validation_pending'
        write_json(temporary/'class_mapping.json',mapping)
        write_json(temporary/'split_manifest.json',plan)
        write_json(temporary/'export_manifest.json',manifest)
        (temporary/'README.txt').write_text(
            '图枢 V1.1 目标检测数据集\nCOCO file_name 相对于数据集根目录。\n'
            'YOLO 迁移到其他目录/电脑后，使用 Python 3 运行 python3 relocate_dataset.py。\n'
            '标注为连续图像边界坐标，图片方向已烘焙。负样本保留；同源组不跨集合。\n'
            '来源与模型分数仅保存在 export_manifest.json，未写入训练标签。\n',encoding='utf-8')
        context.checkpoint()
        # Independent reader never imports this module's coordinate generation code.
        from tushu.validation.reader import validate
        result = validate(temporary)
        if not result['passed']:
            raise ValueError('独立回读失败：'+'；'.join(result['errors'][:5]))
        write_json(temporary/'validation.json',result)
        # Freeze checks before publication catch external or unexpected concurrent edits.
        for asset in selected:
            fresh = project.asset(asset['id'])
            if (fresh['active_version_id'],fresh['revision'])!=(asset['active_version_id'],asset['revision']):
                raise ValueError('导出期间输入变化，拒绝发布，请重新导出')
        if current_plan(project)['input_hash']!=plan['input_hash']:
            raise ValueError('导出期间划分发生变化，拒绝发布')
        context.checkpoint()
        manifest['status']='validated'
        write_json(temporary/'export_manifest.json',manifest)
        temporary.rename(final)
        with project.transaction() as db:
            db.execute('UPDATE exports SET snapshot_json=?,manifest_hash=?,validation_json=?,status=? WHERE id=?',
                       (json.dumps(manifest),digest(manifest),json.dumps(result),'success',identifier))
        context.completed=len(selected)
        return {'path':str(final),'validation':result,'excluded':manifest['excluded']}
    except Exception:
        shutil.rmtree(temporary,ignore_errors=True)
        with project.transaction() as db:
            db.execute("UPDATE exports SET status=? WHERE id=?",('cancelled' if context.cancel.is_set() else 'failed',identifier))
        raise
