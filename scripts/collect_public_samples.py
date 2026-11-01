"""Download explicitly selected Wikimedia Commons files with provenance. No API keys."""
from pathlib import Path
import hashlib
import io
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import httpx
from PIL import Image,ImageOps

root=Path(__file__).resolve().parents[1]
folder=root/'samples/public';folder.mkdir(parents=True,exist_ok=True)
items=[
 {'source_file':'Felis_catus-cat_on_snow.jpg','file':'雪地中的猫.jpg','author':'Von.grzanka','license':'CC BY-SA 3.0','license_url':'https://creativecommons.org/licenses/by-sa/3.0/','expected_broad_category':'动物'},
 {'source_file':'YellowLabradorLooking_new.jpg','file':'拉布拉多犬.jpg','author':'Original photograph: Elf; derivative work: Djmirko; retouch: FT2','license':'CC BY-SA 3.0','license_url':'https://creativecommons.org/licenses/by-sa/3.0/','expected_broad_category':'动物'},
 {'source_file':'Sunflower_with_Bee.jpg','file':'向日葵与蜜蜂.jpg','author':'Alabama Extension / Justin Miller','license':'CC0 1.0','license_url':'https://creativecommons.org/publicdomain/zero/1.0/','expected_broad_category':'植物'},
 {'source_file':'Cup_with_Lid.jpg','file':'银质带盖杯.jpg','author':'National Museum in Kraków / Christian Franck (historic object)','license':'CC0 1.0','license_url':'https://creativecommons.org/publicdomain/zero/1.0/','expected_broad_category':'物品'},
]
def download(item):
 name=item['source_file']; h=hashlib.md5(name.encode()).hexdigest()
 url=f'https://upload.wikimedia.org/wikipedia/commons/{h[0]}/{h[:2]}/{urllib.parse.quote(name)}?download=1'
 item['source_page']='https://commons.wikimedia.org/wiki/File:'+urllib.parse.quote(name)
 item['download_url']=url
 if (folder/item['file']).is_file():
  image=Image.open(folder/item['file']);item.update(sha256=hashlib.sha256((folder/item['file']).read_bytes()).hexdigest(),distributed_size=list(image.size),modifications='Resized to longest edge <=1600, RGB JPEG re-encoding, metadata removed',collected_at='2026-11-01',purpose='Functional smoke test, not accuracy ground truth');return item
 with httpx.Client(timeout=httpx.Timeout(45,connect=10),follow_redirects=True,headers={'User-Agent':'Tushu/1.1 public image annotation sample collection'},trust_env=True) as client:
  response=client.get(url)
  if response.status_code==429:
   import time
   time.sleep(2)
   url=f'https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{urllib.parse.quote(name)}/960px-{urllib.parse.quote(name)}'
   item['download_url']=url
   response=client.get(url)
  response.raise_for_status()
 image=ImageOps.exif_transpose(Image.open(io.BytesIO(response.content))).convert('RGB')
 original=list(image.size);image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
 path=folder/item['file'];Image.frombytes('RGB',image.size,image.tobytes()).save(path,'JPEG',quality=92)
 item.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),original_size=original,distributed_size=list(image.size),
             modifications='EXIF direction baked, resized to longest edge <=1600, RGB JPEG re-encoding, metadata removed',
             collected_at='2026-11-01',purpose='Functional smoke test and interface demonstration, not accuracy ground truth')
 print(item['file'],image.size,flush=True)
 return item
if __name__=='__main__':
 results=list(ThreadPoolExecutor(max_workers=1).map(download,items))
 (folder/'sources.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 lines=['# 公开示例图片来源与许可','', '只用于功能演示和真实调用测试，不构成物种识别准确率测试集。', '']
 for item in results:
  lines += [f"## {item['file']}",f"作者：{item['author']}。许可：{item['license']}（{item['license_url']}）。",f"来源：{item['source_page']}",f"修改：{item['modifications']}",f"SHA-256：{item['sha256']}",'']
 lines+=['CC BY-SA 图片及其缩放重编码副本按原许可单独提供，不随业务源码许可改写。', '图片内可能含有多个对象；expected_broad_category 仅用于样例归类，不是精确框或模型准确率真值。']
 (folder/'ATTRIBUTION.md').write_text('\n'.join(lines))
