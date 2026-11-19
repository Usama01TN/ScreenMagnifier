# -*- coding: utf-8 -*-
"""
ColorSwatchesWidget: a grid of color swatches, e.g. a color-picker history.
- Newest first; adding an existing color moves it to the front; at most maxColors are kept.
- Click a swatch: colorClicked(QColor); right-click: removes it (colorRemoved(int)).
- Hover highlight and a tooltip with the HEX code; columns adapt to the width (heightForWidth).
"""
from ManyQt.QtCore import Qt, QRectF, QSize, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtWidgets import QWidget, QToolTip, QSizePolicy
from ManyQt.QtGui import QPainter, QColor, QPen, QFont


class ColorSwatchesWidget(QWidget):
    """
    ColorSwatchesWidget class.
    """
    colorClicked = pyqtSignal(QColor)  # type: pyqtSignal
    colorRemoved = pyqtSignal(int)  # type: pyqtSignal
    colorsChanged = pyqtSignal()  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param colors: (list[QColor | str]) Initial colors, newest first.
        :param maxColors: (int) Older colors are dropped beyond this.
        :param swatchSize: (int) Swatch edge in px.
        :param spacing: (int) Gap between swatches in px.
        :param placeholderText: (str | unicode | QString) Shown when empty.
        :param colorClicked: callable | None
        :param colorRemoved: callable | None
        :param colorsChanged: callable | None
        :param args: any
        :param kwargs: any
        """
        colors = kwargs.pop('colors', [])  # type: list
        maxColors = kwargs.pop('maxColors', 24)  # type: int
        swatchSize = kwargs.pop('swatchSize', 24)  # type: int
        spacing = kwargs.pop('spacing', 6)  # type: int
        placeholderText = kwargs.pop('placeholderText', 'No colors yet')  # type: str
        colorClicked = kwargs.pop('colorClicked', None)  # type: callable | None
        colorRemoved = kwargs.pop('colorRemoved', None)  # type: callable | None
        colorsChanged = kwargs.pop('colorsChanged', None)  # type: callable | None
        super(ColorSwatchesWidget, self).__init__(*args, **kwargs)
        for signal, slot in ((self.colorClicked, colorClicked), (self.colorRemoved, colorRemoved),
                             (self.colorsChanged, colorsChanged)):
            if callable(slot):
                signal.connect(slot)
        self.__m_maxColors = max(1, int(maxColors))  # type: int
        self.__m_swatchSize = max(8, int(swatchSize))  # type: int
        self.__m_spacing = max(0, int(spacing))  # type: int
        self.__m_placeholderText = placeholderText  # type: str
        self.__m_colors = [QColor(c) for c in colors if QColor(c).isValid()][:self.__m_maxColors]  # type: list
        self.__m_hover = -1  # type: int
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)  # type: QSizePolicy
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    # ---------- Helpers ----------
    def _columns(self, width=None):
        """
        :param width: (int | None) Widget width (None = current).
        :return: int
        """
        w = self.width() if width is None else int(width)  # type: int
        return max(1, (w + self.__m_spacing) // (self.__m_swatchSize + self.__m_spacing))

    def _rect(self, index):
        """
        :param index: int
        :return: QRectF
        """
        cols = self._columns()  # type: int
        step = self.__m_swatchSize + self.__m_spacing  # type: int
        return QRectF((index % cols) * step + 1, (index // cols) * step + 1, self.__m_swatchSize - 2,
                      self.__m_swatchSize - 2)

    def _indexAt(self, pos):
        """
        :param pos: QPoint
        :return: (int) Swatch index, -1 if none.
        """
        for i in range(len(self.__m_colors)):
            if self._rect(i).adjusted(-1, -1, 1, 1).contains(pos.x(), pos.y()):
                return i
        return -1

    def _changed(self):
        """
        :return:
        """
        self.updateGeometry()
        self.update()
        self.colorsChanged.emit()

    # ---------- Public API ----------
    def getColors(self):
        """
        :return: (list[QColor]) Newest first.
        """
        return [QColor(c) for c in self.__m_colors]

    @pyqtSlot(list)
    def setColors(self, colors):
        """
        :param colors: list[QColor | str]
        :return:
        """
        self.__m_colors = [QColor(c) for c in colors if QColor(c).isValid()][:self.__m_maxColors]  # type: list[QColor]
        self._changed()

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def addColor(self, color):
        """
        Put a color first (moving it if already present).
        :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
        :return:
        """
        c = QColor(color)  # type: QColor
        if not c.isValid():
            return
        self.__m_colors = [x for x in self.__m_colors if x.rgb() != c.rgb()]  # type: list
        self.__m_colors.insert(0, c)
        del self.__m_colors[self.__m_maxColors:]
        self._changed()

    @pyqtSlot(int)
    def removeColor(self, index):
        """
        :param index: int
        :return:
        """
        if 0 <= int(index) < len(self.__m_colors):
            del self.__m_colors[int(index)]
            self.__m_hover = -1  # type: int
            self._changed()
            self.colorRemoved.emit(int(index))

    @pyqtSlot()
    def clear(self):
        """
        :return:
        """
        if self.__m_colors:
            self.__m_colors = []  # type: list
            self._changed()

    def getMaxColors(self):
        """
        :return: int
        """
        return self.__m_maxColors

    @pyqtSlot(int)
    def setMaxColors(self, maxColors):
        """
        :param maxColors: int
        :return:
        """
        self.__m_maxColors = max(1, int(maxColors))  # type: int
        del self.__m_colors[self.__m_maxColors:]
        self._changed()

    def getSwatchSize(self):
        """
        :return: int
        """
        return self.__m_swatchSize

    @pyqtSlot(int)
    def setSwatchSize(self, swatchSize):
        """
        :param swatchSize: int
        :return:
        """
        self.__m_swatchSize = max(8, int(swatchSize))  # type: int
        self._changed()

    def getSpacing(self):
        """
        :return: int
        """
        return self.__m_spacing

    @pyqtSlot(int)
    def setSpacing(self, spacing):
        """
        :param spacing: int
        :return:
        """
        self.__m_spacing = max(0, int(spacing))  # type: int
        self._changed()

    def getPlaceholderText(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_placeholderText

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setPlaceholderText(self, placeholderText):
        """
        :param placeholderText: str | unicode | QString
        :return:
        """
        self.__m_placeholderText = placeholderText  # type: str
        self.update()

    # ---------- Qt overrides ----------
    def hasHeightForWidth(self):
        """
        :return: bool
        """
        return True

    def heightForWidth(self, width):
        """
        :param width: int
        :return: int
        """
        rows = max(1, (len(self.__m_colors) + self._columns(width) - 1) // self._columns(width))  # type: int
        return rows * (self.__m_swatchSize + self.__m_spacing)

    def sizeHint(self):
        """
        :return: QSize
        """
        return QSize(8 * (self.__m_swatchSize + self.__m_spacing), self.heightForWidth(
            8 * (self.__m_swatchSize + self.__m_spacing)))

    def minimumSizeHint(self):
        """
        :return: QSize
        """
        return QSize(self.__m_swatchSize, self.__m_swatchSize)

    def resizeEvent(self, e):
        """
        :param e: QResizeEvent
        :return:
        """
        super(ColorSwatchesWidget, self).resizeEvent(e)
        self.updateGeometry()

    def mouseMoveEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        index = self._indexAt(e.pos())  # type: int
        if index != self.__m_hover:
            self.__m_hover = index  # type: int
            self.update()
        if index >= 0:
            QToolTip.showText(self.mapToGlobal(e.pos()), self.tr(u'{}  -  click: copy, right-click: remove').format(
                u'{}'.format(self.__m_colors[index].name()).upper()), self)
        super(ColorSwatchesWidget, self).mouseMoveEvent(e)

    def leaveEvent(self, e):
        """
        :param e: QEvent
        :return:
        """
        self.__m_hover = -1  # type: int
        self.update()
        super(ColorSwatchesWidget, self).leaveEvent(e)

    def mouseReleaseEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        index = self._indexAt(e.pos())  # type: int
        if index >= 0:
            if e.button() == Qt.LeftButton:
                self.colorClicked.emit(QColor(self.__m_colors[index]))
            elif e.button() == Qt.RightButton:
                self.removeColor(index)
        super(ColorSwatchesWidget, self).mouseReleaseEvent(e)

    def paintEvent(self, event):
        """
        :param event: QPaintEvent
        :return:
        """
        p = QPainter(self)  # type: QPainter
        p.setRenderHint(QPainter.Antialiasing, True)
        if not self.__m_colors:
            font = QFont(self.font())  # type: QFont
            font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
            p.setFont(font)
            p.setPen(QColor('#7C8498'))
            p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, self.__m_placeholderText)
            p.end()
            return
        for i, c in enumerate(self.__m_colors):
            r = self._rect(i)  # type: QRectF
            hover = i == self.__m_hover  # type: bool
            if hover:
                r = r.adjusted(-1, -1, 1, 1)  # type: QRectF
            p.setPen(QPen(QColor(255, 255, 255, 230) if hover else QColor(255, 255, 255, 70), 2 if hover else 1))
            p.setBrush(c)
            p.drawRoundedRect(r, 5, 5)
        p.end()

    # ---------- Properties ----------
    colors = pyqtProperty(list, fget=getColors, fset=setColors, notify=colorsChanged)  # type: pyqtProperty
    maxColors = pyqtProperty(int, fget=getMaxColors, fset=setMaxColors)  # type: pyqtProperty
    swatchSize = pyqtProperty(int, fget=getSwatchSize, fset=setSwatchSize)  # type: pyqtProperty
    spacing = pyqtProperty(int, fget=getSpacing, fset=setSpacing)  # type: pyqtProperty
    placeholderText = pyqtProperty('QString', fget=getPlaceholderText, fset=setPlaceholderText)  # type: pyqtProperty
