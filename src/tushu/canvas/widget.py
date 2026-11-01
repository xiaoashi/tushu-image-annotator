from __future__ import annotations

from dataclasses import replace
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget
from tushu.domain.entities import Box


class Coordinates:
    def __init__(self):
        self.scale=1.
        self.offset=QPointF()

    def screen(self,x,y):
        return QPointF(x*self.scale+self.offset.x(),y*self.scale+self.offset.y())

    def image(self,point):
        return ((point.x()-self.offset.x())/self.scale,(point.y()-self.offset.y())/self.scale)


class Canvas(QWidget):
    command = Signal(object,str)
    selected = Signal(str)
    zoom_changed = Signal(float)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(350,300)
        self.coords=Coordinates()
        self.image=QImage()
        self.full_size=(1,1)
        self.boxes=[]
        self.categories={}
        self.category=None
        self.active=None
        self.mode='select'
        self.hidden_classes=set()
        self.minimum_score=0.
        self.locked=False
        self.space=False
        self.gesture=None
        self.draft=None
        self.drag_start=None
        self.before=None
        self.fit_pending=False

    def load(self,path,width,height,boxes,categories):
        self.image=QImage(str(path)) if path else QImage()
        self.full_size=(width,height)
        self.boxes=[replace(b) for b in boxes]
        self.categories={c['id']:c for c in categories}
        self.active=None
        self.gesture=None
        self.draft=None
        self.fit()

    def visible(self,box):
        return box.category_id not in self.hidden_classes and (box.score is None or box.score>=self.minimum_score)

    @property
    def has_hidden(self):
        return any(not self.visible(b) for b in self.boxes)

    def fit(self):
        width,height=self.full_size
        self.coords.scale=1. if self.image.isNull() else max(.05,min(16.,min(max(1,self.width()-64)/width,max(1,self.height()-64)/height)))
        self.coords.offset=QPointF((self.width()-width*self.coords.scale)/2,(self.height()-height*self.coords.scale)/2)
        self.zoom_changed.emit(self.coords.scale)
        self.update()

    def zoom(self,scale,anchor=None):
        anchor=anchor or QPointF(self.width()/2,self.height()/2)
        image_point=self.coords.image(anchor)
        self.coords.scale=max(.05,min(16.,scale))
        self.coords.offset=anchor-QPointF(image_point[0]*self.coords.scale,image_point[1]*self.coords.scale)
        self.zoom_changed.emit(self.coords.scale)
        self.update()

    def resizeEvent(self,event):
        if self.image.isNull():
            self.fit()
        super().resizeEvent(event)

    def rect(self,box):
        return QRectF(self.coords.screen(box.x1,box.y1),self.coords.screen(box.x2,box.y2))

    def handles(self,box):
        rectangle=self.rect(box)
        x1,y1,x2,y2=rectangle.left(),rectangle.top(),rectangle.right(),rectangle.bottom()
        return [QPointF(x1,y1),QPointF((x1+x2)/2,y1),QPointF(x2,y1),QPointF(x2,(y1+y2)/2),
                QPointF(x2,y2),QPointF((x1+x2)/2,y2),QPointF(x1,y2),QPointF(x1,(y1+y2)/2)]

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.fillRect(self.rect_widget(),QColor('#202725'))
        if self.image.isNull():
            painter.setPen(QColor('#d0d9d5'))
            painter.drawText(self.rect_widget(),Qt.AlignmentFlag.AlignCenter,
                             '图枢\n\n新建或打开项目，然后导入图片\n\n支持 JPEG · PNG · 静态 WebP')
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        width,height=self.full_size
        target=QRectF(self.coords.screen(0,0),self.coords.screen(width,height))
        painter.fillRect(target,QColor('#f0f0ed'))
        painter.drawImage(target,self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for box in self.boxes:
            if not self.visible(box):
                continue
            category=self.categories.get(box.category_id,{})
            color=QColor(category.get('color','#e0bb61'))
            rectangle=self.rect(box)
            painter.setPen(QPen(color,2 if box.id==self.active else 1.4))
            painter.drawRect(rectangle)
            label=category.get('display_name','未知类别')
            if box.score is not None:
                label+=f' {box.score:.2f}'
            text_width=painter.fontMetrics().horizontalAdvance(label)+10
            label_rect=QRectF(rectangle.left(),max(target.top(),rectangle.top()-22),text_width,22)
            painter.fillRect(label_rect,color)
            luminance=.2126*color.redF()+.7152*color.greenF()+.0722*color.blueF()
            painter.setPen(QColor('#111c17') if luminance>.55 else QColor('white'))
            painter.drawText(label_rect.adjusted(5,0,-3,0),Qt.AlignmentFlag.AlignVCenter,label)
            if box.id==self.active and not self.locked:
                painter.setPen(QPen(color,1))
                painter.setBrush(QColor('white'))
                for point in self.handles(box):
                    painter.drawRect(QRectF(point.x()-4,point.y()-4,8,8))
                painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.draft:
            painter.setPen(QPen(QColor('#f5d57a'),1.5,Qt.PenStyle.DashLine))
            painter.drawRect(self.draft)
        if self.locked:
            painter.fillRect(QRectF(12,12,210,30),QColor('#152a22'))
            painter.setPen(QColor('white'))
            painter.drawText(QRectF(20,12,200,30),Qt.AlignmentFlag.AlignVCenter,'后台任务运行中 · 编辑已锁定')

    def rect_widget(self):
        return QRectF(0,0,self.width(),self.height())

    def clamped(self,point):
        x,y=self.coords.image(point)
        return max(0,min(self.full_size[0],x)),max(0,min(self.full_size[1],y))

    def mousePressEvent(self,event):
        self.setFocus()
        if self.image.isNull():
            return
        point=event.position()
        self.drag_start=point
        self.image_start=self.clamped(point)
        if self.space or event.button()==Qt.MouseButton.MiddleButton:
            self.gesture='pan'
            self.old_offset=QPointF(self.coords.offset)
            return
        if self.locked or event.button()!=Qt.MouseButton.LeftButton:
            return
        if self.mode=='draw' and self.category:
            self.gesture='draw'
            return
        selected=next((b for b in self.boxes if b.id==self.active),None)
        if selected and self.visible(selected):
            for index,handle in enumerate(self.handles(selected)):
                if abs(point.x()-handle.x())<=7 and abs(point.y()-handle.y())<=7:
                    self.gesture=f'resize:{index}'
                    self.before=replace(selected)
                    return
        hit=next((b for b in reversed(self.boxes) if self.visible(b) and self.rect(b).contains(point)),None)
        self.active=hit.id if hit else None
        self.selected.emit(self.active or '')
        if hit:
            self.gesture='move'
            self.before=replace(hit)
        self.update()

    def mouseMoveEvent(self,event):
        point=event.position()
        if self.gesture=='pan':
            self.coords.offset=self.old_offset+point-self.drag_start
        elif self.gesture=='draw':
            self.draft=QRectF(self.coords.screen(*self.image_start),self.coords.screen(*self.clamped(point))).normalized()
        elif self.gesture in ('move',) or (self.gesture or '').startswith('resize:'):
            x,y=self.clamped(point)
            before=self.before
            if self.gesture=='move':
                dx,dy=x-self.image_start[0],y-self.image_start[1]
                dx=max(-before.x1,min(self.full_size[0]-before.x2,dx))
                dy=max(-before.y1,min(self.full_size[1]-before.y2,dy))
                current=replace(before,x1=before.x1+dx,x2=before.x2+dx,y1=before.y1+dy,y2=before.y2+dy)
            else:
                index=int(self.gesture.split(':')[1])
                x1,y1,x2,y2=before.x1,before.y1,before.x2,before.y2
                if index in (0,6,7): x1=min(x,x2-1)
                if index in (2,3,4): x2=max(x,x1+1)
                if index in (0,1,2): y1=min(y,y2-1)
                if index in (4,5,6): y2=max(y,y1+1)
                current=replace(before,x1=x1,y1=y1,x2=x2,y2=y2)
            self.boxes=[current if b.id==before.id else b for b in self.boxes]
        elif not self.locked:
            self.setCursor(Qt.CursorShape.CrossCursor if self.mode=='draw' else Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseReleaseEvent(self,event):
        gesture=self.gesture
        self.gesture=None
        self.draft=None
        if gesture=='draw':
            x,y=self.clamped(event.position())
            x0,y0=self.image_start
            if (event.position()-self.drag_start).manhattanLength()>=3 and abs(x-x0)>=1 and abs(y-y0)>=1:
                box=Box(self.category,min(x,x0),min(y,y0),max(x,x0),max(y,y0))
                self.command.emit(self.boxes+[box],'create')
                self.active=box.id
                self.selected.emit(box.id)
        elif gesture=='move' or (gesture or '').startswith('resize:'):
            box=next(b for b in self.boxes if b.id==self.before.id)
            if box.to_dict()!=self.before.to_dict():
                box.edited=True
                self.command.emit(self.boxes,gesture)
        self.update()

    def wheelEvent(self,event):
        self.zoom(self.coords.scale*(1.15 if event.angleDelta().y()>0 else 1/1.15),event.position())
        event.accept()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Space:
            self.space=True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self,event):
        if event.key()==Qt.Key.Key_Space:
            self.space=False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            super().keyReleaseEvent(event)

    def cancel_gesture(self):
        if self.before and (self.gesture=='move' or (self.gesture or '').startswith('resize:')):
            self.boxes=[replace(self.before) if b.id==self.before.id else b for b in self.boxes]
        self.gesture=None
        self.draft=None
        self.mode='select'
        self.update()
