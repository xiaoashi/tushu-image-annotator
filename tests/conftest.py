import pytest
from tushu.repositories.project import Project
from tushu.services.editing import add_category


@pytest.fixture
def project(tmp_path):
    project=Project.create(tmp_path,'中文项目')
    add_category(project,'动物','animal')
    yield project
    project.close()


def make_images(folder,count=4):
    from PIL import Image
    folder.mkdir(parents=True,exist_ok=True)
    for index in range(count):
        Image.new('RGB',(120+index,80),(index%256,(index//256)%256,100)).save(folder/f'动物_{index}.png')
    return folder


@pytest.fixture
def imported(project,tmp_path):
    from tushu.services.importing import scan,import_files
    import_files(project,scan(make_images(tmp_path/'输入')))
    return project
