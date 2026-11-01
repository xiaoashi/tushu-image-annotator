from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
import json
import re
import unicodedata

from tushu.domain.entities import uid


class History:
    def __init__(self,project):
        self.project = project
        self.stacks = OrderedDict()

    def _stack(self,asset):
        key = (asset['id'],asset['active_version_id'])
        if key not in self.stacks:
            self.stacks[key] = [[],[]]
        self.stacks.move_to_end(key)
        return self.stacks[key]

    def execute(self,asset,boxes,command):
        before = self.project.boxes(asset['active_version_id'])
        self.project.save_boxes(asset['id'],boxes,asset['revision'],command)
        undo,redo = self._stack(asset)
        undo.append((before,[replace(b) for b in boxes]))
        del undo[:-100]
        redo.clear()
        while sum(len(s[0])+len(s[1]) for s in self.stacks.values())>1000:
            oldest = next(iter(self.stacks))
            stack = self.stacks[oldest]
            if stack[0]:
                stack[0].pop(0)
            elif stack[1]:
                stack[1].pop(0)
            else:
                del self.stacks[oldest]

    def undo(self,asset,redo=False):
        undo_stack,redo_stack = self._stack(asset)
        source,target = (redo_stack,undo_stack) if redo else (undo_stack,redo_stack)
        if not source:
            return
        before,after = source[-1]
        self.project.save_boxes(asset['id'],after if redo else before,asset['revision'],
                                'redo' if redo else 'undo')
        target.append(source.pop())


def add_category(project,display_name,export_name,color='#237866'):
    display_name = display_name.strip()
    export_name = unicodedata.normalize('NFKC',export_name.strip())
    if not 1<=len(display_name)<=50 or not 1<=len(export_name)<=50:
        raise ValueError('类别名称须为 1—50 字')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
        raise ValueError('颜色须为 #RRGGBB')
    if any(unicodedata.normalize('NFKC',c['export_name']).casefold()==export_name.casefold() for c in project.categories()):
        raise ValueError('导出类别名称重复')
    identifier = uid()
    with project.transaction() as db:
        db.execute('INSERT INTO categories VALUES(?,?,?,?,?,1)',
                   (identifier,display_name,export_name,color,len(project.categories())))
    return identifier


def update_category(project,identifier,display_name,export_name,color,enabled=True):
    display_name,export_name = display_name.strip(),unicodedata.normalize('NFKC',export_name.strip())
    if not 1<=len(display_name)<=50 or not 1<=len(export_name)<=50 or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
        raise ValueError('类别名须为 1—50 字，颜色须为 #RRGGBB')
    if any(c['id']!=identifier and c['export_name'].casefold()==export_name.casefold() for c in project.categories()):
        raise ValueError('导出名重复')
    if not enabled and project.rows('SELECT id FROM annotations WHERE category_id=?',(identifier,)):
        raise ValueError('该类别仍被标注引用，请先合并类别')
    with project.transaction() as db:
        db.execute('UPDATE categories SET display_name=?,export_name=?,color=?,enabled=? WHERE id=?',
                   (display_name,export_name,color,int(enabled),identifier))
        project.audit(db,'category_updated',{'id':identifier,'export_name':export_name})
        db.execute("UPDATE exports SET status='outdated' WHERE status='success'")


def merge_category(project,source,target=None):
    if source == target:
        raise ValueError('请选择另一个合并目标')
    with project.transaction() as db:
        referenced = project.rows('SELECT DISTINCT version_id FROM annotations WHERE category_id=?',(source,))
        if referenced and not target:
            raise ValueError('类别被标注引用，须先合并到其他类别')
        if target and not project.rows('SELECT id FROM categories WHERE id=? AND enabled=1',(target,)):
            raise ValueError('合并目标无效')
        for row in referenced:
            boxes = project.boxes(row['version_id'])
            for box in boxes:
                if box.category_id == source:
                    box.category_id = target
                    box.edited = True
                    db.execute('UPDATE annotations SET category_id=?,data_json=? WHERE id=?',
                               (target,json.dumps(box.to_dict()),box.id))
            db.execute("UPDATE image_versions SET state='pending',revision=revision+1 WHERE id=?",(row['version_id'],))
            db.execute("UPDATE assets SET state='pending' WHERE active_version_id=?",(row['version_id'],))
        db.execute('UPDATE class_mappings SET category_id=?,revision=revision+1 WHERE category_id=?',(target,source))
        db.execute('DELETE FROM categories WHERE id=?',(source,))
        project.audit(db,'category_merged',{'source':source,'target':target})
        db.execute("UPDATE exports SET status='outdated' WHERE status='success'")


def review(project,asset_id,hidden=False,acknowledge_stale=False):
    asset = project.asset(asset_id)
    if hidden:
        raise ValueError('请先显示全部检测框，再完成复核')
    from tushu.services.quality import check_files, is_stale
    check_files(project,asset)
    if is_stale(project,asset):
        if not acknowledge_stale:
            raise ValueError('增强来源已变化，请校正后勾选确认来源过期处理')
        with project.transaction() as db:
            db.execute('UPDATE lineage SET acknowledged=1 WHERE child_asset_id=?',(asset_id,))
    boxes = project.boxes(asset['active_version_id'])
    return project.save_boxes(asset_id,boxes,asset['revision'],'review', 'reviewed' if boxes else 'negative')


def set_excluded(project,asset_ids,reason=None):
    with project.transaction() as db:
        for identifier in asset_ids:
            asset = project.asset(identifier)
            if reason is None:
                from tushu.services.quality import check_files
                check_files(project,asset)
                state = 'pending'
            else:
                if not reason.strip():
                    raise ValueError('请填写排除原因')
                state = 'excluded'
            db.execute('UPDATE assets SET state=?,excluded_reason=? WHERE id=?',(state,reason or '',identifier))
        project.invalidate_plans(db,'导出范围发生变化')


def rename_assets(project,asset_ids,prefix='image_',start=1,step=1,padding=6,apply=False):
    if start<0 or step<1 or not 1<=padding<=12:
        raise ValueError('起始序号不能为负、步长至少 1、补零位数为 1—12')
    mapping = []
    for index,identifier in enumerate(asset_ids):
        asset = project.asset(identifier)
        name = f'{prefix}{start+index*step:0{padding}d}'
        if re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.rstrip(' .')!=name or len(name)>180:
            raise ValueError('名称含非法字符、过长或结尾含空格/点')
        if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',name,re.I):
            raise ValueError('名称为 Windows 保留名')
        mapping.append({'id':identifier,'old':asset['display_name'],'new':name})
    names = [row['new'].casefold() for row in mapping]
    others = {a['display_name'].casefold() for a in project.assets() if a['id'] not in asset_ids}
    if len(set(names))!=len(names) or set(names)&others:
        raise ValueError('重命名导致名称碰撞')
    if apply:
        with project.transaction() as db:
            db.executemany('UPDATE assets SET display_name=? WHERE id=?',[(m['new'],m['id']) for m in mapping])
            project.audit(db,'rename',mapping)
    return mapping
