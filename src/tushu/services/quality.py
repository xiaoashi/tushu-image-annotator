from __future__ import annotations

from PIL import Image
from tushu.domain.entities import REVIEWED, iou
from tushu.infrastructure.files import sha256


def check_files(project,asset):
    for path_key,hash_key in (('source_path','file_hash'),('path','sha256')):
        path = project.path(asset[path_key])
        if not path.is_file() or sha256(path)!=asset[hash_key]:
            raise ValueError('项目源快照或工作文件缺失/摘要变化，请恢复备份')
    with Image.open(project.path(asset['path'])) as image:
        if image.size != (asset['width'],asset['height']):
            raise ValueError('工作图实际尺寸与记录不一致')
        image.load()


def is_stale(project,asset):
    for row in project.rows('''SELECT l.*,a.active_version_id,v.revision FROM lineage l
        JOIN assets a ON a.id=l.parent_asset_id JOIN image_versions v ON v.id=a.active_version_id
        WHERE l.child_asset_id=?''',(asset['id'],)):
        if not row['acknowledged'] and (row['source_revision']!=row['revision'] or
                                        row['source_version_id']!=row['active_version_id']):
            return True
    return False


def check(project,asset_ids=None,require_review=True,context=None):
    assets = project.assets()
    if asset_ids is not None:
        chosen = set(asset_ids)
        assets = [a for a in assets if a['id'] in chosen]
    else:
        assets = [a for a in assets if a['state']!='excluded']
    categories = {c['id']:c for c in project.categories() if c['enabled']}
    issues = []
    counts = {key:0 for key in categories}
    def issue(level,code,asset,message,boxes=None):
        issues.append({'level':level,'code':code,'asset_id':asset['id'] if asset else None,
                       'name':asset['display_name'] if asset else '', 'message':message,'boxes':boxes or []})
    for index,asset in enumerate(assets):
        if context:
            context.checkpoint()
            context.progress(index+1,len(assets),asset['display_name'])
        try:
            check_files(project,asset)
        except Exception as error:
            issue('error','FILE',asset,str(error))
        if require_review and asset['state'] not in REVIEWED:
            issue('error','REVIEW',asset,'图片尚未复核或已排除')
        if is_stale(project,asset):
            issue('error','LINEAGE',asset,'增强样本的来源已变化，需要重新校正并确认')
        boxes = project.boxes(asset['active_version_id'])
        if asset['state']=='negative' and boxes:
            issue('error','NEGATIVE',asset,'负样本仍含检测框')
        for box in boxes:
            try:
                box.validate(asset['width'],asset['height'])
                if box.category_id not in categories:
                    raise ValueError('类别缺失或已禁用')
                counts[box.category_id] += 1
            except Exception as error:
                issue('error','BOX',asset,str(error),[box.id])
        for left in range(len(boxes)):
            for right in range(left+1,len(boxes)):
                if boxes[left].category_id==boxes[right].category_id and iou(boxes[left],boxes[right])>.9:
                    issue('warning','OVERLAP',asset,'同类框 IoU >0.90，请确认是否重复',[boxes[left].id,boxes[right].id])
    for key,count in counts.items():
        if count==0:
            issue('warning','EMPTY_CLASS',None,f"类别 {categories[key]['display_name']} 没有目标框")
    if len(assets)<10:
        issue('warning','SMALL_DATASET',None,'样本少于 10 张，请确认是否符合用途')
    return {'errors':[i for i in issues if i['level']=='error'],
            'warnings':[i for i in issues if i['level']=='warning'],'issues':issues,'assets':len(assets),'counts':counts}
