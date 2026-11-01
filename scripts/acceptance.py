"""Reproducible engineering acceptance, synthetic data is NOT model accuracy ground truth."""
from __future__ import annotations
from pathlib import Path
import json
import statistics
import subprocess
import sys
import time
from PIL import Image,ImageDraw
import numpy as np
from pycocotools.coco import COCO

from tushu.app.check import environment
from tushu.domain.entities import Box
from tushu.repositories.project import Project
from tushu.services import importing,editing,inferencing,splitting,processing
from tushu.datasets.exporter import export
from tushu.inference.yolox import YoloX
from tushu.infrastructure.files import write_json
from tushu.infrastructure.tasks import TaskContext

ROOT=Path(__file__).resolve().parents[1]
output=ROOT/'acceptance'
output.mkdir(exist_ok=True)
source=output/'工程测试图片'
source.mkdir(exist_ok=True)
for index in range(500):
    image=Image.new('RGBA' if index%4==0 else 'RGB',(320+index%19,240+index%13),
                    (index%256,index//256*90,140,180) if index%4==0 else (index%256,index//256*90,140))
    draw=ImageDraw.Draw(image)
    draw.rectangle((10,15,70+index%17,90),outline='white',width=3)
    draw.text((20,120),f'Engineering fixture {index}',fill='white')
    fmt=index%3
    if fmt==0: image.save(source/f'合成_{index:04d}.png')
    elif fmt==1: image.convert('RGB').save(source/f'合成_{index:04d}.jpg',quality=90)
    else: image.save(source/f'合成_{index:04d}.webp',lossless=True)

report={'environment':environment(),'dataset':'500 synthetic engineering fixtures; NOT a model accuracy evaluation',
        'count':500,'times':{},'checks':{}}
project=Project.create(output,'工程验收样本（合成图，非模型准确率评估）')
try:
    started=time.perf_counter(); rows=importing.scan(source)
    report['times']['scan_seconds']=time.perf_counter()-started
    started=time.perf_counter(); result=importing.import_files(project,rows)
    report['times']['import_seconds']=time.perf_counter()-started
    assert len(result['added'])==500 and not result['failed']
    model=YoloX(ROOT/'models/yolox-s-coco')
    category=editing.add_category(project,'工程矩形','engineering_rectangle')
    mapping={i:category for i in range(80)}
    inferencing.register(project,model,mapping)
    started=time.perf_counter()
    def progress(done,total,name):
        if done%50==0: print(f'inference {done}/{total}',flush=True)
    inference=inferencing.run(project,[a['id'] for a in project.assets()],model,mapping,
                               context=TaskContext(project,'acceptance_inference',progress))
    report['times']['inference_500_seconds']=time.perf_counter()-started
    assert len(inference['success'])==500 and not inference['failed']
    seconds=np.array(inference['seconds'][1:101])
    report['times']['warm_100_p50_seconds']=float(np.percentile(seconds,50))
    report['times']['warm_100_p95_seconds']=float(np.percentile(seconds,95))
    report['checks']['real_inference_500']=True
    # Explicit deterministic engineering annotations, not promoted model output or asserted human reviews.
    for index,asset in enumerate(project.assets()):
        boxes=[] if index%5==0 else [Box(category,10,15,70+index%17,90)]
        project.save_boxes(asset['id'],boxes,asset['revision'],'engineering_fixture_ground_truth')
        editing.review(project,asset['id'])
    plan=splitting.create(project)
    for fmt in ('yolo','coco'):
        started=time.perf_counter()
        dataset=export(project,output/'datasets',fmt,acknowledge_warnings=True)
        report['times'][fmt+'_export_seconds']=time.perf_counter()-started
        report['checks'][fmt]=dataset
    coco_root=Path(report['checks']['coco']['path'])
    for split in ('train','val'):
        dataset=COCO(str(coco_root/f'annotations/instances_{split}.json'))
        assert dataset.getImgIds()
        for image in dataset.loadImgs(dataset.getImgIds()):
            with Image.open(coco_root/image['file_name']) as decoded:
                assert decoded.size==(image['width'],image['height'])
    report['checks']['target_loader']='pycocotools '+__import__('importlib.metadata',fromlist=['version']).version('pycocotools')
    # A standalone move/relocation needs no app or PyYAML.
    yolo_root=Path(report['checks']['yolo']['path'])
    subprocess.run([sys.executable,str(yolo_root/'relocate_dataset.py')],check=True)
    import yaml
    assert Path(yaml.safe_load((yolo_root/'data.yaml').read_text())['path'])==yolo_root
    report['checks']['relocation']=True
    report['project']=str(project.root)
    report['passed']=True
finally:
    project.close()
    write_json(output/'engineering-report.json',report)
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
