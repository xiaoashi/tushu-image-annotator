"""Build a strict local manifest for the official, already downloaded YOLOX-S asset."""
from pathlib import Path
import ast
import json
from tushu.inference.yolox import CONTRACT
from tushu.infrastructure.files import sha256, write_json

root = Path(__file__).resolve().parents[1]
folder = root/'models/yolox-s-coco'
classes_tree = ast.parse((root/'licenses/yolox-reference/coco_classes.py').read_text())
classes = ast.literal_eval(next(n.value for n in classes_tree.body if isinstance(n,ast.Assign)))
write_json(folder/'class_names.json',list(classes))
manifest = dict(CONTRACT,id='yolox-s-coco-0.1.1rc0',version='0.1.1rc0',
                sha256=sha256(folder/'model.onnx'),framework_version='YOLOX 0.1.1rc0 official ONNX',
                num_classes=len(classes),license_source='https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE',
                weight_source='https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx')
write_json(folder/'model_manifest.json',manifest)
(folder/'SOURCE.md').write_text('''# Model provenance
Official YOLOX-S ONNX release 0.1.1rc0, downloaded from the weight_source URL in model_manifest.json.
Repository: https://github.com/Megvii-BaseDetection/YOLOX
Upstream code is Apache-2.0; LICENSE is included. This release publishes the weight through the same official
repository; no separate weight-specific license was found in the release asset. Reconfirm weight redistribution
conditions before public/commercial redistribution. Local development package only, not a legal certification.
COCO class names describe supported detections, not arbitrary plant species.
Reference source files are kept separately in licenses/yolox-reference and are NOT original business code.
Runtime does not download anything. SHA-256 is verified on every model load.
''',encoding='utf-8')
print(json.dumps({'id':manifest['id'],'sha256':manifest['sha256'],'classes':len(classes)}))
