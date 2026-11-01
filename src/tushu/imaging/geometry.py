from __future__ import annotations

from dataclasses import replace
import numpy as np
from PIL import Image, ImageEnhance


def transform(image, boxes, operations, retained_threshold=0.20):
    matrix = np.eye(3,dtype=np.float64)
    current = image.copy()
    result = [replace(b) for b in boxes]
    removed = []
    low_area = []
    for operation in operations:
        name = operation['op']
        width,height = current.size
        affine = np.eye(3,dtype=np.float64)
        if name == 'resize':
            if 'longest' in operation:
                scale = int(operation['longest']) / max(width,height)
                size = (max(1,round(width*scale)),max(1,round(height*scale)))
            else:
                size = (int(operation['width']),int(operation['height']))
            if min(size)<1 or max(size)>10000 or size[0]*size[1]>30_000_000:
                raise ValueError('输出尺寸超限')
            affine = np.diag([size[0]/width,size[1]/height,1.])
            current = current.resize(size,Image.Resampling.LANCZOS)
        elif name == 'crop':
            x,y,w,h = [int(operation[k]) for k in ('x','y','width','height')]
            if x<0 or y<0 or w<1 or h<1 or x+w>width or y+h>height:
                raise ValueError('裁剪矩形不能超出图片范围')
            affine[0,2],affine[1,2] = -x,-y
            current = current.crop((x,y,x+w,y+h))
        elif name == 'flip_h':
            affine = np.array([[-1,0,width],[0,1,0],[0,0,1]],dtype=float)
            current = current.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        elif name == 'flip_v':
            affine = np.array([[1,0,0],[0,-1,height],[0,0,1]],dtype=float)
            current = current.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        elif name == 'rotate':
            angle = int(operation['angle'])
            matrices = {90:[[0,-1,height],[1,0,0],[0,0,1]],
                        180:[[-1,0,width],[0,-1,height],[0,0,1]],
                        270:[[0,1,0],[-1,0,width],[0,0,1]]}
            if angle not in matrices:
                raise ValueError('旋转仅支持顺时针 90、180、270 度')
            affine = np.array(matrices[angle],dtype=float)
            current = current.transpose({90:Image.Transpose.ROTATE_270,
                180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_90}[angle])
        elif name in ('brightness','contrast'):
            factor = float(operation['factor'])
            if not .8 <= factor <= 1.2:
                raise ValueError('亮度/对比度系数应在 0.8—1.2 之间')
            enhancer = ImageEnhance.Brightness if name == 'brightness' else ImageEnhance.Contrast
            current = enhancer(current).enhance(factor)
        elif name == 'encode':
            continue
        else:
            raise ValueError(f'不支持的操作：{name}')
        transformed = []
        for box in result:
            corners = np.array([[box.x1,box.y1,1],[box.x2,box.y1,1],
                                [box.x1,box.y2,1],[box.x2,box.y2,1]]) @ affine.T
            raw_min,raw_max = corners[:,:2].min(axis=0),corners[:,:2].max(axis=0)
            clipped_min = np.maximum(raw_min,0)
            clipped_max = np.minimum(raw_max,current.size)
            dimensions = clipped_max-clipped_min
            ratio = max(0,dimensions[0])*max(0,dimensions[1])/max(1e-12,np.prod(raw_max-raw_min))
            if min(dimensions)<1 or ratio<retained_threshold:
                removed.append(box.id)
                if 0 < ratio < retained_threshold:
                    low_area.append(box.id)
                continue
            transformed.append(replace(box,x1=float(clipped_min[0]),y1=float(clipped_min[1]),
                                       x2=float(clipped_max[0]),y2=float(clipped_max[1])))
        result = transformed
        matrix = affine @ matrix
    return current,result,{'matrix':matrix.tolist(),'input_size':list(image.size),
                          'output_size':list(current.size),'removed':removed,'low_area':low_area,
                          'operations':operations,'algorithm':'orthogonal-1'}
