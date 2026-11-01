from __future__ import annotations

from collections import OrderedDict
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QIcon
from tushu.domain.entities import STATES


class AssetModel(QAbstractListModel):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.assets=[]
        self.project=None
        self.icons=OrderedDict()

    def reset(self,project,assets):
        self.beginResetModel()
        self.project=project
        self.assets=assets
        self.endResetModel()

    def rowCount(self,parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.assets)

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row()>=len(self.assets):
            return None
        asset=self.assets[index.row()]
        if role==Qt.ItemDataRole.DisplayRole:
            return f"{asset['display_name']}\n{asset['width']} × {asset['height']} · {STATES[asset['state']]}"
        if role==Qt.ItemDataRole.ToolTipRole:
            return f"{asset['display_name']}\n{STATES[asset['state']]}\n{asset['excluded_reason']}"
        if role==Qt.ItemDataRole.DecorationRole:
            key=asset['sha256']
            if key not in self.icons:
                path=self.project.root/'thumbnails'/f'{key}.png'
                self.icons[key]=QIcon(str(path)) if path.exists() else QIcon()
                while len(self.icons)>100:
                    self.icons.popitem(last=False)
            else:
                self.icons.move_to_end(key)
            return self.icons[key]
        if role==Qt.ItemDataRole.UserRole:
            return asset['id']
        return None
