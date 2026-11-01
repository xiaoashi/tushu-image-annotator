from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
from PySide6.QtCore import QSize, Qt, QSettings, QTimer
from PySide6.QtGui import QAction,QColor,QKeySequence,QShortcut
from PySide6.QtWidgets import (QAbstractItemView,QApplication,QCheckBox,QComboBox,QDialog,
    QDialogButtonBox,QDoubleSpinBox,QFileDialog,QFormLayout,QHBoxLayout,QHeaderView,QInputDialog,
    QLabel,QLineEdit,QListView,QMainWindow,QMenu,QMessageBox,QProgressBar,QPushButton,QSpinBox,
    QSplitter,QTableWidget,QTableWidgetItem,QToolBar,QVBoxLayout,QWidget,QTextEdit)

from tushu.canvas.widget import Canvas
from tushu.domain.entities import REVIEWED,STATES
from tushu.repositories.project import Project
from tushu.services.editing import History
from tushu.ui.dialogs import CategoriesDialog,ModelDialog,ProcessDialog,ScanDialog,buttons,message
from tushu.ui.models import AssetModel
from tushu.ui.workers import Worker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project=None
        self.current=None
        self.history=None
        self.worker=None
        self.model=None
        self.mapping=None
        self.threshold=.3
        self.nms=.45
        self.settings=QSettings('Tushu','Tushu-1.0')
        self.setWindowTitle('图枢 · 图像批量处理与智能辅助标注 V1.1')
        self.resize(1440,900)
        self.setMinimumSize(1080,680)
        self.build()
        self.refresh()

    def action(self,menu,text,handler,shortcut=None):
        action=QAction(text,self)
        action.triggered.connect(lambda checked=False:self.guard(handler))
        if shortcut: action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    def guard(self,handler):
        try:
            return handler()
        except Exception as error:
            QMessageBox.warning(self,'操作未完成',str(error))
            if self.project and self.current:
                try: self.load_asset(self.current)
                except Exception: pass

    def require_project(self):
        if not self.project:
            raise ValueError('请先新建或打开项目')
        if self.worker and self.worker.isRunning():
            raise ValueError('后台任务仍在运行，请等待完成或取消')

    def build(self):
        project_menu=self.menuBar().addMenu('项目')
        self.action(project_menu,'新建项目…',self.new_project,'Ctrl+N')
        self.action(project_menu,'打开项目…',self.open_project,'Ctrl+O')
        self.recent_menu=project_menu.addMenu('最近项目')
        self.update_recents()
        self.action(project_menu,'重命名项目…',self.rename_project)
        self.action(project_menu,'归档／取消归档项目',self.archive)
        self.action(project_menu,'备份项目…',self.backup)
        self.action(project_menu,'从备份恢复…',self.restore)
        self.action(project_menu,'关闭项目',self.close_project)
        image_menu=self.menuBar().addMenu('图片')
        self.action(image_menu,'导入文件夹…',self.import_folder)
        self.action(image_menu,'全选可见图片',lambda:self.list.selectAll())
        self.action(image_menu,'清空选择',lambda:self.list.clearSelection())
        self.action(image_menu,'反选可见图片',self.invert)
        self.action(image_menu,'逻辑重命名…',self.rename_images)
        self.action(image_menu,'批量处理…',self.process)
        self.action(image_menu,'排除所选图片…',self.exclude)
        self.action(image_menu,'重新纳入所选图片',lambda:self.exclude(True))
        self.action(image_menu,'移入项目回收区…',self.trash)
        self.action(image_menu,'恢复回收区全部图片',self.restore_trash)
        self.action(image_menu,'历史工作版本…',self.versions)
        data_menu=self.menuBar().addMenu('数据集')
        self.action(data_menu,'类别管理…',self.categories)
        self.action(data_menu,'加载本地模型包…',self.load_model)
        self.action(data_menu,'模型映射与阈值…',self.configure_model)
        self.action(data_menu,'预标注所选图片…',self.infer)
        self.action(data_menu,'质量检查…',self.quality)
        self.action(data_menu,'合并所选图片的同源组…',self.merge_groups)
        self.action(data_menu,'创建训练／验证划分…',self.split)
        self.action(data_menu,'训练组增强…',lambda:self.process(True))
        self.action(data_menu,'导出 YOLO／COCO…',self.export)
        tools=self.menuBar().addMenu('工具')
        self.action(tools,'任务中心／失败重试…',self.tasks)
        self.action(tools,'清理缩略图与预览缓存',self.clear_cache)
        self.action(tools,'设置…',self.preferences)
        self.action(tools,'环境自检',self.environment)
        self.action(tools,'快捷键与使用说明',self.help)
        toolbar=QToolBar('工作流程',self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)
        self.project_label=QLabel('图枢  ')
        self.project_label.setObjectName('projectTitle')
        toolbar.addWidget(self.project_label)
        self.action(toolbar,'新建项目',self.new_project)
        self.action(toolbar,'打开项目',self.open_project)
        toolbar.addSeparator()
        self.action(toolbar,'导入图片',self.import_folder)
        self.action(toolbar,'批量处理',self.process)
        self.action(toolbar,'预标注',self.infer)
        self.action(toolbar,'完成复核',self.complete_review)
        toolbar.addSeparator()
        self.action(toolbar,'质量检查',self.quality)
        self.action(toolbar,'导出数据集',self.export)
        self.toolbar=toolbar
        splitter=QSplitter()
        left=QWidget(); layout=QVBoxLayout(left); layout.setContentsMargins(14,14,14,10)
        self.count=QLabel('图片'); self.count.setObjectName('panelTitle'); layout.addWidget(self.count)
        self.search=QLineEdit(); self.search.setPlaceholderText('搜索文件名'); self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.state=QComboBox(); self.state.addItem('全部状态',None)
        for key,value in STATES.items(): self.state.addItem(value,key)
        self.state.currentIndexChanged.connect(self.refresh); layout.addWidget(self.state)
        filters=QHBoxLayout()
        self.source_filter=QComboBox(); self.source_filter.addItems(['全部来源','原始图片','增强副本'])
        self.source_filter.currentIndexChanged.connect(self.refresh); filters.addWidget(self.source_filter)
        self.sort=QComboBox(); self.sort.addItems(['文件名升序','文件名降序','尺寸从小到大','尺寸从大到小'])
        self.sort.currentIndexChanged.connect(self.refresh); filters.addWidget(self.sort)
        layout.addLayout(filters)
        self.class_filter=QComboBox(); self.class_filter.addItem('全部类别',None)
        self.class_filter.currentIndexChanged.connect(self.refresh); layout.addWidget(self.class_filter)
        self.list=QListView()
        self.asset_model=AssetModel(self)
        self.list.setModel(self.asset_model)
        self.list.setIconSize(QSize(66,66))
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(3)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.selectionModel().currentChanged.connect(self.current_changed)
        layout.addWidget(self.list,1)
        self.progress_label=QLabel('尚未打开项目'); self.progress_label.setWordWrap(True); layout.addWidget(self.progress_label)
        self.review_progress=QProgressBar(); self.review_progress.setMaximum(1); self.review_progress.setValue(0)
        layout.addWidget(self.review_progress)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        middle=QWidget(); center=QVBoxLayout(middle); center.setContentsMargins(0,0,0,0); center.setSpacing(0)
        strip=QHBoxLayout(); strip.setContentsMargins(14,10,14,10)
        self.identity=QLabel('等待选择图片'); self.identity.setMinimumWidth(80); self.identity.setMaximumWidth(400); strip.addWidget(self.identity,1)
        self.draw_button=QPushButton('画框 W'); self.draw_button.setCheckable(True)
        self.draw_button.toggled.connect(self.drawing); strip.addWidget(self.draw_button)
        fit=QPushButton('适应 F'); fit.clicked.connect(self.fit); strip.addWidget(fit)
        zoom=QPushButton('100%'); zoom.clicked.connect(lambda:self.canvas.zoom(1)); strip.addWidget(zoom)
        center.addLayout(strip)
        self.canvas=Canvas()
        self.canvas.command.connect(self.canvas_command)
        self.canvas.selected.connect(self.select_box)
        self.canvas.zoom_changed.connect(lambda value:self.zoom_label.setText(f'{value*100:.0f}%') if hasattr(self,'zoom_label') else None)
        center.addWidget(self.canvas,1)
        bottom=QHBoxLayout(); bottom.setContentsMargins(14,8,14,8)
        self.details=QLabel('全分辨率坐标 · 原图保留'); bottom.addWidget(self.details,1)
        self.zoom_label=QLabel('100%'); bottom.addWidget(self.zoom_label)
        center.addLayout(bottom)
        right=QWidget(); right_layout=QVBoxLayout(right); right_layout.setContentsMargins(14,14,14,10)
        title=QLabel('类别与检测框'); title.setObjectName('panelTitle'); right_layout.addWidget(title)
        self.category=QComboBox(); self.category.currentIndexChanged.connect(self.choose_category)
        right_layout.addWidget(self.category)
        category_buttons=QHBoxLayout()
        manage=QPushButton('管理类别'); manage.clicked.connect(lambda:self.guard(self.categories)); category_buttons.addWidget(manage)
        assign=QPushButton('所选框改类'); assign.clicked.connect(lambda:self.guard(self.reclassify)); category_buttons.addWidget(assign)
        right_layout.addLayout(category_buttons)
        self.show_category=QCheckBox('仅显示当前类别'); self.show_category.toggled.connect(self.visibility)
        right_layout.addWidget(self.show_category)
        self.score_filter=QDoubleSpinBox(); self.score_filter.setRange(0,1); self.score_filter.setSingleStep(.05)
        self.score_filter.setPrefix('显示分数 ≥ '); self.score_filter.valueChanged.connect(self.visibility)
        right_layout.addWidget(self.score_filter)
        self.box_table=QTableWidget(0,3)
        self.box_table.setHorizontalHeaderLabels(['类别','分数／来源','坐标'])
        self.box_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.box_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.box_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.box_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.box_table.horizontalHeader().setStretchLastSection(True)
        self.box_table.itemSelectionChanged.connect(self.table_selected)
        right_layout.addWidget(self.box_table,1)
        self.save_label=QLabel('尚无标注'); right_layout.addWidget(self.save_label)
        row=QHBoxLayout()
        for text,handler in [('撤销',lambda:self.undo()),('重做',lambda:self.undo(True)),('删除框',self.delete_box)]:
            button=QPushButton(text); button.clicked.connect(lambda checked=False,h=handler:self.guard(h)); row.addWidget(button)
        right_layout.addLayout(row)
        self.stale=QCheckBox('我已校正并确认过期的增强来源'); right_layout.addWidget(self.stale)
        review_button=QPushButton('完成复核   ⌘ / Ctrl + Enter'); review_button.setObjectName('primary')
        review_button.clicked.connect(lambda:self.guard(self.complete_review)); right_layout.addWidget(review_button)
        self.model_label=QLabel('未加载模型\n可直接人工标注'); self.model_label.setWordWrap(True); right_layout.addWidget(self.model_label)
        splitter.addWidget(left); splitter.addWidget(middle); splitter.addWidget(right)
        splitter.setSizes([270,850,320]); splitter.setChildrenCollapsible(False)
        left.setMinimumWidth(230); right.setMinimumWidth(280)
        self.setCentralWidget(splitter)
        self.status=QLabel('就绪 · 本地离线运行'); self.statusBar().addWidget(self.status,1)
        self.task_progress=QProgressBar(); self.task_progress.setFixedWidth(190); self.task_progress.hide()
        self.statusBar().addPermanentWidget(self.task_progress)
        self.cancel_button=QPushButton('取消任务'); self.cancel_button.clicked.connect(self.cancel_task); self.cancel_button.hide()
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.shortcuts=[]
        bindings=[('A',lambda:self.navigate(-1)),('D',lambda:self.navigate(1)),('W',lambda:self.draw_button.setChecked(True)),
            ('Escape',self.escape),('Delete',self.delete_box),('Backspace',self.delete_box),('F',self.fit),
            ('Ctrl+S',self.saved),('Ctrl+Z',self.undo),('Ctrl+Shift+Z',lambda:self.undo(True)),
            ('Ctrl+Return',self.complete_review),('Meta+Return',self.complete_review)]
        for key,handler in bindings:
            shortcut=QShortcut(QKeySequence(key),self)
            shortcut.activated.connect(lambda h=handler:self.shortcut(h))
            self.shortcuts.append(shortcut)
        for index in range(9):
            shortcut=QShortcut(str(index+1),self)
            shortcut.activated.connect(lambda i=index:self.shortcut(lambda:self.category.setCurrentIndex(i) if i<self.category.count() else None))
            self.shortcuts.append(shortcut)
        self.setStyleSheet('''
            QMainWindow,QWidget { background:#f4f5f1; color:#24332b; font-size:13px; }
            QToolBar { border:0; border-bottom:1px solid #d9dfd7; padding:9px; spacing:7px; }
            QToolButton { padding:7px 9px; border-radius:5px; }
            QToolButton:hover,QPushButton:hover { background:#e1e8de; }
            QPushButton { min-height:26px; padding:3px 8px; }
            QPushButton#primary { background:#276347; color:white; border:0; padding:9px; border-radius:5px; }
            QPushButton#primary:hover { background:#174f35; }
            QPushButton:focus,QComboBox:focus,QLineEdit:focus { border:2px solid #357e58; }
            QLabel#panelTitle { font-size:15px; font-weight:600; margin-bottom:6px; }
            QLabel#projectTitle { font-size:17px; font-weight:600; padding-right:8px; }
            QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox { min-height:26px; }
            QListView { background:#f9faf7; border:0; }
            QListView::item { min-height:76px; padding:5px; border-radius:4px; }
            QListView::item:selected { background:#d9e7d9; color:#163d26; }
            QTableWidget { background:#fafbf8; gridline-color:#dfe4db; border:0; }
            QHeaderView::section { background:#e9ede5; padding:5px; border:0; }
            QProgressBar { border:1px solid #ced8ca; border-radius:3px; text-align:center; max-height:17px; }
            QProgressBar::chunk { background:#85b18c; }
            QStatusBar { border-top:1px solid #d9dfd7; }
        ''')

    def shortcut(self,handler):
        focus=QApplication.focusWidget()
        if isinstance(focus,(QLineEdit,QTextEdit,QSpinBox,QDoubleSpinBox,QComboBox)):
            return
        if self.worker and self.worker.isRunning(): return
        self.guard(handler)

    def attach(self,project):
        self.project=project
        self.history=History(project)
        self.current=None
        self.model=None; self.mapping=None
        self.remember(project.root)
        self.project_label.setText(project.name+'  ')
        self.setWindowTitle(f'{project.name} — 图枢 V1.1')
        self.update_categories()
        self.refresh()
        if self.asset_model.assets:
            self.list.setCurrentIndex(self.asset_model.index(0))
        interrupted=project.rows("SELECT id,type FROM tasks WHERE status='interrupted'")
        if interrupted:
            QTimer.singleShot(0,lambda:message(self,'发现中断任务',{'说明':'已提交结果保留；任务中心可以查看失败详情并重试未完成图片。','tasks':interrupted}))

    def new_project(self):
        if self.worker and self.worker.isRunning(): return
        name,ok=QInputDialog.getText(self,'新建项目','项目名称',text='我的图像数据集')
        if not ok: return
        parent=QFileDialog.getExistingDirectory(self,'选择项目保存位置',self.settings.value('workspace',str(Path.home()/'Pictures')))
        if not parent: return
        project=Project.create(parent,name)
        self.close_project()
        self.attach(project)

    def open_project(self,path=None):
        if self.worker and self.worker.isRunning(): return
        path=path or QFileDialog.getExistingDirectory(self,'选择包含 project.json 的项目文件夹')
        if not path: return
        if self.project and Path(path).resolve()==self.project.root: return
        project=Project(path)
        self.close_project()
        self.attach(project)

    def close_project(self):
        if self.worker and self.worker.isRunning():
            raise ValueError('请先等待或取消后台任务')
        if self.project:
            self.project.close()
        self.project=None; self.current=None; self.history=None; self.model=None; self.mapping=None
        self.asset_model.icons.clear()
        self.canvas.load(None,1,1,[],[])
        self.box_table.setRowCount(0)
        self.project_label.setText('图枢  ')
        self.setWindowTitle('图枢 · 图像批量处理与智能辅助标注 V1.1')
        self.update_categories()
        self.refresh()

    def remember(self,path):
        recent=self.settings.value('recent',[]) or []
        if isinstance(recent,str): recent=[recent]
        recent=[str(path)]+[p for p in recent if p!=str(path)]
        self.settings.setValue('recent',recent[:12])
        self.update_recents()

    def update_recents(self):
        self.recent_menu.clear()
        recent=self.settings.value('recent',[]) or []
        if isinstance(recent,str): recent=[recent]
        for path in recent:
            label=path
            try: label=json.loads((Path(path)/'project.json').read_text('utf-8'))['name']
            except Exception: pass
            self.action(self.recent_menu,label,lambda p=path:self.open_project(p))

    def update_categories(self):
        categories=self.project.categories() if self.project else []
        previous=self.category.currentData()
        previous_filter=self.class_filter.currentData()
        self.category.blockSignals(True); self.class_filter.blockSignals(True)
        self.category.clear(); self.class_filter.clear(); self.class_filter.addItem('全部类别',None)
        for category in categories:
            if category['enabled']:
                self.category.addItem(category['display_name'],category['id'])
                self.class_filter.addItem(category['display_name'],category['id'])
        self.category.setCurrentIndex(max(0,self.category.findData(previous)))
        self.class_filter.setCurrentIndex(max(0,self.class_filter.findData(previous_filter)))
        self.category.blockSignals(False); self.class_filter.blockSignals(False)
        self.canvas.categories={c['id']:c for c in categories}
        self.choose_category()

    def refresh(self,*args):
        if not hasattr(self,'asset_model'): return
        assets=self.project.assets() if self.project else []
        selected=set(self.selected_ids()) if self.project else set()
        visible=[]
        for asset in assets:
            if self.search.text().casefold() not in asset['display_name'].casefold(): continue
            if self.state.currentData() and asset['state']!=self.state.currentData(): continue
            if self.source_filter.currentIndex()==1 and asset['parent_asset_id']: continue
            if self.source_filter.currentIndex()==2 and not asset['parent_asset_id']: continue
            if self.class_filter.currentData() and not any(b.category_id==self.class_filter.currentData() for b in self.project.boxes(asset['active_version_id'])): continue
            visible.append(asset)
        sort=self.sort.currentIndex()
        visible.sort(key=(lambda a:(a['width']*a['height'],a['id'])) if sort>=2 else
                     (lambda a:(a['display_name'].casefold(),a['id'])),reverse=sort in (1,3))
        self.list.selectionModel().blockSignals(True)
        self.asset_model.reset(self.project,visible)
        from PySide6.QtCore import QItemSelectionModel
        for index,asset in enumerate(visible):
            if asset['id'] in selected:
                self.list.selectionModel().select(self.asset_model.index(index),QItemSelectionModel.SelectionFlag.Select)
            if asset['id']==self.current:
                self.list.selectionModel().setCurrentIndex(self.asset_model.index(index),QItemSelectionModel.SelectionFlag.NoUpdate)
        self.list.selectionModel().blockSignals(False)
        if self.current and not any(a['id']==self.current for a in visible):
            self.clear_current()
        valid=[a for a in assets if a['state'] not in ('excluded','error')]
        reviewed=sum(a['state'] in REVIEWED for a in valid)
        errors=sum(a['state']=='error' for a in assets)
        excluded=sum(a['state']=='excluded' for a in assets)
        self.count.setText(f'图片  {len(visible)} / {len(assets)}')
        self.progress_label.setText(f'已复核 {reviewed} / {len(valid)}\n异常 {errors} · 排除 {excluded}')
        self.progress_label.setToolTip('\n'.join(f'{name}: {sum(a["state"]==key for a in assets)}' for key,name in STATES.items()))
        self.review_progress.setMaximum(max(1,len(valid))); self.review_progress.setValue(reviewed)
        self.model_label.setText(f'{self.model.id}\n本地 CPU · 映射已配置' if self.model and self.mapping else '未配置模型映射\n可直接人工标注')

    def selected_ids(self):
        return [self.asset_model.assets[i.row()]['id'] for i in self.list.selectionModel().selectedIndexes()]

    def chosen(self):
        self.require_project()
        result=self.selected_ids()
        if not result and self.current and any(a['id']==self.current for a in self.asset_model.assets): result=[self.current]
        if not result: raise ValueError('请先在左侧选择图片（支持多选）')
        return result

    def current_changed(self,index,previous):
        if index.isValid():
            identifier=self.asset_model.assets[index.row()]['id']
            self.guard(lambda:self.load_asset(identifier))

    def clear_current(self):
        self.current=None
        self.canvas.load(None,1,1,[],self.project.categories() if self.project else [])
        self.box_table.setRowCount(0)
        self.identity.setText('等待选择图片')
        self.details.setText('当前筛选中没有选定图片')
        self.save_label.setText('尚无选定标注')

    def reveal_asset(self,identifier):
        for widget in (self.search,self.state,self.source_filter,self.class_filter): widget.blockSignals(True)
        self.search.clear(); self.state.setCurrentIndex(0); self.source_filter.setCurrentIndex(0); self.class_filter.setCurrentIndex(0)
        for widget in (self.search,self.state,self.source_filter,self.class_filter): widget.blockSignals(False)
        self.refresh(); self.load_asset(identifier)

    def load_asset(self,identifier,preserve_view=False):
        if not self.project: return
        asset=self.project.asset(identifier)
        self.current=identifier
        from PySide6.QtCore import QItemSelectionModel
        for row,visible in enumerate(self.asset_model.assets):
            if visible['id']==identifier:
                index=self.asset_model.index(row)
                selection=self.list.selectionModel()
                selection.blockSignals(True)
                selection.setCurrentIndex(index,QItemSelectionModel.SelectionFlag.NoUpdate)
                if not selection.isSelected(index):
                    selection.select(index,QItemSelectionModel.SelectionFlag.ClearAndSelect)
                selection.blockSignals(False)
                self.list.scrollTo(index)
                break
        path=self.project.root/'previews'/f"{asset['sha256']}.png"
        if not path.exists(): path=self.project.path(asset['path'])
        scale,offset=self.canvas.coords.scale,self.canvas.coords.offset
        active=self.canvas.active
        self.canvas.load(path,asset['width'],asset['height'],self.project.boxes(asset['active_version_id']),self.project.categories())
        if preserve_view:
            self.canvas.coords.scale=scale; self.canvas.coords.offset=offset; self.canvas.active=active
        self.choose_category()
        self.visibility()
        self.identity.setText(asset['display_name'])
        self.identity.setToolTip(asset['display_name'])
        self.details.setText(f"{asset['width']} × {asset['height']} px  ·  {STATES[asset['state']]}  ·  版本 {asset['active_version_id'][:8]}")
        self.save_label.setText(f"已保存 · 修订 {asset['revision']}")
        self.canvas.locked=bool(self.worker and self.worker.isRunning()) or asset['state']=='excluded'
        self.stale.setChecked(False)
        self.fill_boxes()

    def fill_boxes(self):
        self.box_table.blockSignals(True)
        boxes=self.canvas.boxes
        self.box_table.setRowCount(len(boxes))
        for row,box in enumerate(boxes):
            category=self.canvas.categories.get(box.category_id,{})
            status='人工' if box.score is None else f'{box.score:.2f}'+(' · 已改' if box.edited else ' · 模型')
            coords=f'{box.x1:.1f}, {box.y1:.1f}\n{box.x2:.1f}, {box.y2:.1f}'
            for column,text in enumerate((category.get('display_name','未知'),status,coords)):
                item=QTableWidgetItem(text); item.setData(Qt.ItemDataRole.UserRole,box.id)
                item.setToolTip(json.dumps(box.to_dict(),ensure_ascii=False,indent=2))
                if not self.canvas.visible(box): item.setForeground(QColor('#7d817b'))
                self.box_table.setItem(row,column,item)
            self.box_table.setRowHeight(row,44)
        self.box_table.blockSignals(False)

    def select_box(self,identifier):
        self.box_table.blockSignals(True)
        self.box_table.clearSelection()
        for row,box in enumerate(self.canvas.boxes):
            if box.id==identifier:
                self.box_table.selectRow(row)
                self.box_table.scrollToItem(self.box_table.item(row,0))
                break
        self.box_table.blockSignals(False)

    def table_selected(self):
        row=self.box_table.currentRow()
        if 0<=row<len(self.canvas.boxes):
            self.canvas.active=self.canvas.boxes[row].id; self.canvas.update()

    def choose_category(self,*args):
        self.canvas.category=self.category.currentData()
        self.visibility()

    def visibility(self,*args):
        self.canvas.minimum_score=self.score_filter.value()
        self.canvas.hidden_classes=set(self.canvas.categories)-{self.category.currentData()} if self.show_category.isChecked() else set()
        self.canvas.update()
        self.fill_boxes()

    def drawing(self,enabled):
        self.canvas.mode='draw' if enabled else 'select'
        if enabled and not self.category.currentData():
            self.draw_button.setChecked(False)
            self.guard(lambda:(_ for _ in ()).throw(ValueError('请先通过“管理类别”添加类别')))

    def escape(self):
        self.draw_button.setChecked(False); self.canvas.cancel_gesture()

    def fit(self): self.canvas.fit()

    def canvas_command(self,boxes,command):
        self.guard(lambda:self.commit(boxes,command))

    def commit(self,boxes,command):
        self.require_project()
        if not self.current: return
        asset=self.project.asset(self.current)
        self.history.execute(asset,[replace(b) for b in boxes],command)
        self.load_asset(self.current,True)
        self.refresh()

    def reclassify(self):
        if not self.canvas.active or not self.category.currentData(): return
        boxes=[replace(b,category_id=self.category.currentData(),edited=True) if b.id==self.canvas.active else replace(b) for b in self.canvas.boxes]
        self.commit(boxes,'reclassify')

    def delete_box(self):
        if self.current and self.canvas.active:
            self.commit([replace(b) for b in self.canvas.boxes if b.id!=self.canvas.active],'delete')
            self.canvas.active=None

    def undo(self,redo=False):
        self.require_project()
        if self.current:
            self.history.undo(self.project.asset(self.current),redo)
            self.load_asset(self.current,True); self.refresh()

    def saved(self):
        if self.current:
            self.save_label.setText(f"已保存 · 修订 {self.project.asset(self.current)['revision']}")

    def complete_review(self):
        self.require_project()
        if not self.current: return
        if not self.canvas.boxes and QMessageBox.question(self,'确认负样本','已查看整张图片，确认没有需要标注的目标？')!=QMessageBox.StandardButton.Yes: return
        from tushu.services.editing import review
        original=[a['id'] for a in self.asset_model.assets]
        position=original.index(self.current) if self.current in original else -1
        review(self.project,self.current,self.canvas.has_hidden,self.stale.isChecked())
        self.load_asset(self.current,True); self.refresh()
        visible={a['id'] for a in self.asset_model.assets}
        if self.current not in visible:
            successor=next((key for key in original[position+1:]+original[:position] if key in visible),None)
            if successor: self.load_asset(successor)

    def navigate(self,delta):
        assets=self.asset_model.assets
        if not assets: return
        index=next((i for i,a in enumerate(assets) if a['id']==self.current),-1)
        index=max(0,min(len(assets)-1,index+delta))
        self.list.setCurrentIndex(self.asset_model.index(index))

    def start_task(self,kind,action,on_result=None):
        self.require_project()
        self.worker=Worker(self.project,kind,action,self)
        worker=self.worker
        self.canvas.cancel_gesture(); self.canvas.locked=True; self.canvas.update()
        self.task_progress.setRange(0,0); self.task_progress.show(); self.cancel_button.show()
        self.status.setText('正在执行：'+kind)
        worker.progress.connect(self.task_update)
        worker.error.connect(lambda text:QMessageBox.warning(self,'任务失败',text))
        worker.cancelled.connect(lambda text:message(self,'任务已取消',text))
        worker.result.connect(lambda value:QTimer.singleShot(0,lambda:self.task_result(on_result,value)))
        worker.finished.connect(self.task_finished)
        worker.start()

    def task_update(self,done,total,name):
        if total:
            self.task_progress.setRange(0,total); self.task_progress.setValue(done)
        self.status.setText(f'{done} / {total or "扫描中"} · {name}')

    def task_result(self,callback,value):
        if self.worker and self.worker.isRunning():
            QTimer.singleShot(30,lambda:self.task_result(callback,value)); return
        if callback: self.guard(lambda:callback(value))

    def task_finished(self):
        self.task_progress.hide(); self.cancel_button.hide()
        self.canvas.locked=False
        self.status.setText('任务结束 · 详见任务中心')
        self.refresh()
        if self.current: self.guard(lambda:self.load_asset(self.current,True))

    def cancel_task(self):
        if self.worker: self.worker.cancel_event.set(); self.status.setText('已请求取消，等待单图安全检查点…')

    def import_folder(self):
        self.require_project()
        folder=QFileDialog.getExistingDirectory(self,'选择图片文件夹')
        if not folder: return
        recursive=QMessageBox.question(self,'扫描范围','是否递归扫描子文件夹？（不跟随符号链接）')==QMessageBox.StandardButton.Yes
        from tushu.services.importing import scan,import_files
        def scanned(rows):
            if not rows: QMessageBox.information(self,'扫描结束','没有发现支持的图片。'); return
            dialog=ScanDialog(rows,self.project,self)
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.start_task('导入图片',lambda ctx:import_files(self.project,rows,ctx),
                                lambda report:message(self,'导入报告',report))
        self.start_task('扫描图片',lambda ctx:scan(folder,recursive,ctx),scanned)

    def categories(self):
        self.require_project()
        CategoriesDialog(self.project,self).exec()
        self.update_categories(); self.refresh()
        if self.current: self.load_asset(self.current,True)

    def model_folder(self):
        if getattr(sys,'frozen',False): return Path(sys._MEIPASS)/'models/yolox-s-coco'
        return Path(__file__).resolve().parents[3]/'models/yolox-s-coco'

    def load_model(self,builtin=False,after=None):
        self.require_project()
        folder=str(self.model_folder()) if builtin else QFileDialog.getExistingDirectory(self,'选择模型包（包含 model_manifest.json）',str(self.model_folder()))
        if not folder: return
        from tushu.inference.yolox import YoloX
        def ready(model):
            self.model=model
            if not self.project.categories():
                response=QMessageBox.question(self,'建立模型类别','当前没有类别。是否建立 COCO 模型支持的 80 类？\n可之后删除不用的类别、添加植物等人工类别。')
                if response==QMessageBox.StandardButton.Yes:
                    from tushu.services.editing import add_category
                    chinese={'bird':'鸟','cat':'猫','dog':'狗','horse':'马','sheep':'羊','cow':'牛','elephant':'大象',
                             'bear':'熊','zebra':'斑马','giraffe':'长颈鹿','potted plant':'盆栽','person':'人',
                             'bottle':'瓶子','cup':'杯子','chair':'椅子','book':'书','cell phone':'手机','car':'汽车'}
                    colors=['#276749','#85622c','#385a97','#8e4771','#486d7b','#7759a0']
                    for index,name in enumerate(model.classes):
                        add_category(self.project,chinese.get(name,name),name,colors[index%len(colors)])
            self.update_categories()
            self.configure_model()
            if after and self.mapping: after()
        self.start_task('验证模型包',lambda ctx:YoloX(folder),ready)

    def configure_model(self):
        self.require_project()
        if not self.model:
            self.load_model(True); return
        dialog=ModelDialog(self.project,self.model,self)
        dialog.threshold.setValue(self.threshold); dialog.nms.setValue(self.nms)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            from tushu.services.inferencing import register
            register(self.project,self.model,dialog.mapping())
            self.mapping=dialog.mapping(); self.threshold=dialog.threshold.value(); self.nms=dialog.nms.value()
            self.refresh()

    def infer(self):
        identifiers=self.chosen()
        if not self.model:
            self.load_model(True,self.infer); return
        if not self.mapping:
            self.configure_model()
            if not self.mapping: return
        from tushu.services.inferencing import replacement_counts,run
        replaced,protected=replacement_counts(self.project,identifiers)
        if QMessageBox.question(self,'确认预标注策略',f'处理 {len(identifiers)} 张图片。\n替换 {replaced} 个未修改且未复核的自动建议；保留 {protected} 个人工／已改／已复核框。\n新建议全部需要复核。是否开始？')!=QMessageBox.StandardButton.Yes: return
        self.start_task('本地模型预标注',lambda ctx:run(self.project,identifiers,self.model,self.mapping,self.threshold,self.nms,ctx),lambda report:message(self,'预标注报告',report))

    def process(self,augment=False):
        identifiers=self.chosen()
        if augment:
            from tushu.services.splitting import current_plan
            plan=current_plan(self.project)
            for key in identifiers:
                asset=self.project.asset(key)
                if plan['assignments'].get(asset['group_id'])!='train' or asset['state'] not in REVIEWED:
                    raise ValueError('选择中包含验证组或未复核图片，请只选择已复核的训练组图片')
        dialog=ProcessDialog(self.project,identifiers,self,augment)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            from tushu.services.processing import apply
            self.start_task('训练组增强' if augment else '图像批处理',lambda ctx:apply(self.project,identifiers,dialog.operations,ctx,augment),lambda report:message(self,'处理报告',report))

    def quality(self):
        self.require_project()
        from tushu.services.quality import check
        self.start_task('质量检查',lambda ctx:check(self.project,context=ctx),self.quality_result)

    def quality_result(self,report):
        dialog=QDialog(self); dialog.setWindowTitle('质量检查 · 双击问题定位图片'); dialog.resize(900,550)
        layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"检查 {report['assets']} 张 · 错误 {len(report['errors'])} · 警告 {len(report['warnings'])}"))
        table=QTableWidget(len(report['issues']),4); table.setHorizontalHeaderLabels(['级别','图片','编号','原因'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); table.horizontalHeader().setStretchLastSection(True)
        for row,issue in enumerate(report['issues']):
            for column,text in enumerate((issue['level'],issue['name'],issue['code'],issue['message'])):
                table.setItem(row,column,QTableWidgetItem(text))
        def locate(row,column):
            identifier=report['issues'][row]['asset_id']
            if identifier: self.reveal_asset(identifier); dialog.accept()
        table.cellDoubleClicked.connect(locate); layout.addWidget(table)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(dialog.reject); layout.addWidget(close)
        dialog.exec()

    def split(self):
        self.require_project()
        dialog=QDialog(self); dialog.setWindowTitle('锁定训练／验证划分'); layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel('按同源组划分，精确重复图和增强图不跨集合。改变导出范围后须重新划分。'))
        form=QFormLayout(); ratio=QDoubleSpinBox(); ratio.setRange(.5,.95); ratio.setValue(.8); ratio.setSingleStep(.05)
        seed=QSpinBox(); seed.setRange(0,2147483647); seed.setValue(42)
        form.addRow('训练比例',ratio); form.addRow('随机种子',seed); layout.addLayout(form); buttons(dialog,layout)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            from tushu.services.splitting import create
            plan=create(self.project,ratio.value(),seed.value())
            message(self,'划分计划已保存 · 请核对实际比例与类别覆盖',plan)

    def merge_groups(self):
        identifiers=self.chosen()
        if QMessageBox.question(self,'合并同源组','将所选图片的整个同源组连接；已有划分计划将失效。确认这些图片来自同一来源？')!=QMessageBox.StandardButton.Yes: return
        from tushu.services.splitting import merge_groups
        merge_groups(self.project,identifiers); self.status.setText('同源组已合并，请重新划分')

    def export(self):
        self.require_project()
        dialog=QDialog(self); dialog.setWindowTitle('导出数据集 · 冻结后独立回读验证'); dialog.resize(700,520)
        layout=QVBoxLayout(dialog)
        format_box=QComboBox(); format_box.addItems(['YOLO 检测','COCO 检测']); layout.addWidget(format_box)
        scope=QComboBox(); scope.addItems(['所有已复核图片（默认）','仅左侧所选图片']); layout.addWidget(scope)
        report_box=QTextEdit(); report_box.setReadOnly(True); layout.addWidget(report_box)
        acknowledge=QCheckBox('我已核对质量警告、未纳入图片和划分比例，接受当前类别覆盖情况')
        layout.addWidget(acknowledge)
        def preflight():
            assets=self.project.assets()
            selected=self.selected_ids() if scope.currentIndex()==1 else [a['id'] for a in assets if a['state'] in REVIEWED]
            from tushu.services.splitting import current_plan
            plan=current_plan(self.project)
            summary={'纳入数量':len(selected),'未纳入':[{'name':a['display_name'],'reason':STATES[a['state']]} for a in assets if a['id'] not in selected],
                     '划分统计':plan['statistics'],'说明':'导出时将重新检查全部文件摘要、框和复核状态；有错误则不发布。'}
            report_box.setPlainText(json.dumps(summary,ensure_ascii=False,indent=2))
            acknowledge.setChecked(False)
        scope.currentIndexChanged.connect(lambda:self.guard(preflight)); preflight()
        buttons(dialog,layout)
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        if not acknowledge.isChecked(): raise ValueError('请先明确确认预检提示')
        destination=QFileDialog.getExistingDirectory(self,'选择导出父目录',str(self.project.root/'exports'))
        if not destination: return
        selected=self.selected_ids() if scope.currentIndex()==1 else None
        from tushu.datasets.exporter import export
        # Full warnings are computed in worker, then explicitly confirmed before a second export action.
        from tushu.services.quality import check
        ids=selected if selected is not None else [a['id'] for a in self.project.assets() if a['state'] in REVIEWED]
        def checked(report):
            if report['errors']:
                self.quality_result(report); return
            if report['warnings']:
                text='\n'.join(w['message'] for w in report['warnings'])
                if QMessageBox.question(self,'确认质量警告',text+'\n\n是否接受以上警告并继续？')!=QMessageBox.StandardButton.Yes: return
            self.start_task('导出与独立回读',lambda ctx:export(self.project,destination,'yolo' if format_box.currentIndex()==0 else 'coco',selected,True,ctx),
                            lambda result:message(self,'数据集已通过校验并发布',result))
        self.start_task('导出质量预检',lambda ctx:check(self.project,ids,context=ctx),checked)

    def exclude(self,include=False):
        identifiers=self.chosen()
        reason=None
        if not include:
            reason,ok=QInputDialog.getText(self,'排除图片','排除原因')
            if not ok: return
        from tushu.services.editing import set_excluded
        set_excluded(self.project,identifiers,reason); self.refresh()
        if self.current: self.load_asset(self.current,True)

    def invert(self):
        from PySide6.QtCore import QItemSelectionModel
        for index in range(self.asset_model.rowCount()):
            self.list.selectionModel().select(self.asset_model.index(index),QItemSelectionModel.SelectionFlag.Toggle)

    def rename_images(self):
        identifiers=self.chosen()
        dialog=QDialog(self); dialog.setWindowTitle('逻辑重命名 · 不改变原始文件'); layout=QVBoxLayout(dialog); form=QFormLayout()
        prefix=QLineEdit('image_'); start=QSpinBox(); start.setRange(0,99999999); start.setValue(1)
        step=QSpinBox(); step.setRange(1,999999); padding=QSpinBox(); padding.setRange(1,12); padding.setValue(6)
        for label,widget in [('前缀',prefix),('起始',start),('步长',step),('补零位数',padding)]: form.addRow(label,widget)
        layout.addLayout(form); buttons(dialog,layout)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            from tushu.services.editing import rename_assets
            mapping=rename_assets(self.project,identifiers,prefix.text(),start.value(),step.value(),padding.value())
            if QMessageBox.question(self,'确认名称映射','\n'.join(f"{m['old']} → {m['new']}" for m in mapping[:30])+f'\n共 {len(mapping)} 张，完整映射保存到项目审计记录。')!=QMessageBox.StandardButton.Yes: return
            rename_assets(self.project,identifiers,prefix.text(),start.value(),step.value(),padding.value(),True); self.refresh()

    def versions(self):
        self.require_project()
        if not self.current: return
        versions=self.project.rows('SELECT * FROM image_versions WHERE asset_id=? ORDER BY rowid DESC',(self.current,))
        labels=[f"{v['id'][:12]} · {v['width']}×{v['height']} · {STATES[v['state']]} · 修订 {v['revision']}" for v in versions]
        choice,ok=QInputDialog.getItem(self,'切换历史版本','历史版本保留独立标注；切换将使划分计划失效。',labels,0,False)
        if ok:
            from tushu.services.processing import activate_version
            activate_version(self.project,self.current,versions[labels.index(choice)]['id']); self.load_asset(self.current); self.refresh()

    def trash(self):
        identifiers=self.chosen()
        if QMessageBox.question(self,'移入项目回收区',f'将 {len(identifiers)} 张移入逻辑回收区？\n源快照和工作版本保留，用户原目录不会改变。')!=QMessageBox.StandardButton.Yes: return
        from tushu.services.processing import remove_assets
        remove_assets(self.project,identifiers)
        if self.current in identifiers:
            self.current=None; self.canvas.load(None,1,1,[],[]); self.box_table.setRowCount(0)
        self.refresh()

    def restore_trash(self):
        self.require_project()
        with self.project.transaction() as db:
            db.execute("UPDATE assets SET removed=0,state='pending' WHERE removed=1")
            self.project.invalidate_plans(db,'恢复回收区')
        self.refresh()

    def rename_project(self):
        self.require_project()
        name,ok=QInputDialog.getText(self,'重命名项目','名称',text=self.project.name)
        if ok: self.project.rename(name); self.project_label.setText(name+'  '); self.remember(self.project.root)

    def archive(self):
        self.require_project()
        with self.project.transaction() as db:
            db.execute('UPDATE projects SET archived=1-archived')
        self.status.setText('项目已归档' if self.project.one('SELECT archived FROM projects')['archived'] else '已取消归档')

    def backup(self):
        self.require_project()
        folder=QFileDialog.getExistingDirectory(self,'选择项目以外的备份父目录')
        if folder:
            from tushu.infrastructure.backup import backup
            self.start_task('备份项目',lambda ctx:backup(self.project,folder,ctx),lambda path:message(self,'备份完成',path))

    def restore(self):
        if self.worker and self.worker.isRunning(): return
        source=QFileDialog.getExistingDirectory(self,'选择备份目录（含 checksums.json）')
        if not source: return
        destination=QFileDialog.getExistingDirectory(self,'选择恢复父目录')
        if not destination: return
        from tushu.infrastructure.backup import restore
        # Can restore even when no project is open; use a separate read-only worker.
        worker=Worker(None,'恢复备份',lambda ctx:restore(source,destination),self)
        self.worker=worker
        worker.result.connect(lambda path:QTimer.singleShot(100,lambda:self.guard(lambda:self.open_project(path))))
        worker.error.connect(lambda text:QMessageBox.warning(self,'恢复失败',text))
        worker.finished.connect(self.task_finished); worker.start()

    def tasks(self):
        self.require_project()
        dialog=QDialog(self); dialog.setWindowTitle('任务中心 · 历史结果与失败清单'); dialog.resize(880,600)
        layout=QVBoxLayout(dialog)
        tasks=self.project.rows('SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100')
        table=QTableWidget(len(tasks),4); table.setHorizontalHeaderLabels(['类型','状态','进度','开始时间（本地）'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for row,task in enumerate(tasks):
            for column,key in enumerate(('type','status','progress_json','created_at')):
                value=task[key] or ''
                if key=='created_at':
                    from datetime import datetime
                    value=datetime.fromisoformat(value).astimezone().strftime('%Y-%m-%d %H:%M:%S')
                table.setItem(row,column,QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        details=QTextEdit(); details.setReadOnly(True); layout.addWidget(details)
        table.currentCellChanged.connect(lambda row,*args:details.setPlainText(json.dumps(tasks[row],ensure_ascii=False,indent=2)) if row>=0 else None)
        retry=QPushButton('重试最近推理中失败／未完成图片（需先加载同一模型）')
        def retry_inference():
            if not self.model or not self.mapping:
                QMessageBox.warning(dialog,'请先配置模型','先在数据集菜单加载模型并完成映射。'); return
            runs=self.project.rows('SELECT * FROM inference_runs ORDER BY created_at DESC LIMIT 1')
            if not runs: return
            run=runs[0]
            if run['model_package_id']!=self.model.id:
                QMessageBox.warning(dialog,'模型不匹配','请加载原任务模型'); return
            completed={i['version_id'] for i in self.project.rows("SELECT version_id FROM inference_items WHERE run_id=? AND status='success'",(run['id'],))}
            snapshot=json.loads(run['input_snapshot_json'])
            chosen=[a for a in snapshot if a['active_version_id'] not in completed]
            for asset in chosen:
                fresh=self.project.asset(asset['id'])
                if fresh['active_version_id']!=asset['active_version_id'] or fresh['revision']!=asset['revision']:
                    QMessageBox.warning(dialog,'输入版本已变','请重新选择图片并确认新预标注任务。'); return
            if not chosen: QMessageBox.information(dialog,'无待重试项','最近推理已经全部完成。'); return
            dialog.accept()
            from tushu.services.inferencing import run as infer_run
            self.start_task('重试本地预标注',lambda ctx:infer_run(self.project,[a['id'] for a in chosen],self.model,self.mapping,self.threshold,self.nms,ctx),lambda result:message(self,'重试报告',result))
        retry.clicked.connect(retry_inference); layout.addWidget(retry)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(dialog.reject); layout.addWidget(close)
        dialog.exec()

    def clear_cache(self):
        self.require_project()
        count=0
        for folder in ('thumbnails','previews'):
            for path in (self.project.root/folder).glob('*.png'): path.unlink(); count+=1
        self.asset_model.icons.clear(); self.refresh()
        self.status.setText(f'已清理 {count} 个缓存文件；可在工具菜单重新生成')
        # Rebuild in a bounded sequential background stream, never materialize the whole image set.
        def rebuild(ctx):
            from PIL import Image
            from tushu.services.importing import cache_image
            assets=self.project.assets()
            for index,asset in enumerate(assets):
                ctx.checkpoint()
                with Image.open(self.project.path(asset['path'])) as image: cache_image(self.project,image,asset['sha256'])
                ctx.progress(index+1,len(assets),asset['display_name'])
            return len(assets)
        self.start_task('重建图像缓存',rebuild)

    def preferences(self):
        dialog=QDialog(self); dialog.setWindowTitle('设置'); layout=QVBoxLayout(dialog); form=QFormLayout()
        workspace=QLineEdit(self.settings.value('workspace',str(Path.home()/'Pictures')))
        background=QLineEdit(self.settings.value('background','#ffffff'))
        form.addRow('默认项目父目录',workspace); form.addRow('JPEG 默认背景色',background)
        layout.addLayout(form)
        layout.addWidget(QLabel('容量上限：10000 张／项目，2000 张／次，100 MiB／文件，3000 万像素／图。\n'
                               '推理并发 1，逐图处理；预览最长边 2048，缩略图最长边 256。'))
        buttons(dialog,layout)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            if not QColor(background.text()).isValid(): raise ValueError('背景颜色无效')
            self.settings.setValue('workspace',workspace.text()); self.settings.setValue('background',background.text())

    def environment(self):
        from tushu.app.check import environment
        message(self,'环境自检',environment())

    def help(self):
        message(self,'使用说明与快捷键',
            '新建项目 → 导入图片 → 管理类别 → 人工画框或本地预标注 → 逐图复核 → 质量检查 → 创建划分 → 导出。\n\n'
            '植物物种可建立人工类别；YOLOX COCO 只支持其 80 类，不会因新增类别自动获得识别能力。\n\n'
            'A / D 上一张、下一张；W 画框；Esc 选择；Space 拖动平移；滚轮缩放。\n'
            '1—9 选择前九类；Delete 删除所选框；Ctrl/⌘ Z 撤销，Shift Z 重做；F 适应窗口。\n'
            'Ctrl/⌘ Enter 完成复核；所有框命令自动提交，保存成功后显示“已保存”。\n\n'
            '复核无框时需明确确认负样本；隐藏框时禁止复核。增强仅用于已划分的训练组，增强后须再次复核。\n'
            '导出后会独立回读验证，成功才发布正式目录。YOLO 迁移目录后运行包内 relocate_dataset.py。\n'
            '完整操作说明见交付目录 docs/用户手册.md。')

    def context_menu(self,point):
        menu=QMenu(self)
        for label,handler in [('批量处理…',self.process),('排除图片…',self.exclude),('历史版本…',self.versions)]:
            self.action(menu,label,handler)
        menu.exec(self.list.viewport().mapToGlobal(point))

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self,'任务仍在运行','请求取消并在任务安全结束后退出？')==QMessageBox.StandardButton.Yes:
                self.cancel_task()
                self.worker.finished.connect(self.close)
            event.ignore(); return
        self.close_project(); event.accept()
