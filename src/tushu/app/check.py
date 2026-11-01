from __future__ import annotations
import importlib.metadata
import json
import platform
from PIL import features


def environment():
    packages=['tushu','PySide6-Essentials','Pillow','numpy','opencv-python-headless','onnxruntime','PyYAML']
    return {'system':platform.platform(),'machine':platform.machine(),'python':platform.python_version(),
            'packages':{name:importlib.metadata.version(name) for name in packages},
            'encoders':{'jpeg':features.check('jpg'),'png':features.check('zlib'),'webp':features.check('webp')}}


def main():
    print(json.dumps(environment(),ensure_ascii=False,indent=2))
