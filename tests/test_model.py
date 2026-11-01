import ast
import json
from pathlib import Path
import shutil
from dataclasses import replace
import cv2
import numpy as np
import pytest
from PIL import Image

from tushu.inference.yolox import YoloX,preprocess,decode,postprocess
from tushu.services import inferencing,editing
from tushu.domain.entities import Box

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def model():
    return YoloX(ROOT/'models/yolox-s-coco')


def official_functions(path,names):
    tree=ast.parse(path.read_text())
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    module=ast.Module(body=functions,type_ignores=[])
    scope={'np':np,'cv2':cv2}
    exec(compile(module,str(path),'exec'),scope)
    return scope


def test_official_numeric_parity(model):
    reference=ROOT/'licenses/yolox-reference'
    pre=official_functions(reference/'data_augment.py',{'preproc'})['preproc']
    post=official_functions(reference/'demo_utils.py',{'nms','demo_postprocess','multiclass_nms_class_aware'})
    image=Image.open(ROOT/'samples/public/雪地中的猫.jpg').convert('RGB')
    ours,ratio=preprocess(image)
    expected,expected_ratio=pre(np.asarray(image)[:,:,::-1].copy(),(640,640))
    np.testing.assert_array_equal(ours[0],expected)
    assert ratio==expected_ratio
    raw=model.session.run(['output'],{'images':ours})[0]
    np.testing.assert_array_equal(decode(raw),post['demo_postprocess'](raw.copy(),(640,640))[0])
    pred=post['demo_postprocess'](raw.copy(),(640,640))[0]
    coords=np.concatenate((pred[:,:2]-pred[:,2:4]/2,pred[:,:2]+pred[:,2:4]/2),1)/ratio
    ref=post['multiclass_nms_class_aware'](coords,pred[:,4:5]*pred[:,5:],.45,.3)
    ref=ref[np.argsort(ref[:,4])[::-1]]
    ours,truncated=postprocess(raw,ratio,image.width,image.height)
    assert not truncated and len(ours)==len(ref)>0
    for actual,expected in zip(ours,ref):
        clipped=expected[:4].copy(); clipped[[0,2]]=np.clip(clipped[[0,2]],0,image.width); clipped[[1,3]]=np.clip(clipped[[1,3]],0,image.height)
        np.testing.assert_allclose(actual['xyxy'],clipped,atol=1e-5)
        assert actual['score']==pytest.approx(expected[4]) and actual['class_id']==expected[5]


def test_manifest_tamper_rejected(tmp_path):
    folder=tmp_path/'model'
    shutil.copytree(ROOT/'models/yolox-s-coco',folder)
    manifest=json.loads((folder/'model_manifest.json').read_text()); manifest['sha256']='0'*64
    (folder/'model_manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='SHA-256'): YoloX(folder)
    manifest['decoded']=True; (folder/'model_manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='契约'): YoloX(folder)


def test_real_inference_and_manual_protection(imported,model):
    project=imported; category=project.categories()[0]['id']; asset=project.assets()[0]
    mapping={i:category for i in range(80)}
    inferencing.register(project,model,mapping)
    manual=Box(category,1,1,10,20)
    auto=Box(category,20,20,40,40,source='model',score=.8,model_id=model.id,model_class=16)
    edited=replace(auto,id='edited',edited=True)
    project.save_boxes(asset['id'],[manual,auto,edited],0)
    report=inferencing.run(project,[asset['id']],model,mapping)
    assert report['success']==[asset['id']]
    saved=project.boxes(asset['active_version_id'])
    assert manual.id in {b.id for b in saved} and edited.id in {b.id for b in saved} and auto.id not in {b.id for b in saved}
    assert project.asset(asset['id'])['state']=='pending'
