from __future__ import annotations

import json
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox,QColorDialog,QComboBox,QDialog,QDialogButtonBox,QDoubleSpinBox,
    QFormLayout,QHBoxLayout,QLabel,QLineEdit,QListWidget,QMessageBox,QPushButton,
    QSpinBox,QTableWidget,QTableWidgetItem,QTextEdit,QVBoxLayout,QAbstractItemView,QHeaderView)


def buttons(dialog,layout):
    box=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    return box


def message(parent,title,text):
    dialog=QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(760,520)
    layout=QVBoxLayout(dialog)
    editor=QTextEdit()
    editor.setReadOnly(True)
    editor.setPlainText(text if isinstance(text,str) else json.dumps(text,ensure_ascii=False,indent=2))
    layout.addWidget(editor)
    close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.rejected.connect(dialog.reject)
    layout.addWidget(close)
    dialog.exec()


class ScanDialog(QDialog):
    def __init__(self,rows,project,parent=None):
        super().__init__(parent)
        self.setWindowTitle('扫描结果 · 确认后导入')
        self.resize(980,600)
        layout=QVBoxLayout(self)
        hashes={a['file_hash'] for a in project.assets()}
        seen=set(hashes)
        duplicates=0
        for row in rows:
            if row.get('hash') in seen:
                row['reason']='文件摘要重复，将跳过'
                duplicates+=1
            if row.get('hash'):
                seen.add(row['hash'])
        valid=[r for r in rows if r.get('accepted')]
        size=sum(r['size']+r['width']*r['height']*4 for r in valid)
        layout.addWidget(QLabel(f'发现 {len(rows)} 张 · 可解码 {len(valid)} 张 · 摘要重复 {duplicates} 张\n'
                               f'预计源副本与工作图空间约 {size/1024**2:.1f} MiB；单次最多 2000 张。'))
        table=QTableWidget(len(rows),6)
        table.setHorizontalHeaderLabels(['文件','格式','尺寸','模式','大小','检查结果'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for index,row in enumerate(rows):
            values=[row['name'],row.get('format','—'),f"{row.get('width','—')}×{row.get('height','—')}",
                    row.get('mode','—'),f"{row.get('size',0)/1024:.1f} KiB",row.get('reason') or '可导入']
            for column,value in enumerate(values):
                table.setItem(index,column,QTableWidgetItem(str(value)))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        box=buttons(self,layout)
        box.button(QDialogButtonBox.StandardButton.Ok).setText('确认导入')
        box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(valid) and len(valid)<=2000)


class CategoriesDialog(QDialog):
    def __init__(self,project,parent=None):
        super().__init__(parent)
        self.project=project
        self.setWindowTitle('类别管理 · 稳定类别 ID')
        self.resize(820,550)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('中文显示名用于界面；导出名写入训练数据。自定义类别不代表模型能识别。'))
        self.table=QTableWidget(0,5)
        self.table.setHorizontalHeaderLabels(['显示名称','导出名称','颜色 #RRGGBB','启用','稳定 ID'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        row=QHBoxLayout()
        for label,handler in [('添加类别',self.add),('添加动物／植物／物品模板',self.template),('保存所选行',self.save),('删除／合并所选类别',self.merge)]:
            button=QPushButton(label)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.reload()

    def reload(self):
        self.categories=self.project.categories()
        self.table.setRowCount(len(self.categories))
        for index,category in enumerate(self.categories):
            for column,key in enumerate(('display_name','export_name','color','enabled','id')):
                item=QTableWidgetItem(str(category[key]))
                if key=='id': item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(index,column,item)

    def add(self):
        from PySide6.QtWidgets import QInputDialog
        from tushu.services.editing import add_category
        name,ok=QInputDialog.getText(self,'添加类别','中文显示名（例如：银杏）')
        if not ok: return
        export,ok=QInputDialog.getText(self,'添加类别','导出名（例如：ginkgo）',text=name)
        if not ok: return
        color=QColorDialog.getColor(parent=self)
        if not color.isValid(): return
        try:
            add_category(self.project,name,export,color.name())
            self.reload()
        except Exception as error:
            QMessageBox.warning(self,'未添加',str(error))

    def template(self):
        from tushu.services.editing import add_category
        existing={c['export_name'].casefold() for c in self.project.categories()}
        for display,export,color in [('动物','animal','#276749'),('植物','plant','#65782b'),('物品','object','#385a97')]:
            if export not in existing: add_category(self.project,display,export,color)
        self.reload()

    def save(self):
        from tushu.services.editing import update_category
        row=self.table.currentRow()
        if row<0: return
        try:
            values=[self.table.item(row,c).text() for c in range(4)]
            update_category(self.project,self.categories[row]['id'],*values[:3],values[3]!='0')
            self.reload()
        except Exception as error:
            QMessageBox.warning(self,'未保存',str(error))

    def merge(self):
        from PySide6.QtWidgets import QInputDialog
        from tushu.services.editing import merge_category
        row=self.table.currentRow()
        if row<0: return
        source=self.categories[row]
        targets=[c for c in self.categories if c['id']!=source['id'] and c['enabled']]
        choices=['直接删除（有引用时会阻止）']+[c['display_name'] for c in targets]
        choice,ok=QInputDialog.getItem(self,'删除／合并',f"处理类别：{source['display_name']}",choices,0,False)
        if not ok: return
        target=None if choice==choices[0] else targets[choices.index(choice)-1]['id']
        try:
            merge_category(self.project,source['id'],target)
            self.reload()
        except Exception as error:
            QMessageBox.warning(self,'操作未完成',str(error))


class ModelDialog(QDialog):
    def __init__(self,project,model,parent=None):
        super().__init__(parent)
        self.setWindowTitle('模型类别映射 · 未映射类别将忽略')
        self.resize(800,680)
        self.model=model
        layout=QVBoxLayout(self)
        label=QLabel(f"{model.id}\n本地 CPU · 640×640 · SHA-256 {model.manifest['sha256'][:20]}…\n"
                     '盆栽不等于植物物种识别。自定义植物类别通常需要人工标注。')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table=QTableWidget(len(model.classes),2)
        self.table.setHorizontalHeaderLabels(['模型原始类别','项目类别（可多对一）'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        categories=[c for c in project.categories() if c['enabled']]
        previous={r['model_class_id']:r['category_id'] for r in project.rows(
            'SELECT * FROM class_mappings WHERE model_package_id=?',(model.id,))}
        self.combos=[]
        for index,name in enumerate(model.classes):
            item=QTableWidgetItem(f'{index} · {name}')
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(index,0,item)
            combo=QComboBox()
            combo.addItem('忽略',None)
            for category in categories:
                combo.addItem(category['display_name'],category['id'])
            suggested=previous.get(index)
            if index not in previous:
                suggested=next((c['id'] for c in categories if c['export_name'].casefold()==name.casefold()),None)
                if suggested is None:
                    animal={'bird','cat','dog','horse','sheep','cow','elephant','bear','zebra','giraffe'}
                    broad='animal' if name in animal else 'plant' if name=='potted plant' else 'object' if name!='person' else None
                    suggested=next((c['id'] for c in categories if broad and c['export_name'].casefold()==broad),None)
            combo.setCurrentIndex(max(0,combo.findData(suggested)))
            self.table.setCellWidget(index,1,combo)
            self.combos.append(combo)
        layout.addWidget(self.table)
        self.threshold=QDoubleSpinBox()
        self.threshold.setRange(.01,.99)
        self.threshold.setSingleStep(.05)
        self.threshold.setValue(.30)
        self.nms=QDoubleSpinBox()
        self.nms.setRange(.01,.99)
        self.nms.setValue(.45)
        form=QFormLayout()
        form.addRow('置信度阈值',self.threshold)
        form.addRow('NMS IoU 阈值',self.nms)
        layout.addLayout(form)
        buttons(self,layout)

    def mapping(self):
        return {index:combo.currentData() for index,combo in enumerate(self.combos)}


class ProcessDialog(QDialog):
    def __init__(self,project,asset_ids,parent=None,augment=False):
        super().__init__(parent)
        self.project=project
        self.asset_ids=asset_ids
        self.augment=augment
        self.operations=[]
        self.setWindowTitle('训练组增强方案' if augment else '批量处理 · 按列表顺序执行')
        self.resize(950,720)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel(f'选择 {len(asset_ids)} 张。新版本全部需要复核；原图保留。'
                               '裁剪保留面积低于 20% 的框会移除，请检查预览统计。'))
        content=QHBoxLayout()
        left=QVBoxLayout()
        self.list=QListWidget()
        self.list.setMaximumHeight(150)
        left.addWidget(self.list)
        tools=QHBoxLayout()
        for label,handler in [('上移',self.up),('移除操作',self.remove)]:
            button=QPushButton(label)
            button.clicked.connect(handler)
            tools.addWidget(button)
        left.addLayout(tools)
        self.kind=QComboBox()
        entries=[('水平翻转','flip_h'),('垂直翻转','flip_v'),('顺时针旋转','rotate'),
                 ('亮度','brightness'),('对比度','contrast')]
        if not augment:
            entries=[('最长边等比缩放','resize_longest'),('固定尺寸拉伸','resize'),('固定像素裁剪','crop')]+entries+[('编码／格式转换','encode')]
        for text,value in entries: self.kind.addItem(text,value)
        self.width=QSpinBox(); self.width.setRange(1,10000); self.width.setValue(1024)
        self.height=QSpinBox(); self.height.setRange(1,10000); self.height.setValue(768)
        self.x=QSpinBox(); self.x.setRange(0,9999)
        self.y=QSpinBox(); self.y.setRange(0,9999)
        self.angle=QComboBox(); self.angle.addItems(['90','180','270'])
        self.factor=QDoubleSpinBox(); self.factor.setRange(.8,1.2); self.factor.setSingleStep(.05); self.factor.setValue(1.1)
        self.format=QComboBox(); self.format.addItems(['PNG','JPEG','WEBP'])
        self.quality=QSpinBox(); self.quality.setRange(1,95); self.quality.setValue(90)
        self.compression=QSpinBox(); self.compression.setRange(0,9); self.compression.setValue(6)
        self.background=QLineEdit(parent.settings.value('background','#ffffff') if parent and hasattr(parent,'settings') else '#ffffff')
        self.lossless=QCheckBox('WebP 无损')
        self.form=QFormLayout()
        for label,widget in [('添加操作',self.kind),('宽／最长边',self.width),('高',self.height),('裁剪 x',self.x),
            ('裁剪 y',self.y),('顺时针角度',self.angle),('系数',self.factor),('输出格式',self.format),
            ('JPEG/WebP 质量',self.quality),('PNG 压缩等级',self.compression),('JPEG 背景色',self.background),('',self.lossless)]:
            self.form.addRow(label,widget)
        left.addLayout(self.form)
        self.kind.currentIndexChanged.connect(self.visibility)
        self.format.currentIndexChanged.connect(self.visibility)
        self.visibility()
        add=QPushButton('添加到操作序列'); add.clicked.connect(self.add)
        left.addWidget(add)
        preview=QPushButton('计算样本预览'); preview.clicked.connect(self.preview)
        left.addWidget(preview)
        content.addLayout(left,1)
        right=QVBoxLayout()
        self.image=QLabel('添加操作后点击“计算样本预览”')
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(420,340)
        self.info=QLabel('预览使用所选第一张；批量失败会逐图报告。')
        self.info.setWordWrap(True)
        right.addWidget(self.image,1); right.addWidget(self.info)
        content.addLayout(right,2)
        layout.addLayout(content,1)
        self.confirm=QCheckBox('我已检查样本预览、框移除统计和编码背景，确认应用所列操作')
        layout.addWidget(self.confirm)
        box=buttons(self,layout)
        box.button(QDialogButtonBox.StandardButton.Ok).setText('生成增强副本' if augment else '应用新版本')

    def visibility(self):
        kind=self.kind.currentData()
        visible={self.width:kind in ('resize_longest','resize','crop'),self.height:kind in ('resize','crop'),
                 self.x:kind=='crop',self.y:kind=='crop',self.angle:kind=='rotate',
                 self.factor:kind in ('brightness','contrast'),self.format:kind=='encode',
                 self.quality:kind=='encode' and self.format.currentText()!='PNG',
                 self.compression:kind=='encode' and self.format.currentText()=='PNG',
                 self.background:kind=='encode' and self.format.currentText()=='JPEG',
                 self.lossless:kind=='encode' and self.format.currentText()=='WEBP'}
        for widget,show in visible.items():
            widget.setVisible(show)
            label=self.form.labelForField(widget)
            if label: label.setVisible(show)

    def add(self):
        kind=self.kind.currentData()
        operation={'op':kind}
        if kind=='resize_longest': operation={'op':'resize','longest':self.width.value()}
        elif kind=='resize': operation.update(width=self.width.value(),height=self.height.value())
        elif kind=='crop': operation.update(x=self.x.value(),y=self.y.value(),width=self.width.value(),height=self.height.value())
        elif kind=='rotate': operation['angle']=int(self.angle.currentText())
        elif kind in ('brightness','contrast'): operation['factor']=self.factor.value()
        elif kind=='encode': operation.update(format=self.format.currentText(),quality=self.quality.value(),
            compress_level=self.compression.value(),background=self.background.text(),lossless=self.lossless.isChecked())
        self.operations.append(operation)
        self.refresh()

    def refresh(self):
        self.list.clear()
        labels={'resize':'缩放','crop':'裁剪','flip_h':'水平翻转','flip_v':'垂直翻转','rotate':'旋转',
                'brightness':'亮度','contrast':'对比度','encode':'格式编码'}
        for op in self.operations:
            self.list.addItem(labels[op['op']]+' · '+', '.join(f'{k}={v}' for k,v in op.items() if k!='op'))
        self.confirm.setChecked(False)
        self.preview_valid=False

    def up(self):
        index=self.list.currentRow()
        if index>0:
            self.operations[index-1],self.operations[index]=self.operations[index],self.operations[index-1]
            self.refresh(); self.list.setCurrentRow(index-1)

    def remove(self):
        index=self.list.currentRow()
        if index>=0:
            self.operations.pop(index); self.refresh()

    def preview(self):
        import io
        from tushu.services.processing import preview
        from tushu.imaging.normalize import encode
        if not self.operations: return
        try:
            image,boxes,info=preview(self.project,self.asset_ids[0],self.operations)
            codec=next((op for op in reversed(self.operations) if op['op']=='encode'),{})
            stream=io.BytesIO()
            encode(image,stream,codec.get('format','PNG'),codec.get('quality',90),codec.get('background','#ffffff'),
                   codec.get('lossless',False),codec.get('compress_level',6))
            data=stream.getvalue()
            qimage=QImage.fromData(data)
            pixmap=QPixmap.fromImage(qimage)
            self.image.setPixmap(pixmap.scaled(440,380,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            self.info.setText(f"输出 {image.width}×{image.height} · {len(data)/1024:.1f} KiB\n"
                              f"保留 {len(boxes)} 框 · 移除 {len(info['removed'])} 框（低保留面积 {len(info['low_area'])}）\n"
                              '仅预览第一张；实际处理逐图记录成功与失败。')
            self.preview_valid=True
        except Exception as error:
            self.preview_valid=False
            QMessageBox.warning(self,'无法预览',str(error))

    def accept(self):
        if not self.operations or not getattr(self,'preview_valid',False) or not self.confirm.isChecked():
            QMessageBox.warning(self,'请先预览','添加操作、计算样本预览并确认后才能执行。')
            return
        super().accept()
