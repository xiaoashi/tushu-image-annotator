from dataclasses import replace
import json
from pathlib import Path
from threading import Event
import pytest
from PIL import Image
from tushu.domain.entities import Box, REVIEWED
from tushu.imaging.geometry import transform
from tushu.repositories.project import Project
from tushu.services import importing,editing,processing,quality,splitting
from tushu.datasets.exporter import export
from tushu.infrastructure.tasks import TaskContext,Cancelled
from tushu.validation.reader import validate


def reviewed(project,negatives=True):
    category=project.categories()[0]['id']
    for index,asset in enumerate(project.assets()):
        if not negatives or index%2==0:
            project.save_boxes(asset['id'],[Box(category,1,2,30,40)],asset['revision'])
        editing.review(project,asset['id'])
    return splitting.create(project)


@pytest.mark.parametrize('op,expected,size',[
    ({'op':'flip_h'},(70,5,90,25),(100,60)),
    ({'op':'flip_v'},(10,35,30,55),(100,60)),
    ({'op':'rotate','angle':90},(35,10,55,30),(60,100)),
    ({'op':'rotate','angle':180},(70,35,90,55),(100,60)),
    ({'op':'rotate','angle':270},(5,70,25,90),(60,100)),
    ({'op':'resize','width':200,'height':180},(20,15,60,75),(200,180)),
    ({'op':'crop','x':15,'y':10,'width':60,'height':40},(0,0,15,15),(60,40)),
])
def test_geometry(op,expected,size):
    image=Image.new('RGB',(100,60))
    output,boxes,info=transform(image,[Box('a',10,5,30,25)],[op])
    assert output.size==size
    assert (boxes[0].x1,boxes[0].y1,boxes[0].x2,boxes[0].y2)==pytest.approx(expected)
    assert len(info['matrix'])==3


def test_crop_edge_and_minimum():
    image=Image.new('RGB',(100,60))
    boxes=[Box('a',0,0,100,60),Box('a',0,0,1,1),Box('a',90,50,100,60)]
    _,out,info=transform(image,boxes,[{'op':'crop','x':0,'y':0,'width':50,'height':30}])
    assert len(out)==2 and info['removed']==[boxes[2].id]
    with pytest.raises(ValueError): transform(image,boxes,[{'op':'crop','x':99,'y':0,'width':2,'height':5}])


def test_scan_normalization(tmp_path,project):
    folder=tmp_path/'源'; folder.mkdir()
    rgba=Image.new('RGBA',(12,9),(22,33,44,128)); rgba.save(folder/'透明.png')
    Image.new('L',(11,10),128).save(folder/'灰度.png')
    rgb=Image.new('RGB',(13,10)); exif=rgb.getexif(); exif[274]=6; rgb.save(folder/'方向.jpg',exif=exif)
    (folder/'坏图.png').write_bytes(b'broken')
    rgb.save(folder/'伪扩展.png',format='JPEG')
    rgb.save(folder/'坏ICC.png',icc_profile=b'bad-icc')
    frames=[Image.new('RGB',(10,10),'red'),Image.new('RGB',(10,10),'green')]
    frames[0].save(folder/'动画.webp',save_all=True,append_images=frames[1:],duration=100)
    (folder/'环').symlink_to(folder,target_is_directory=True)
    rows=importing.scan(folder)
    assert len(rows)==7
    assert sum(r['accepted'] for r in rows)==3
    result=importing.import_files(project,rows)
    assert len(result['added'])==3 and len(result['rejected'])==4
    sizes={a['display_name']:(a['width'],a['height'],a['mode']) for a in project.assets()}
    assert sizes['方向.jpg'][:2]==(10,13)
    assert sizes['透明.png'][2]=='RGBA' and sizes['灰度.png'][2]=='RGB'
    result=importing.import_files(project,rows)
    assert len(result['duplicate'])==3


def test_dedup_pixel_group(tmp_path,project):
    folder=tmp_path/'images'; folder.mkdir()
    image=Image.new('RGB',(20,20),'red')
    image.save(folder/'a.png',compress_level=1); image.save(folder/'b.png',compress_level=9)
    importing.import_files(project,importing.scan(folder))
    assets=project.assets()
    assert len(assets)==2 and assets[0]['group_id']==assets[1]['group_id']
    with pytest.raises(ValueError): splitting.create(project)


def test_atomic_edits_history_and_reopen(imported):
    project=imported; asset=project.assets()[0]; category=project.categories()[0]['id']
    history=editing.History(project)
    box=Box(category,0,0,1,1)
    history.execute(asset,[box],'create')
    with pytest.raises(ValueError): project.save_boxes(asset['id'],[],asset['revision'])
    asset=project.asset(asset['id']); history.undo(asset)
    assert not project.boxes(asset['active_version_id'])
    history.undo(project.asset(asset['id']),True)
    editing.review(project,asset['id'])
    assert project.asset(asset['id'])['state']=='reviewed'
    root=project.root; project.close()
    reopened=Project(root)
    try:
        assert reopened.asset(asset['id'])['state']=='reviewed'
        assert reopened.boxes(asset['active_version_id'])[0].x2==1
        with pytest.raises(RuntimeError): Project(root)
    finally: reopened.close()


def test_invalid_edit_rollback(imported):
    project=imported; asset=project.assets()[0]; category=project.categories()[0]['id']
    for box in [Box(category,0,0,float('nan'),4),Box(category,0,0,.5,1),Box(category,0,0,121,4),Box('missing',0,0,1,1)]:
        with pytest.raises(ValueError): project.save_boxes(asset['id'],[box],0)
    assert project.asset(asset['id'])['revision']==0


