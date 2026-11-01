"""Exercise the bundled runtime without relying on a system Python or the development venv."""
from __future__ import annotations

from pathlib import Path
import socket
import sys
import tempfile
from PIL import Image,ImageDraw

from tushu.app.check import environment
from tushu.domain.entities import Box
from tushu.repositories.project import Project
from tushu.services import importing,editing,inferencing,splitting,quality
from tushu.datasets.exporter import export
from tushu.inference.yolox import YoloX
from tushu.infrastructure.backup import backup,restore
from tushu.infrastructure.files import write_json


def smoke(report_path):
    def no_network(*args,**kwargs):
        raise RuntimeError('Self-test forbids network access')
    original_connect=socket.socket.connect
    original_create=socket.create_connection
    socket.socket.connect=no_network
    socket.create_connection=no_network
    report={'environment':environment(),'network':'socket connections denied during test',
            'frozen':bool(getattr(sys,'frozen',False)),'checks':{},'passed':False}
    try:
        with tempfile.TemporaryDirectory(prefix='tushu-bundled-smoke-') as temp:
            folder=Path(temp); inputs=folder/'中文输入'; inputs.mkdir()
            for index in range(8):
                image=Image.new('RGB',(160+index,120),(index*30,60,140))
                ImageDraw.Draw(image).rectangle((10,20,70,90),fill='white')
                image.save(inputs/f'工程图_{index}.png')
            project=Project.create(folder,'打包离线自检')
            try:
                result=importing.import_files(project,importing.scan(inputs))
                assert len(result['added'])==8 and not result['failed']
                report['checks']['import']=True
                model_root=Path(sys._MEIPASS)/'models/yolox-s-coco' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[3]/'models/yolox-s-coco'
                model=YoloX(model_root)
                category=editing.add_category(project,'工程目标','fixture')
                mapping={index:category for index in range(len(model.classes))}
                inferencing.register(project,model,mapping)
                result=inferencing.run(project,[a['id'] for a in project.assets()],model,mapping)
                assert len(result['success'])==8 and not result['failed']
                report['checks']['real_model_inference']=True
                for index,asset in enumerate(project.assets()):
                    project.save_boxes(asset['id'],[Box(category,10,20,70,90)] if index%2 else [],asset['revision'])
                    editing.review(project,asset['id'])
                assert not quality.check(project)['errors']
                splitting.create(project)
                for fmt in ('yolo','coco'):
                    result=export(project,folder/'export',fmt,acknowledge_warnings=True)
                    assert result['validation']['passed'] and result['validation']['negative_images']==4
                    report['checks'][fmt]=result['validation']
                saved=backup(project,folder/'backup')
                restored=Project(restore(saved,folder/'restored'))
                try:
                    assert len(restored.assets())==8 and not quality.check(restored)['errors']
                    report['checks']['backup_restore']=True
                finally: restored.close()
                report['passed']=True
            finally: project.close()
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        socket.socket.connect=original_connect
        socket.create_connection=original_create
        write_json(Path(report_path),report)
    return report
