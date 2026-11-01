"""Independent dataset parser. No imports of exporting or geometry algorithms."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from PIL import Image
from tushu.infrastructure.files import sha256


def validate(root):
    root = Path(root).resolve()
    errors = []
    def fail(message):
        errors.append(message)
    try:
        manifest = json.loads((root/'export_manifest.json').read_text('utf-8'))
        mapping = json.loads((root/'class_mapping.json').read_text('utf-8'))
        plan = json.loads((root/'split_manifest.json').read_text('utf-8'))
        if [c['yolo_id'] for c in mapping]!=list(range(len(mapping))):
            fail('YOLO 类别编号不连续')
        if [c['coco_id'] for c in mapping]!=list(range(1,len(mapping)+1)):
            fail('COCO 类别编号不连续')
        category_ids = {c['id'] for c in mapping}
        groups = {'train':set(),'val':set()}
        pixels = {'train':set(),'val':set()}
        assets = {'train':set(),'val':set()}
        roots = {'train':set(),'val':set()}
        filenames = set()
        expected_files = set()
        observed = {}
        max_error = 0.
        if manifest['format']=='coco':
            annotation_ids = set()
            image_ids = set()
            for split in ('train','val'):
                coco = json.loads((root/f'annotations/instances_{split}.json').read_text('utf-8'))
                if {c['id'] for c in coco['categories']}!=set(range(1,len(mapping)+1)):
                    fail('COCO 类别列表不一致')
                for image in coco['images']:
                    if image['id'] in image_ids:
                        fail('COCO image ID 重复')
                    image_ids.add(image['id'])
                    if image['file_name'] in observed:
                        fail('COCO 文件名重复')
                    observed[image['file_name']]={'image':image,'boxes':[],'split':split}
                image_lookup = {im['id']:im['file_name'] for im in coco['images']}
                for annotation in coco['annotations']:
                    if annotation['id'] in annotation_ids:
                        fail('COCO annotation ID 重复')
                    annotation_ids.add(annotation['id'])
                    if annotation['image_id'] not in image_lookup:
                        fail('COCO 悬空 image 引用')
                        continue
                    x,y,w,h = annotation['bbox']
                    if not all(math.isfinite(v) for v in (x,y,w,h,annotation['area'])) or min(w,h)<1:
                        fail('COCO 非法框')
                    if abs(annotation['area']-w*h)>max(1e-6,w*h*1e-8) or annotation['iscrowd']!=0:
                        fail('COCO 面积/iscrowd 错误')
                    category = annotation['category_id']-1
                    if category not in range(len(mapping)):
                        fail('COCO 无效类别引用')
                        continue
                    observed[image_lookup[annotation['image_id']]]['boxes'].append(
                        (mapping[category]['id'],[x,y,x+w,y+h]))
        elif manifest['format']!='yolo':
            fail('未知导出格式')
        for item in manifest['images']:
            relative = item['file']
            path = (root/relative).resolve()
            if not path.is_relative_to(root):
                fail('图片路径穿越')
                continue
            expected_files.add(relative)
            split = item['split']
            if split not in groups:
                fail('未知集合')
                continue
            if relative.casefold() in filenames:
                fail('文件名大小写碰撞')
            filenames.add(relative.casefold())
            groups[split].add(item['group_id'])
            pixels[split].add(item['pixel_hash'])
            assets[split].add(item['asset_id'])
            roots[split].add(item['root_asset_id'])
            if plan['assignments'].get(item['group_id'])!=split:
                fail('划分清单与图片分组不一致')
            if item['parent_asset_id'] and split!='train':
                fail('增强图进入验证组')
            if sha256(path)!=item['sha256']:
                fail(f'图片摘要不一致：{relative}')
            with Image.open(path) as image:
                image.load()
                width,height = image.size
                if [width,height]!=[item['width'],item['height']]:
                    fail('图片实际尺寸与清单不一致')
                rgba=image.convert('RGBA')
                pixel=hashlib.sha256(f'{width},{height},RGBA'.encode())
                pixel.update(rgba.tobytes())
                if pixel.hexdigest()!=item['pixel_hash']:
                    fail('规范化像素摘要与清单不一致')
            parsed = []
            if manifest['format']=='yolo':
                label = root/'labels'/split/(Path(relative).stem+'.txt')
                for line in label.read_text('utf-8').splitlines():
                    tokens = line.split()
                    if len(tokens)!=5:
                        fail('YOLO 每行必须恰好 5 列')
                        continue
                    category = int(tokens[0])
                    values = [float(v) for v in tokens[1:]]
                    if category not in range(len(mapping)) or not all(math.isfinite(v) for v in values):
                        fail('YOLO 无效类别/数值')
                        continue
                    cx,cy,w,h = values
                    if not 0<=cx<=1 or not 0<=cy<=1 or not 0<w<=1 or not 0<h<=1:
                        fail('YOLO 归一化数值越界')
                    parsed.append((mapping[category]['id'],[(cx-w/2)*width,(cy-h/2)*height,
                                                          (cx+w/2)*width,(cy+h/2)*height]))
            else:
                if relative not in observed:
                    fail('COCO 遗漏图片/负样本')
                    continue
                entry = observed[relative]
                if entry['split']!=split or entry['image']['width']!=width or entry['image']['height']!=height:
                    fail('COCO 图片元数据不一致')
                parsed = entry['boxes']
            expected = item['boxes']
            if len(expected)!=len(parsed) or item['negative']!=(len(parsed)==0):
                fail('框数量/负样本数量不一致')
            remaining = list(parsed)
            for box in expected:
                if box['category_id'] not in category_ids:
                    fail('真值类别不在映射中')
                    continue
                coords = [box[k] for k in ('x1','y1','x2','y2')]
                matches = [(index,max(abs(a-b) for a,b in zip(coords,actual)))
                           for index,(category,actual) in enumerate(remaining) if category==box['category_id']]
                if not matches:
                    fail('回读框类别/数量不符')
                    continue
                match,difference = min(matches,key=lambda value:value[1])
                max_error=max(max_error,difference)
                if difference>1:
                    fail('回读坐标误差超过 1 像素')
                _,actual = remaining.pop(match)
                if actual[0]<-1e-4 or actual[1]<-1e-4 or actual[2]>width+1e-4 or actual[3]>height+1e-4:
                    fail('回读框越界')
        for kind,sets in (('同源组',groups),('像素重复组',pixels),('资产',assets),('根来源',roots)):
            if sets['train']&sets['val']:
                fail(kind+'跨 train/val 泄漏')
        actual_files = {str(p.relative_to(root)) for p in (root/'images').rglob('*') if p.is_file()}
        if actual_files!=expected_files:
            fail('图片目录文件数量与清单不一致')
        if manifest['format']=='coco' and set(observed)!=expected_files:
            fail('COCO 图片数量与清单不一致')
        if manifest['format']=='yolo':
            actual_labels = {str(p.relative_to(root/'labels')) for p in (root/'labels').rglob('*.txt')}
            expected_labels = {f"{im['split']}/{Path(im['file']).stem}.txt" for im in manifest['images']}
            if actual_labels!=expected_labels:
                fail('标签文件数量与清单不一致')
        counts = Counter(item['split'] for item in manifest['images'])
        return {'passed':not errors,'errors':errors,'images':len(manifest['images']),
                'negative_images':sum(item['negative'] for item in manifest['images']),
                'boxes':sum(len(item['boxes']) for item in manifest['images']),
                'splits':dict(counts),'max_coordinate_error_px':max_error,'validator':'independent-reader-1'}
    except Exception as error:
        fail(f'读取失败：{type(error).__name__}: {error}')
        return {'passed':False,'errors':errors,'validator':'independent-reader-1'}
