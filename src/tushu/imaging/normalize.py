from __future__ import annotations

import hashlib
import io
from pathlib import Path
import warnings
from PIL import Image, ImageCms, ImageOps, features

Image.MAX_IMAGE_PIXELS = 30_000_000
SUPPORTED = {'.jpg': 'JPEG','.jpeg':'JPEG','.png':'PNG','.webp':'WEBP'}


def inspect(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError('跳过符号链接或非普通文件')
    size = path.stat().st_size
    if size > 100 * 1024**2:
        raise ValueError('文件超过 100 MiB')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as image:
            width,height = image.size
            if image.format not in {'JPEG','PNG','WEBP'}:
                raise ValueError('仅支持 JPEG、PNG、静态 WebP')
            if SUPPORTED.get(path.suffix.lower()) != image.format:
                raise ValueError('扩展名与实际图像格式不一致')
            if getattr(image,'n_frames',1) != 1 or getattr(image,'is_animated',False):
                raise ValueError('不支持动画或多帧图像')
            if width*height > 30_000_000 or max(width,height) > 10_000:
                raise ValueError('图像超过 3000 万像素或边长 10000 像素')
            if image.mode not in ('RGB','RGBA','L','LA','P'):
                raise ValueError(f'不支持的颜色模式 {image.mode}')
            if image.info.get('icc_profile'):
                try:
                    ImageCms.ImageCmsProfile(io.BytesIO(image.info['icc_profile']))
                except Exception as error:
                    raise ValueError('ICC 配置损坏，请先修复色彩配置') from error
            result = {'name':path.name,'size':size,'width':width,'height':height,
                      'mode':image.mode,'format':image.format}
            image.verify()
    return result


def normalize(path: Path) -> tuple[Image.Image,str]:
    inspect(path)
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original)
        alpha = image.convert('RGBA').getchannel('A') if 'A' in image.getbands() or 'transparency' in image.info else None
        color = 'embedded ICC → sRGB' if original.info.get('icc_profile') else 'assumed sRGB'
        if original.info.get('icc_profile'):
            profile = ImageCms.ImageCmsProfile(io.BytesIO(original.info['icc_profile']))
            image = ImageCms.profileToProfile(image.convert('RGB'),profile,ImageCms.createProfile('sRGB'),outputMode='RGB')
        else:
            image = image.convert('RGB')
        if alpha is not None:
            image.putalpha(alpha)
        # A clean image object deliberately drops EXIF, ICC and source paths.
        clean = Image.frombytes(image.mode,image.size,image.tobytes())
        return clean,color


def pixel_hash(image: Image.Image) -> str:
    rgba = image.convert('RGBA')
    result = hashlib.sha256(f'{rgba.width},{rgba.height},RGBA'.encode())
    result.update(rgba.tobytes())
    return result.hexdigest()


def encode(image, path, fmt='PNG', quality=90, background='#ffffff', lossless=False, compress_level=6):
    fmt = fmt.upper()
    if fmt not in ('PNG','JPEG','WEBP'):
        raise ValueError('不支持的编码格式')
    if not 1 <= quality <= 95 or not 0 <= compress_level <= 9:
        raise ValueError('质量应为 1—95，PNG 压缩等级应为 0—9')
    options = {}
    if fmt == 'JPEG':
        if image.mode == 'RGBA':
            base = Image.new('RGB',image.size,background)
            base.paste(image,mask=image.getchannel('A'))
            image = base
        else:
            image = image.convert('RGB')
        options = {'quality':quality}
    elif fmt == 'WEBP':
        if not features.check('webp'):
            raise ValueError('环境缺少 WebP 编码器')
        options = {'quality':quality,'lossless':lossless}
    else:
        options = {'compress_level':compress_level}
    image.save(path,format=fmt,**options)
