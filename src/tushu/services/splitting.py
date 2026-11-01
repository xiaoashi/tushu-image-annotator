from __future__ import annotations

from collections import Counter
import hashlib
import json

from tushu.domain.entities import uid, utcnow
from tushu.infrastructure.files import digest, write_json


def input_groups(project):
    return sorted((a['id'],a['group_id'],a['pixel_hash']) for a in project.assets() if a['state']!='excluded')


def merge_groups(project,asset_ids):
    if len(asset_ids)<2:
        raise ValueError('请选择至少两张同源图片')
    with project.transaction() as db:
        groups = {project.asset(key)['group_id'] for key in asset_ids}
        target = min(groups)
        for group in groups:
            db.execute('UPDATE assets SET group_id=? WHERE group_id=?',(target,group))
        project.invalidate_plans(db,'手工合并同源组')
        project.audit(db,'merge_groups',{'groups':sorted(groups),'target':target})


def statistics(project,assignments):
    result = {split:{'images':0,'categories':{c['id']:{'images':0,'boxes':0} for c in project.categories() if c['enabled']}}
              for split in ('train','val')}
    for asset in project.assets():
        if asset['state']=='excluded':
            continue
        split = assignments.get(asset['group_id'])
        if split is None:
            continue
        result[split]['images'] += 1
        counts = Counter(b.category_id for b in project.boxes(asset['active_version_id']))
        for category,count in counts.items():
            if category in result[split]['categories']:
                result[split]['categories'][category]['images'] += 1
                result[split]['categories'][category]['boxes'] += count
    return result


def create(project,train_ratio=.8,seed=42):
    if not .5<=train_ratio<=.95:
        raise ValueError('训练比例须为 0.50—0.95')
    groups = Counter(group for _,group,_ in input_groups(project))
    if len(groups)<2:
        raise ValueError('至少需要两个独立同源组，不能拆分重复图凑数')
    ordered = sorted(groups,key=lambda group:(hashlib.sha256(f'{seed}:{group}'.encode()).hexdigest(),group))
    target = sum(groups.values())*(1-train_ratio)
    count = 0
    assignments = {}
    for group in ordered:
        if abs(count+groups[group]-target)<abs(count-target):
            assignments[group]='val'
            count += groups[group]
        else:
            assignments[group]='train'
    if 'val' not in assignments.values():
        assignments[min(ordered,key=lambda g:(groups[g],g))]='val'
    if 'train' not in assignments.values():
        assignments[max(ordered,key=lambda g:(groups[g],g))]='train'
    plan = {'id':uid(),'seed':seed,'algorithm':'group-greedy-1','train_ratio':train_ratio,
            'input_hash':digest(input_groups(project)),'assignments':assignments,
            'created_at':utcnow(),'statistics':statistics(project,assignments)}
    with project.transaction() as db:
        project.invalidate_plans(db,'创建新计划')
        db.execute('INSERT INTO split_plans VALUES(?,?,?,?,?,?,?,?)',
                   (plan['id'],seed,plan['algorithm'],json.dumps({'train':train_ratio,'val':1-train_ratio}),
                    plan['input_hash'],'valid',plan['created_at'],json.dumps(plan)))
        db.executemany('INSERT INTO split_assignments VALUES(?,?,?,?)',
                       [(uid(),plan['id'],g,s) for g,s in assignments.items()])
    write_json(project.root/'plans'/f"{plan['id']}.json",plan)
    return plan


def current_plan(project):
    rows = project.rows("SELECT data_json FROM split_plans WHERE status='valid' ORDER BY created_at DESC LIMIT 1")
    if not rows:
        raise ValueError('没有有效划分计划，请先创建训练/验证划分')
    plan = json.loads(rows[0]['data_json'])
    if plan['input_hash']!=digest(input_groups(project)):
        raise ValueError('划分输入已改变，请重新创建计划')
    plan['statistics'] = statistics(project,plan['assignments'])
    return plan


def refresh_plan(project,plan):
    # Only augmentation of a training group may extend a still-valid plan.
    with project.transaction() as db:
        row = project.one('SELECT status FROM split_plans WHERE id=?',(plan['id'],))
        if row['status']!='valid':
            return
        if any(group not in plan['assignments'] for _,group,_ in input_groups(project)):
            project.invalidate_plans(db,'增强产生未分组来源')
            return
        plan['input_hash'] = digest(input_groups(project))
        plan['statistics'] = statistics(project,plan['assignments'])
        db.execute('UPDATE split_plans SET input_hash=?,data_json=? WHERE id=?',
                   (plan['input_hash'],json.dumps(plan),plan['id']))
    write_json(project.root/'plans'/f"{plan['id']}.json",plan)
