"""Explicit installation-time download; never invoked automatically at app startup."""
from pathlib import Path
import hashlib
import json
import urllib.request

root=Path(__file__).resolve().parents[1]
folder=root/'models/yolox-s-coco'
manifest=json.loads((folder/'model_manifest.json').read_text())
target=folder/'model.onnx'
if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==manifest['sha256']:
    print('Local model already verified.')
else:
    temporary=folder/'model.onnx.download'
    try:
        urllib.request.urlretrieve(manifest['weight_source'],temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=manifest['sha256']:
            raise ValueError('Downloaded model SHA-256 mismatch; refusing installation')
        temporary.replace(target)
        print('Official model downloaded and verified. See model SOURCE.md and LICENSE.')
    finally:
        temporary.unlink(missing_ok=True)
