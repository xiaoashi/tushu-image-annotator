from __future__ import annotations

import json
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

from tushu.infrastructure.files import sha256

CONTRACT = {
    'adapter':'yolox-onnx-1','input_name':'images','input_shape':[1,3,640,640],
    'input_dtype':'float32','color_order':'BGR','value_range':[0,255],
    'normalization':{'mean':[0,0,0],'std':[1,1,1]},
    'resize':'top-left-letterbox','padding':114,'interpolation':'cv2.INTER_LINEAR',
    'inverse':'official_scalar_ratio','output_name':'output','output_layout':'N,8400,5+C',
    'decoded':False,'strides':[8,16,32],'nms':'class-aware-inclusive-pixel',
}


def preprocess(image: Image.Image,background='#ffffff'):
    if image.mode=='RGBA':
        base = Image.new('RGB',image.size,background)
        base.paste(image,mask=image.getchannel('A'))
    else:
        base = image.convert('RGB')
    bgr = np.asarray(base)[:,:,::-1].copy()
    ratio = min(640/base.height,640/base.width)
    resized = cv2.resize(bgr,(int(base.width*ratio),int(base.height*ratio)),interpolation=cv2.INTER_LINEAR)
    padded = np.full((640,640,3),114,dtype=np.uint8)
    padded[:resized.shape[0],:resized.shape[1]] = resized
    return np.ascontiguousarray(padded.transpose(2,0,1),dtype=np.float32)[None],ratio


def decode(raw):
    output = raw.copy()
    start = 0
    for stride in (8,16,32):
        size = 640//stride
        grid = np.array([(x,y) for y in range(size) for x in range(size)],dtype=np.float32)
        end = start+len(grid)
        output[0,start:end,:2] = (output[0,start:end,:2]+grid)*stride
        output[0,start:end,2:4] = np.exp(output[0,start:end,2:4])*stride
        start = end
    if not np.isfinite(output).all():
        raise ValueError('模型输出包含 NaN/Inf，未接收本图结果')
    return output[0]


def postprocess(raw,ratio,width,height,threshold=.30,nms=.45,limit=300):
    if not 0<threshold<1 or not 0<nms<1:
        raise ValueError('模型阈值须在 0—1 之间')
    decoded = decode(raw)
    scores = decoded[:,4:5]*decoded[:,5:]
    coordinates = np.concatenate((decoded[:,:2]-decoded[:,2:4]/2,
                                  decoded[:,:2]+decoded[:,2:4]/2),axis=1)/ratio
    detections = []
    for category in range(scores.shape[1]):
        selected = np.flatnonzero(scores[:,category]>threshold)
        order = selected[np.argsort(scores[selected,category])[::-1]]
        while len(order):
            best = int(order[0])
            detections.append((coordinates[best].copy(),float(scores[best,category]),category))
            remaining = order[1:]
            if not len(remaining):
                break
            minimum = np.maximum(coordinates[best,:2],coordinates[remaining,:2])
            maximum = np.minimum(coordinates[best,2:],coordinates[remaining,2:])
            intersection = np.prod(np.maximum(0,maximum-minimum+1),axis=1)
            area_best = np.prod(coordinates[best,2:]-coordinates[best,:2]+1)
            area_remaining = np.prod(coordinates[remaining,2:]-coordinates[remaining,:2]+1,axis=1)
            overlaps = intersection/(area_best+area_remaining-intersection)
            order = remaining[overlaps<=nms]
    detections.sort(key=lambda item:item[1],reverse=True)
    valid = []
    for coords,score,category in detections:
        coords[[0,2]]=np.clip(coords[[0,2]],0,width)
        coords[[1,3]]=np.clip(coords[[1,3]],0,height)
        if coords[2]-coords[0]>=1 and coords[3]-coords[1]>=1 and 0<=score<=1:
            valid.append({'xyxy':coords.tolist(),'score':score,'class_id':category})
    return valid[:limit],len(valid)>limit


class YoloX:
    def __init__(self,folder):
        self.folder = Path(folder).resolve()
        for name in ('model.onnx','model_manifest.json','class_names.json','LICENSE','SOURCE.md'):
            if not (self.folder/name).is_file():
                raise ValueError(f'模型包缺少 {name}')
        self.manifest = json.loads((self.folder/'model_manifest.json').read_text('utf-8'))
        self.classes = json.loads((self.folder/'class_names.json').read_text('utf-8'))
        for key in ('id','version','sha256','framework_version','license_source','weight_source'):
            if not self.manifest.get(key):
                raise ValueError(f'模型 manifest 缺少 {key}')
        for key,value in CONTRACT.items():
            if self.manifest.get(key)!=value:
                raise ValueError(f'不受支持的模型契约：{key}，只支持经验证的 YOLOX 640 适配器')
        if not isinstance(self.classes,list) or not all(isinstance(c,str) and c for c in self.classes):
            raise ValueError('模型类名列表无效')
        if self.manifest.get('num_classes')!=len(self.classes):
            raise ValueError('模型类别数量不一致')
        if sha256(self.folder/'model.onnx')!=self.manifest['sha256']:
            raise ValueError('模型 SHA-256 不匹配')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(self.folder/'model.onnx'),sess_options=options,
                                           providers=['CPUExecutionProvider'])
        inputs,outputs = self.session.get_inputs(),self.session.get_outputs()
        if len(inputs)!=1 or inputs[0].shape!=[1,3,640,640] or inputs[0].name!='images' or inputs[0].type!='tensor(float)':
            raise ValueError('模型真实输入与 manifest 不匹配')
        if len(outputs)!=1 or outputs[0].name!='output' or outputs[0].shape!=[1,8400,5+len(self.classes)]:
            raise ValueError('模型真实输出与 manifest 不匹配')
        self.id = self.manifest['id']
        warm = self.session.run(['output'],{'images':np.zeros((1,3,640,640),np.float32)})[0]
        if not np.isfinite(warm).all():
            raise ValueError('模型试运行输出无效')

    def predict(self,image,threshold=.30,nms=.45,background='#ffffff'):
        tensor,ratio = preprocess(image,background)
        raw = self.session.run(['output'],{'images':tensor})[0]
        return postprocess(raw,ratio,image.width,image.height,threshold,nms)
