"""Run only in .validation-venv; torchvision/PyTorch are not shipped with the app."""
from pathlib import Path
import importlib.metadata
import json
import torch
from torchvision.datasets import CocoDetection
from torch.utils.data import DataLoader

root=Path(__file__).resolve().parents[1]
report=json.loads((root/'acceptance/engineering-report.json').read_text())
dataset_root=Path(report['checks']['coco']['path'])
results={}
for split in ('train','val'):
    dataset=CocoDetection(str(dataset_root),str(dataset_root/f'annotations/instances_{split}.json'))
    loader=DataLoader(dataset,batch_size=8,num_workers=0,collate_fn=lambda batch:tuple(zip(*batch)))
    images=boxes=negative=0
    for batch_images,targets in loader:
        for image,target in zip(batch_images,targets):
            assert image.mode=='RGB'
            images+=1; boxes+=len(target); negative+=not target
            for item in target:
                assert item['category_id']==1 and item['bbox'][2]>0 and item['bbox'][3]>0
    results[split]={'images':images,'boxes':boxes,'negative_images':negative}
assert sum(r['images'] for r in results.values())==500
assert sum(r['negative_images'] for r in results.values())==100
result={'passed':True,'loader':'torchvision.datasets.CocoDetection + torch.utils.data.DataLoader',
        'versions':{p:importlib.metadata.version(p) for p in ('torch','torchvision','pycocotools')},
        'splits':results,'source':'https://docs.pytorch.org/vision/stable/generated/torchvision.datasets.CocoDetection.html',
        'licenses':{'torch':'BSD-3-Clause','torchvision':'BSD-3-Clause','pycocotools':'BSD-2-Clause'},
        'note':'Only dataset loading tested; no training or accuracy evaluation. Test environment not bundled.'}
(root/'docs/training-loader-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