def test_version_transform_and_restore(imported):
    project=imported; asset=project.assets()[0]; category=project.categories()[0]['id']
    project.save_boxes(asset['id'],[Box(category,0,0,10,20)],0); editing.review(project,asset['id'])
    old=project.asset(asset['id'])
    report=processing.apply(project,[asset['id']],[{'op':'rotate','angle':90}])
    assert len(report['success'])==1
    current=project.asset(asset['id'])
    assert current['state']=='pending' and current['width']==80
    box=project.boxes(current['active_version_id'])[0]
    assert (box.x1,box.y1,box.x2,box.y2)==(60,0,80,10)
    processing.activate_version(project,asset['id'],old['active_version_id'])
    assert project.asset(asset['id'])['state']=='reviewed'
    assert project.path(old['path']).exists() and project.path(current['path']).exists()


def test_split_reproducible_and_invalidated(imported,tmp_path):
    project=imported
    first=splitting.create(project); second=splitting.create(project)
    assert first['assignments']==second['assignments']
    folder=tmp_path/'more'; folder.mkdir(); Image.new('RGB',(11,11),'green').save(folder/'more.png')
    importing.import_files(project,importing.scan(folder))
    with pytest.raises(ValueError): splitting.current_plan(project)


def test_augment_only_train_and_stale(imported):
    project=imported; plan=reviewed(project)
    train=next(a for a in project.assets() if plan['assignments'][a['group_id']]=='train')
    val=next(a for a in project.assets() if plan['assignments'][a['group_id']]=='val')
    assert processing.apply(project,[val['id']],[{'op':'flip_h'}],augment=True)['failed']
    report=processing.apply(project,[train['id']],[{'op':'flip_h'}],augment=True)
    child=project.asset(report['success'][0]['id'])
    assert child['state']=='pending' and child['group_id']==train['group_id']
    assert splitting.current_plan(project)['assignments'][child['group_id']]=='train'
    original=project.asset(train['id'])
    project.save_boxes(train['id'],project.boxes(original['active_version_id']),original['revision'])
    assert quality.is_stale(project,child)
    with pytest.raises(ValueError): editing.review(project,child['id'])
    editing.review(project,child['id'],acknowledge_stale=True)
    assert not quality.is_stale(project,child)


@pytest.mark.parametrize('fmt',['yolo','coco'])
def test_exports_negative_roundtrip_and_tamper(imported,tmp_path,fmt):
    project=imported; reviewed(project)
    result=export(project,tmp_path/'exports',fmt,acknowledge_warnings=True)
    root=Path(result['path']); report=validate(root)
    assert report['passed'] and report['images']==4 and report['negative_images']==2
    assert report['max_coordinate_error_px']<.0001
    if fmt=='yolo':
        labels=sorted((root/'labels').rglob('*.txt')); assert len(labels)==4
        label=next(p for p in labels if p.read_text())
        label.write_text('0 0.8 0.8 0.1 0.1\n')
    else:
        file=root/'annotations/instances_train.json'; coco=json.loads(file.read_text())
        if coco['annotations']: coco['annotations'][0]['bbox'][0]+=20
        else: coco['images'].pop()
        file.write_text(json.dumps(coco))
    assert not validate(root)['passed']


def test_no_export_unreviewed_or_bad_files(imported,tmp_path):
    project=imported; splitting.create(project)
    with pytest.raises(ValueError): export(project,tmp_path/'out',asset_ids=[a['id'] for a in project.assets()],acknowledge_warnings=True)
    reviewed(project)
    asset=project.assets()[0]; project.path(asset['path']).write_bytes(b'changed')
    with pytest.raises(ValueError): export(project,tmp_path/'out',acknowledge_warnings=True)
    assert not list((tmp_path/'out').glob('tushu_yolo_*'))


def test_cancellation_no_partial_export(imported,tmp_path):
    reviewed(imported)
    event=Event(); event.set()
    with pytest.raises(Cancelled): export(imported,tmp_path/'out',acknowledge_warnings=True,
                                           context=TaskContext(cancel=event))
    assert not list((tmp_path/'out').glob('*'))


def test_category_merge_protects_state(imported):
    project=imported; asset=project.assets()[0]; source=project.categories()[0]['id']
    project.save_boxes(asset['id'],[Box(source,1,1,10,10)],0); editing.review(project,asset['id'])
    target=editing.add_category(project,'植物','plant')
    with pytest.raises(ValueError): editing.merge_category(project,source)
    editing.merge_category(project,source,target)
    assert project.asset(asset['id'])['state']=='pending'
    assert project.boxes(asset['active_version_id'])[0].category_id==target


def test_backup_restore(imported,tmp_path):
    from tushu.infrastructure.backup import backup,restore
    reviewed(imported)
    folder=backup(imported,tmp_path/'备份')
    target=restore(folder,tmp_path/'恢复')
    restored=Project(target)
    try:
        assert len(restored.assets())==4
        assert all(a['state'] in REVIEWED for a in restored.assets())
        assert not quality.check(restored)['errors']
    finally: restored.close()


def test_hidden_review_and_rename(imported):
    project=imported; asset=project.assets()[0]
    with pytest.raises(ValueError): editing.review(project,asset['id'],hidden=True)
    with pytest.raises(ValueError): editing.rename_assets(project,[asset['id']],prefix='bad/')
    mapping=editing.rename_assets(project,[asset['id']],prefix='动物_',apply=True)
    assert project.asset(asset['id'])['display_name']==mapping[0]['new']
