from pathlib import Path
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from tushu.canvas.widget import Canvas
from tushu.domain.entities import Box
from tushu.ui.window import MainWindow
from tushu.ui.dialogs import ProcessDialog


def test_canvas_draw_move_resize(qtbot,imported):
    asset=imported.assets()[0]; category=imported.categories()[0]
    canvas=Canvas(); qtbot.addWidget(canvas); canvas.resize(800,600); canvas.show()
    canvas.load(imported.path(asset['path']),asset['width'],asset['height'],[],imported.categories())
    canvas.category=category['id']; canvas.mode='draw'
    commands=[]
    canvas.command.connect(lambda boxes,kind:commands.append((boxes,kind)))
    start=canvas.coords.screen(10,10).toPoint(); end=canvas.coords.screen(40,40).toPoint()
    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(canvas,end)
    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=end)
    assert len(commands)==1 and commands[0][1]=='create'
    box=commands[0][0][0]
    assert abs(box.x1-10)<.3 and abs(box.y2-40)<.3
    canvas.boxes=[box]; canvas.mode='select'; canvas.active=box.id
    center=canvas.coords.screen(25,25).toPoint()
    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=center)
    QTest.mouseMove(canvas,center+QPoint(15,15))
    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=center+QPoint(15,15))
    assert len(commands)==2 and commands[-1][1]=='move'
    assert commands[-1][0][0].edited
    for point in canvas.handles(canvas.boxes[0]): assert point is not None
    handle=canvas.handles(canvas.boxes[0])[4].toPoint()
    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle)
    QTest.mouseMove(canvas,handle+QPoint(25,25))
    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=handle+QPoint(25,25))
    assert commands[-1][1]=='resize:4'
    canvas.boxes[0].validate(asset['width'],asset['height'])


def test_mainwindow_edit_filter_and_safe_keys(qtbot,imported):
    window=MainWindow(); qtbot.addWidget(window); window.show(); window.attach(imported)
    asset=imported.assets()[0]; window.load_asset(asset['id'])
    category=imported.categories()[0]['id']
    window.commit([Box(category,1,1,10,10)],'create')
    assert '已保存' in window.save_label.text()
    assert window.box_table.rowCount()==1
    window.search.setText('missing'); assert window.asset_model.rowCount()==0
    window.search.clear(); assert window.asset_model.rowCount()==4
    window.load_asset(asset['id'])
    window.search.setFocus(); window.canvas.active=window.canvas.boxes[0].id
    QTest.keyClick(window.search,Qt.Key.Key_Delete)
    assert len(window.canvas.boxes)==1
    window.canvas.setFocus(); window.delete_box(); assert window.box_table.rowCount()==0
    window.undo(); assert window.box_table.rowCount()==1
    # Don't close fixture-owned connection twice; Project.close is idempotent.
    window.close()


def test_process_dialog_real_preview(qtbot,imported):
    dialog=ProcessDialog(imported,[imported.assets()[0]['id']]); qtbot.addWidget(dialog)
    dialog.kind.setCurrentIndex(dialog.kind.findData('flip_h')); dialog.add(); dialog.preview()
    assert dialog.preview_valid
    assert dialog.image.pixmap() is not None
    dialog.format.setCurrentText('PNG')
    dialog.kind.setCurrentIndex(dialog.kind.findData('encode'))
    assert dialog.quality.isHidden() and not dialog.compression.isHidden()


def test_filter_clears_invisible_current_and_syncs_selection(qtbot,imported):
    window=MainWindow(); qtbot.addWidget(window); window.show(); window.attach(imported)
    asset=imported.assets()[-1]
    window.load_asset(asset['id'])
    assert window.selected_ids()==[asset['id']]
    current=window.list.currentIndex()
    assert window.asset_model.assets[current.row()]['id']==asset['id']
    window.search.setText('does-not-exist')
    assert window.current is None and window.canvas.image.isNull()
    import pytest
    with pytest.raises(ValueError,match='选择图片'): window.chosen()
    window.reveal_asset(asset['id'])
    assert window.current==asset['id'] and window.selected_ids()==[asset['id']]
    window.close()
