from pathlib import Path
from PyInstaller.utils.hooks import collect_all,copy_metadata
root=Path(SPECPATH).parent
datas=[(str(root/'src/tushu/web/static'),'tushu/web/static'),
       (str(root/'models/yolox-s-coco'),'models/yolox-s-coco'),(str(root/'licenses'),'licenses')]
for package in ('tushu','fastapi','starlette','pydantic','uvicorn','Pillow','numpy','opencv-python-headless','onnxruntime','PyYAML','httpx'):
    datas+=copy_metadata(package)
ort_data,ort_bins,ort_imports=collect_all('onnxruntime')
a=Analysis([str(root/'src/tushu/web/launcher.py')],pathex=[str(root/'src')],binaries=ort_bins,datas=datas+ort_data,
 hiddenimports=ort_imports+['uvicorn.logging','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl','uvicorn.lifespan.on'],
 excludes=['pytest','onnx','pycocotools','tkinter','PySide6','matplotlib','torch','scipy'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='图枢网页',debug=False,strip=False,upx=False,console=False,target_arch='arm64')
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='图枢网页')
app=BUNDLE(coll,name='图枢网页.app',bundle_identifier='local.tushu.web',info_plist={'CFBundleShortVersionString':'1.1.0','CFBundleVersion':'1.1.0','NSHighResolutionCapable':True})
