# --- START OF FILE modules/custom_widgets_module.py ---

from PyQt5.QtWidgets import QCheckBox, QWidget, QHBoxLayout, QSlider, QVBoxLayout, QLabel, QLineEdit, QGridLayout, QFrame, QDialog, QApplication
from PyQt5.QtCore import Qt, pyqtProperty, QPropertyAnimation, QEasingCurve, QRect, pyqtSignal, QPoint, QEvent
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush

# ==============================================================================
# 1. 自定义 ToggleSwitch 控件
# ==============================================================================
class ToggleSwitch(QCheckBox):
    """
    一个可自定义样式的切换开关控件，支持并行的、平滑的过渡动画，
    精细的QSS悬停控制，以及标准的“释放时切换”和“拖动切换”交互。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        
        # --- 默认状态属性 ---
        self._trackColorOff = QColor("#E0E0E0")
        self._trackColorOn = QColor("#8F4C33")
        self._knobColor = QColor("#FFFFFF")
        self._borderColor = QColor(Qt.transparent)
        
        # --- 悬停状态专属属性 ---
        self._hover_knobColor = QColor(Qt.transparent)
        self._hover_trackColorOff = QColor(Qt.transparent)
        self._hover_trackColorOn = QColor(Qt.transparent)
        self._hover_borderColor = QColor(Qt.transparent)
        self._hover_knobMarginOffset = 0

        # --- 其他视觉属性 ---
        self._trackBorderRadius = 14
        self._knobMargin = 3
        self._knobShape = 'ellipse'
        self._knobBorderRadius = 0 
        self._borderWidth = 0
        
        self._is_hovering = False
        self._is_mouse_down = False
        self._has_moved = False

        # --- 动画系统 ---
        self._knob_position_ratio = 0.0
        self._knob_margin_anim_value = self._knobMargin

        self.pos_animation = QPropertyAnimation(self, b"_knob_position_ratio", self)
        self.margin_animation = QPropertyAnimation(self, b"_knob_margin_anim_value", self)

        self.pos_animation.setDuration(120)
        self.margin_animation.setDuration(120)
        
        self.pos_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.margin_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.toggled.connect(self._start_toggle_animation)

        self._knob_position_ratio = 1.0 if self.isChecked() else 0.0
        self._knob_margin_anim_value = self._knobMargin

    # --- 动画目标属性的 pyqtProperty ---
    @pyqtProperty(float)
    def _knob_position_ratio(self):
        return self.__knob_position_ratio
    @_knob_position_ratio.setter
    def _knob_position_ratio(self, value):
        self.__knob_position_ratio = value; self.update()

    @pyqtProperty(int)
    def _knob_margin_anim_value(self):
        return self.__knob_margin_anim_value
    @_knob_margin_anim_value.setter
    def _knob_margin_anim_value(self, value):
        self.__knob_margin_anim_value = value; self.update()

    # --- 动画与事件处理 ---
    def _start_toggle_animation(self, checked):
        self.pos_animation.setStartValue(self._knob_position_ratio)
        self.pos_animation.setEndValue(1.0 if checked else 0.0)
        self.pos_animation.start()

    def _start_margin_animation(self, hover):
        start_value = self._knob_margin_anim_value
        if hover:
            default_offset = -1
            offset = self._hover_knobMarginOffset if self._hover_knobMarginOffset != 0 else default_offset
            end_value = self._knobMargin + offset
        else:
            end_value = self._knobMargin
        
        self.margin_animation.setStartValue(start_value)
        self.margin_animation.setEndValue(end_value)
        self.margin_animation.start()

    def enterEvent(self, event):
        self._is_hovering = True
        self.style().unpolish(self); self.style().polish(self)
        self._start_margin_animation(True) 
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovering = False
        self.style().unpolish(self); self.style().polish(self)
        self._start_margin_animation(False) 
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_mouse_down = True
            self._has_moved = False
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self._is_mouse_down:
            self._has_moved = True
            track_rect = self.rect().adjusted(self._borderWidth, self._borderWidth, -self._borderWidth, -self._borderWidth)
            margin = self._knob_margin_anim_value
            knob_width = track_rect.height() - (2 * margin)
            start_x = track_rect.left() + margin
            end_x = track_rect.right() - knob_width - margin
            pos_x = event.pos().x()
            ratio = (pos_x - start_x) / (end_x - start_x) if (end_x - start_x) != 0 else 0
            self._knob_position_ratio = max(0.0, min(1.0, ratio))
            event.accept()
        else:
            super().mouseMoveEvent(event)
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._is_mouse_down:
            self._is_mouse_down = False
            if self._has_moved:
                new_state_is_on = self._knob_position_ratio > 0.5
                if self.isChecked() != new_state_is_on:
                    self.setChecked(new_state_is_on)
                else:
                    self._start_toggle_animation(self.isChecked())
            else:
                self.toggle()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    @pyqtProperty(bool)
    def hover(self): return self._is_hovering
    # ... (所有颜色/尺寸相关的 pyqtProperty getter/setter 省略，保持不变) ...
    @pyqtProperty(QColor)
    def trackColorOff(self): return self._trackColorOff
    @trackColorOff.setter
    def trackColorOff(self, color): self._trackColorOff = color; self.update()
    @pyqtProperty(QColor)
    def trackColorOn(self): return self._trackColorOn
    @trackColorOn.setter
    def trackColorOn(self, color): self._trackColorOn = color; self.update()
    @pyqtProperty(QColor)
    def knobColor(self): return self._knobColor
    @knobColor.setter
    def knobColor(self, color): self._knobColor = color; self.update()
    @pyqtProperty(QColor)
    def borderColor(self): return self._borderColor
    @borderColor.setter
    def borderColor(self, color): self._borderColor = color; self.update()
    @pyqtProperty(int)
    def trackBorderRadius(self): return self._trackBorderRadius
    @trackBorderRadius.setter
    def trackBorderRadius(self, radius): self._trackBorderRadius = radius; self.update()
    @pyqtProperty(int)
    def knobMargin(self): return self._knobMargin
    @knobMargin.setter
    def knobMargin(self, margin): self._knobMargin = margin; self.update()
    @pyqtProperty(str)
    def knobShape(self): return self._knobShape
    @knobShape.setter
    def knobShape(self, shape):
        if shape in ['ellipse', 'rectangle']: self._knobShape = shape; self.update()
    @pyqtProperty(int)
    def knobBorderRadius(self): return self._knobBorderRadius
    @knobBorderRadius.setter
    def knobBorderRadius(self, radius): self._knobBorderRadius = radius; self.update()
    @pyqtProperty(int)
    def borderWidth(self): return self._borderWidth
    @borderWidth.setter
    def borderWidth(self, width): self._borderWidth = width; self.update()
    @pyqtProperty(QColor)
    def hoverKnobColor(self): return self._hover_knobColor
    @hoverKnobColor.setter
    def hoverKnobColor(self, color): self._hover_knobColor = color; self.update()
    @pyqtProperty(QColor)
    def hoverTrackColorOff(self): return self._hover_trackColorOff
    @hoverTrackColorOff.setter
    def hoverTrackColorOff(self, color): self._hover_trackColorOff = color; self.update()
    @pyqtProperty(QColor)
    def hoverTrackColorOn(self): return self._hover_trackColorOn
    @hoverTrackColorOn.setter
    def hoverTrackColorOn(self, color): self._hover_trackColorOn = color; self.update()
    @pyqtProperty(QColor)
    def hoverBorderColor(self): return self._hover_borderColor
    @hoverBorderColor.setter
    def hoverBorderColor(self, color): self._hover_borderColor = color; self.update()
    @pyqtProperty(int)
    def hoverKnobMarginOffset(self): return self._hover_knobMarginOffset
    @hoverKnobMarginOffset.setter
    def hoverKnobMarginOffset(self, offset): self._hover_knobMarginOffset = offset; self.update()


    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        border_color = self._hover_borderColor if self._is_hovering and self._hover_borderColor.isValid() else self._borderColor
        track_on_color = self._hover_trackColorOn if self._is_hovering and self._hover_trackColorOn.isValid() else self._trackColorOn
        track_off_color = self._hover_trackColorOff if self._is_hovering and self._hover_trackColorOff.isValid() else self._trackColorOff
        knob_color = self._hover_knobColor if self._is_hovering and self._hover_knobColor.isValid() else self._knobColor
        if self._borderWidth > 0 and border_color.isValid() and border_color.alpha() > 0:
            pen = QPen(border_color, self._borderWidth); pen.setJoinStyle(Qt.RoundJoin); p.setPen(pen)
            border_rect = rect.adjusted(self._borderWidth//2, self._borderWidth//2, -self._borderWidth//2, -self._borderWidth//2)
            p.setBrush(Qt.NoBrush); p.drawRoundedRect(border_rect, self._trackBorderRadius, self._trackBorderRadius)
        track_color = QColor(track_off_color)
        track_color.setRed(int(track_off_color.red() + (track_on_color.red() - track_off_color.red()) * self._knob_position_ratio))
        track_color.setGreen(int(track_off_color.green() + (track_on_color.green() - track_off_color.green()) * self._knob_position_ratio))
        track_color.setBlue(int(track_off_color.blue() + (track_on_color.blue() - track_off_color.blue()) * self._knob_position_ratio))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(track_color))
        track_rect = rect.adjusted(self._borderWidth, self._borderWidth, -self._borderWidth, -self._borderWidth)
        track_inner_radius = max(0, self._trackBorderRadius - self._borderWidth)
        p.drawRoundedRect(track_rect, track_inner_radius, track_inner_radius)
        margin = self._knob_margin_anim_value
        knob_height = track_rect.height() - (2 * margin)
        knob_width = knob_height 
        start_x = track_rect.left() + margin
        end_x = track_rect.right() - knob_width - margin + 1
        current_x = start_x + (end_x - start_x) * self._knob_position_ratio
        knob_rect = QRect(int(current_x), track_rect.top() + margin, knob_width, knob_height)
        p.setBrush(QBrush(knob_color))
        if self.knobShape == 'rectangle': p.drawRoundedRect(knob_rect, self._knobBorderRadius, self._knobBorderRadius)
        else: p.drawEllipse(knob_rect)
    
    def resizeEvent(self, event):
        self._knob_position_ratio = 1.0 if self.isChecked() else 0.0
        self._knob_margin_anim_value = self._knobMargin
        super().resizeEvent(event)

# ==============================================================================
# 2. 自定义 RangeSlider 控件 (v1.7 - 增加渐变支持与完全向后兼容性)
# ==============================================================================
class RangeSlider(QWidget):
    rangeChanged = pyqtSignal(int, int)

    def __init__(self, orientation, parent=None):
        super().__init__(parent)
        self.setMinimumSize(150, 30)
        self.setMouseTracking(True)
        
        self._min_val, self._max_val = 0, 100
        self._lower_val, self._upper_val = 20, 80
        
        self._first_handle_pressed = False
        self._second_handle_pressed = False
        self._first_handle_hovered = False
        self._second_handle_hovered = False
        self._track_hovered = False
        self.first_handle_rect = QRect()
        self.second_handle_rect = QRect()
        
        self._bar_height = 6
        self._handle_width = 18
        self._handle_height = 18
        self._handle_border_width = 2
        self._handleRadius = 9
        
        self._hover_bar_height = 0
        self._hover_handle_width = 0
        self._hover_handle_height = 0
        self._pressed_handle_width = 0
        self._pressed_handle_height = 0
        
        # [核心修改] 颜色属性现在存储为 QBrush，以支持渐变
        self._trackBrush = QBrush(QColor("#E9EDF0"))
        self._rangeBrush = QBrush(QColor("#3B97E3"))
        self._hoverTrackBrush = QBrush(QColor("#D9DEE4"))
        self._hoverRangeBrush = QBrush(QColor("#5DA9E8"))
        self._handleBrush = QBrush(Qt.white)
        self._hoverHandleBrush = QBrush(QColor("#E9EDF0"))
        self._pressedHandleBrush = QBrush(QColor("#D9DEE4"))

        # 边框颜色仍然是 QColor
        self._handleBorderColor = QColor("#3B97E3")
        self._pressedHandleBorderColor = QColor("#2F78C0")
        
        # 动画属性 (保持不变)
        self._bar_height_anim_value = self._bar_height
        self._first_handle_w_anim = self._handle_width
        self._first_handle_h_anim = self._handle_height
        self._second_handle_w_anim = self._handle_width
        self._second_handle_h_anim = self._handle_height

        self.bar_animation = QPropertyAnimation(self, b"_bar_height_anim_value")
        self.fh_w_anim = QPropertyAnimation(self, b"_first_handle_w_anim")
        self.fh_h_anim = QPropertyAnimation(self, b"_first_handle_h_anim")
        self.sh_w_anim = QPropertyAnimation(self, b"_second_handle_w_anim")
        self.sh_h_anim = QPropertyAnimation(self, b"_second_handle_h_anim")
        
        ANIMATION_DURATION = 80
        self.bar_animation.setDuration(ANIMATION_DURATION)
        self.fh_w_anim.setDuration(ANIMATION_DURATION); self.fh_h_anim.setDuration(ANIMATION_DURATION)
        self.sh_w_anim.setDuration(ANIMATION_DURATION); self.sh_h_anim.setDuration(ANIMATION_DURATION)
        
        easing = QEasingCurve.OutCubic
        self.bar_animation.setEasingCurve(easing)
        self.fh_w_anim.setEasingCurve(easing); self.fh_h_anim.setEasingCurve(easing)
        self.sh_w_anim.setEasingCurve(easing); self.sh_h_anim.setEasingCurve(easing)

    # --- 动画属性 (保持不变) ---
    @pyqtProperty(int)
    def _bar_height_anim_value(self): return self.__bar_height_anim_value
    @_bar_height_anim_value.setter
    def _bar_height_anim_value(self, value): self.__bar_height_anim_value = value; self.update()
    @pyqtProperty(int)
    def _first_handle_w_anim(self): return self.__first_handle_w_anim
    @_first_handle_w_anim.setter
    def _first_handle_w_anim(self, val): self.__first_handle_w_anim = val; self.update()
    @pyqtProperty(int)
    def _first_handle_h_anim(self): return self.__first_handle_h_anim
    @_first_handle_h_anim.setter
    def _first_handle_h_anim(self, val): self.__first_handle_h_anim = val; self.update()
    @pyqtProperty(int)
    def _second_handle_w_anim(self): return self.__second_handle_w_anim
    @_second_handle_w_anim.setter
    def _second_handle_w_anim(self, val): self.__second_handle_w_anim = val; self.update()
    @pyqtProperty(int)
    def _second_handle_h_anim(self): return self.__second_handle_h_anim
    @_second_handle_h_anim.setter
    def _second_handle_h_anim(self, val): self.__second_handle_h_anim = val; self.update()

    # --- QSS 颜色属性 (核心修改：从 QColor 升级到 QBrush) ---
    @pyqtProperty(QBrush)
    def trackBrush(self): return self._trackBrush
    @trackBrush.setter
    def trackBrush(self, brush): self._trackBrush = brush; self.update()

    @pyqtProperty(QBrush)
    def rangeBrush(self): return self._rangeBrush
    @rangeBrush.setter
    def rangeBrush(self, brush): self._rangeBrush = brush; self.update()

    @pyqtProperty(QBrush)
    def hoverTrackBrush(self): return self._hoverTrackBrush
    @hoverTrackBrush.setter
    def hoverTrackBrush(self, brush): self._hoverTrackBrush = brush; self.update()

    @pyqtProperty(QBrush)
    def hoverRangeBrush(self): return self._hoverRangeBrush
    @hoverRangeBrush.setter
    def hoverRangeBrush(self, brush): self._hoverRangeBrush = brush; self.update()

    @pyqtProperty(QBrush)
    def handleBrush(self): return self._handleBrush
    @handleBrush.setter
    def handleBrush(self, brush): self._handleBrush = brush; self.update()
    
    @pyqtProperty(QBrush)
    def hoverHandleBrush(self): return self._hoverHandleBrush
    @hoverHandleBrush.setter
    def hoverHandleBrush(self, brush): self._hoverHandleBrush = brush; self.update()
    
    @pyqtProperty(QBrush)
    def pressedHandleBrush(self): return self._pressedHandleBrush
    @pressedHandleBrush.setter
    def pressedHandleBrush(self, brush): self._pressedHandleBrush = brush; self.update()
    
    # --- 边框颜色属性 (保持 QColor) ---
    @pyqtProperty(QColor)
    def handleBorderColor(self): return self._handleBorderColor
    @handleBorderColor.setter
    def handleBorderColor(self, color): self._handleBorderColor = color; self.update()
    
    @pyqtProperty(QColor)
    def pressedHandleBorderColor(self): return self._pressedHandleBorderColor
    @pressedHandleBorderColor.setter
    def pressedHandleBorderColor(self, color): self._pressedHandleBorderColor = color; self.update()
    
    # --- [核心修正 - 向后兼容] 保留旧的 QColor 属性，避免警告 ---
    @pyqtProperty(QColor)
    def trackColor(self): return self._trackBrush.color()
    @trackColor.setter
    def trackColor(self, color): self.trackBrush = QBrush(color)
    @pyqtProperty(QColor)
    def rangeColor(self): return self._rangeBrush.color()
    @rangeColor.setter
    def rangeColor(self, color): self.rangeBrush = QBrush(color)
    @pyqtProperty(QColor)
    def hoverTrackColor(self): return self._hoverTrackBrush.color()
    @hoverTrackColor.setter
    def hoverTrackColor(self, color): self.hoverTrackBrush = QBrush(color)
    @pyqtProperty(QColor)
    def hoverRangeColor(self): return self._hoverRangeBrush.color()
    @hoverRangeColor.setter
    def hoverRangeColor(self, color): self.hoverRangeBrush = QBrush(color)
    @pyqtProperty(QColor)
    def handleColor(self): return self._handleBrush.color()
    @handleColor.setter
    def handleColor(self, color): self.handleBrush = QBrush(color)
    @pyqtProperty(QColor)
    def hoverHandleColor(self): return self._hoverHandleBrush.color()
    @hoverHandleColor.setter
    def hoverHandleColor(self, color): self.hoverHandleBrush = QBrush(color)
    @pyqtProperty(QColor)
    def pressedHandleColor(self): return self._pressedHandleBrush.color()
    @pressedHandleColor.setter
    def pressedHandleColor(self, color): self.pressedHandleBrush = QBrush(color)

    # --- QSS 尺寸与形状属性 (保持不变) ---
    @pyqtProperty(int)
    def handleRadius(self): return self._handleRadius
    @handleRadius.setter
    def handleRadius(self, radius): self._handleRadius = radius; self.update()
    @pyqtProperty(int)
    def barHeight(self): return self._bar_height
    @barHeight.setter
    def barHeight(self, h): self._bar_height = h; self._bar_height_anim_value = h; self.update()
    @pyqtProperty(int)
    def hoverBarHeight(self): return self._hover_bar_height
    @hoverBarHeight.setter
    def hoverBarHeight(self, h): self._hover_bar_height = h; self.update()
    @pyqtProperty(int)
    def handleWidth(self): return self._handle_width
    @handleWidth.setter
    def handleWidth(self, w): self._handle_width = w; self._first_handle_w_anim = w; self._second_handle_w_anim = w; self.update()
    @pyqtProperty(int)
    def handleHeight(self): return self._handle_height
    @handleHeight.setter
    def handleHeight(self, h): self._handle_height = h; self._first_handle_h_anim = h; self._second_handle_h_anim = h; self.update()
    @pyqtProperty(int)
    def hoverHandleWidth(self): return self._hover_handle_width
    @hoverHandleWidth.setter
    def hoverHandleWidth(self, w): self._hover_handle_width = w; self.update()
    @pyqtProperty(int)
    def hoverHandleHeight(self): return self._hover_handle_height
    @hoverHandleHeight.setter
    def hoverHandleHeight(self, h): self._hover_handle_height = h; self.update()
    @pyqtProperty(int)
    def pressedHandleWidth(self): return self._pressed_handle_width
    @pressedHandleWidth.setter
    def pressedHandleWidth(self, w): self._pressed_handle_width = w; self.update()
    @pyqtProperty(int)
    def pressedHandleHeight(self): return self._pressed_handle_height
    @pressedHandleHeight.setter
    def pressedHandleHeight(self, h): self._pressed_handle_height = h; self.update()
    @pyqtProperty(int)
    def handleBorderWidth(self): return self._handle_border_width
    @handleBorderWidth.setter
    def handleBorderWidth(self, w): self._handle_border_width = w; self.update()
    @pyqtProperty(int)
    def handleSize(self): return self._handle_width
    @handleSize.setter
    def handleSize(self, size): self.handleWidth = size; self.handleHeight = size
    @pyqtProperty(int)
    def hoverHandleSize(self): return self._hover_handle_width
    @hoverHandleSize.setter
    def hoverHandleSize(self, size): self.hoverHandleWidth = size; self.hoverHandleHeight = size
    @pyqtProperty(int)
    def pressedHandleSize(self): return self._pressed_handle_width
    @pressedHandleSize.setter
    def pressedHandleSize(self, size): self.pressedHandleWidth = size; self.pressedHandleHeight = size
    
    # --- 公共API (保持不变) ---
    def setRange(self, min_val, max_val): self._min_val, self._max_val = min_val, max_val; self.update()
    def setLowerValue(self, val): self._lower_val = max(self._min_val, min(val, self._upper_val)); self.rangeChanged.emit(self.lowerValue(), self.upperValue()); self.update()
    def setUpperValue(self, val): self._upper_val = max(self._lower_val, min(val, self._max_val)); self.rangeChanged.emit(self.lowerValue(), self.upperValue()); self.update()
    def lowerValue(self): return int(self._lower_val)
    def upperValue(self): return int(self._upper_val)
    
    # --- 辅助函数 (保持不变) ---
    def _get_max_handle_dimension(self):
        hover_w = self._hover_handle_width if self._hover_handle_width > 0 else self._handle_width + 4
        pressed_w = self._pressed_handle_width if self._pressed_handle_width > 0 else self._handle_width - 2
        max_w = max(self._handle_width, hover_w, pressed_w)
        hover_h = self._hover_handle_height if self._hover_handle_height > 0 else self._handle_height + 4
        pressed_h = self._pressed_handle_height if self._pressed_handle_height > 0 else self._handle_height - 2
        max_h = max(self._handle_height, hover_h, pressed_h)
        return max_w, max_h

    # --- 核心绘制 (核心修改) ---
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        
        margin = (self._get_max_handle_dimension()[0] + self._handle_border_width) // 2
        
        current_bar_height = self._bar_height_anim_value
        track_b = self._hoverTrackBrush if self._track_hovered else self._trackBrush
        range_b = self._hoverRangeBrush if self._track_hovered else self._rangeBrush
        bar_y = (h - current_bar_height) // 2
        
        painter.setPen(Qt.NoPen); painter.setBrush(track_b); painter.drawRoundedRect(margin, bar_y, w - 2 * margin, current_bar_height, current_bar_height//2, current_bar_height//2)
        lower_x = self._value_to_pixel(self._lower_val); upper_x = self._value_to_pixel(self._upper_val)
        painter.setBrush(range_b); painter.drawRoundedRect(lower_x, bar_y, upper_x - lower_x, current_bar_height, current_bar_height//2, current_bar_height//2)
        
        w1, h1 = self._first_handle_w_anim, self._first_handle_h_anim
        b1, bc1 = self._get_handle_brushes(self._first_handle_pressed, self._first_handle_hovered)
        painter.setBrush(b1); painter.setPen(QPen(bc1, self._handle_border_width))
        self.first_handle_rect = QRect(lower_x - w1//2, (h-h1)//2, w1, h1)
        painter.drawRoundedRect(self.first_handle_rect, self._handleRadius, self._handleRadius)
        
        w2, h2 = self._second_handle_w_anim, self._second_handle_h_anim
        b2, bc2 = self._get_handle_brushes(self._second_handle_pressed, self._second_handle_hovered)
        painter.setBrush(b2); painter.setPen(QPen(bc2, self._handle_border_width))
        self.second_handle_rect = QRect(upper_x - w2//2, (h-h2)//2, w2, h2)
        painter.drawRoundedRect(self.second_handle_rect, self._handleRadius, self._handleRadius)

    # --- 事件与动画处理 (核心修改) ---
    def _start_animations(self):
        bar_target = self._hover_bar_height if self._hover_bar_height > 0 else self._bar_height + 2
        self.bar_animation.setEndValue(bar_target if self._track_hovered or self._first_handle_pressed or self._second_handle_pressed else self._bar_height)
        self.bar_animation.start()
        w_target1 = self._handle_width; h_target1 = self._handle_height
        if self._first_handle_pressed:
            w_target1 = self._pressed_handle_width if self._pressed_handle_width > 0 else self._handle_width - 2
            h_target1 = self._pressed_handle_height if self._pressed_handle_height > 0 else self._handle_height - 2
        elif self._first_handle_hovered:
            w_target1 = self._hover_handle_width if self._hover_handle_width > 0 else self._handle_width + 4
            h_target1 = self._hover_handle_height if self._hover_handle_height > 0 else self._handle_height + 4
        self.fh_w_anim.setEndValue(w_target1); self.fh_h_anim.setEndValue(h_target1)
        self.fh_w_anim.start(); self.fh_h_anim.start()
        w_target2 = self._handle_width; h_target2 = self._handle_height
        if self._second_handle_pressed:
            w_target2 = self._pressed_handle_width if self._pressed_handle_width > 0 else self._handle_width - 2
            h_target2 = self._pressed_handle_height if self._pressed_handle_height > 0 else self._handle_height - 2
        elif self._second_handle_hovered:
            w_target2 = self._hover_handle_width if self._hover_handle_width > 0 else self._handle_width + 4
            h_target2 = self._hover_handle_height if self._hover_handle_height > 0 else self._handle_height + 4
        self.sh_w_anim.setEndValue(w_target2); self.sh_h_anim.setEndValue(h_target2)
        self.sh_w_anim.start(); self.sh_h_anim.start()
    
    def _get_handle_brushes(self, pressed, hovered):
        # [核心修改] 此方法现在返回 (QBrush, QColor)
        if pressed: return self._pressedHandleBrush, self._pressedHandleBorderColor
        elif hovered: return self._hoverHandleBrush, self._handleBorderColor
        else: return self._handleBrush, self._handleBorderColor

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.second_handle_rect.contains(event.pos()): self._second_handle_pressed = True
            elif self.first_handle_rect.contains(event.pos()): self._first_handle_pressed = True
            self._start_animations(); self.update()
    def mouseMoveEvent(self, event):
        if self._first_handle_pressed: self.setLowerValue(int(self._pixel_to_value(event.pos().x())))
        elif self._second_handle_pressed: self.setUpperValue(int(self._pixel_to_value(event.pos().x())))
        old_h1, old_h2, old_track = self._first_handle_hovered, self._second_handle_hovered, self._track_hovered
        self._first_handle_hovered = self.first_handle_rect.contains(event.pos()) and not self._second_handle_pressed
        self._second_handle_hovered = self.second_handle_rect.contains(event.pos()) and not self._first_handle_pressed
        bar_y = (self.height() - self._bar_height_anim_value) // 2
        bar_rect = QRect(0, bar_y, self.width(), self._bar_height_anim_value)
        self._track_hovered = bar_rect.contains(event.pos()) and not self._first_handle_hovered and not self._second_handle_hovered
        if old_h1 != self._first_handle_hovered or old_h2 != self._second_handle_hovered or old_track != self._track_hovered:
            self._start_animations(); self.update()
    def mouseReleaseEvent(self, event):
        self._first_handle_pressed = False; self._second_handle_pressed = False
        self._start_animations(); self.update()
    def leaveEvent(self, event):
        self._first_handle_hovered = False; self._second_handle_hovered = False; self._track_hovered = False
        self._start_animations(); self.update()

    # --- 坐标转换 (保持不变) ---
    def _value_to_pixel(self, value):
        margin = (self._get_max_handle_dimension()[0] + self._handle_border_width) // 2
        pixel_span = self.width() - 2 * margin
        span = self._max_val - self._min_val
        if span == 0: return margin
        return int(margin + pixel_span * (value - self._min_val) / span)
    def _pixel_to_value(self, pixel):
        margin = (self._get_max_handle_dimension()[0] + self._handle_border_width) // 2
        pixel_span = self.width() - 2 * margin
        clamped_pixel = max(margin, min(pixel, self.width() - margin))
        pixel_ratio = (clamped_pixel - margin) / pixel_span if pixel_span > 0 else 0
        span = self._max_val - self._min_val
        val = self._min_val + span * pixel_ratio
        return max(self._min_val, min(self._max_val, val))

# ==============================================================================
# 3. 自定义动画色块 (AnimatedColorSwatch) - [v1.1 轮廓动画版]
# ==============================================================================
class AnimatedColorSwatch(QFrame):
    """一个支持轮廓和缩放动画的独立色块，用于调色板。"""
    clicked = pyqtSignal(QColor)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)

        self._color = QColor(color)
        
        # --- [核心修改] 动画目标现在是轮廓颜色 alpha 和缩放比例 ---
        self._outline_alpha = 0.0 # 0.0 (无轮廓) to 255.0 (完全不透明)
        self._scale = 1.0

        self.outline_animation = QPropertyAnimation(self, b"_outline_alpha")
        self.outline_animation.setDuration(100)
        self.outline_animation.setEasingCurve(QEasingCurve.InOutCubic)
        
        self.scale_animation = QPropertyAnimation(self, b"_scale")
        self.scale_animation.setDuration(70)
        self.scale_animation.setEasingCurve(QEasingCurve.OutCubic)

    # --- [核心修改] 新的动画属性 ---
    @pyqtProperty(float)
    def _outline_alpha(self):
        return self.__outline_alpha
    @_outline_alpha.setter
    def _outline_alpha(self, value):
        self.__outline_alpha = value
        self.update()
        
    @pyqtProperty(float)
    def _scale(self): return self.__scale
    @_scale.setter
    def _scale(self, value): self.__scale = value; self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # --- [核心修改] 绘制逻辑现在包含轮廓 ---
        center = self.rect().center()
        width = self.width() * self._scale
        height = self.height() * self._scale
        scaled_rect = QRect(0, 0, int(width), int(height))
        scaled_rect.moveCenter(center)
        
        # 1. 绘制背景色块
        painter.setPen(QPen(QColor("#e0e0e0")))
        painter.setBrush(self._color)
        painter.drawRoundedRect(scaled_rect, 4, 4)

        # 2. 如果轮廓 alpha > 0，则在其上叠加绘制轮廓
        if self._outline_alpha > 0:
            outline_color = QColor(0, 120, 215) # 蓝色高亮
            outline_color.setAlpha(int(self._outline_alpha))
            pen = QPen(outline_color, 2) # 2px 宽的轮廓
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush) # 轮廓是空心的
            # 在缩放后的矩形内侧绘制，使其看起来更 sharp
            painter.drawRoundedRect(scaled_rect.adjusted(1, 1, -1, -1), 3, 3)

    def enterEvent(self, event):
        # --- [核心修改] 启动轮廓渐入动画 ---
        self.outline_animation.setDirection(QPropertyAnimation.Forward)
        self.outline_animation.setStartValue(self._outline_alpha)
        self.outline_animation.setEndValue(255.0)
        self.outline_animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # --- [核心修改] 启动轮廓渐出动画 ---
        self.outline_animation.setDirection(QPropertyAnimation.Backward)
        self.outline_animation.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # --- [核心修改] 按下时只执行缩小动画 ---
            self.scale_animation.stop()
            self.scale_animation.setEndValue(0.8)
            self.scale_animation.start()
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            # --- [核心修改] 松开时恢复尺寸并发送信号 ---
            self.scale_animation.stop()
            self.scale_animation.setEndValue(1.0) # 直接恢复到100%，不再弹回悬停放大
            self.scale_animation.start()
            self.clicked.emit(self._color)
        super().mouseReleaseEvent(event)


# ==============================================================================
# 4. 自定义颜色选择弹出框 (CustomColorPopup) - [v2.4 动画时序修复版]
# ==============================================================================
class CustomColorPopup(QDialog):
    """
    一个支持滑动和淡入淡出动画的弹出式调色板。
    v2.4: 修复了动画启动时因时序问题导致的 "no start value" 警告。
    """
    colorSelected = pyqtSignal(QColor)

    def __init__(self, initial_color=None, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("CustomColorPopupAnimated")
        
        self.setStyleSheet("""
            #CustomColorPopupAnimated QLineEdit { border: 1px solid #DDDDDD; border-radius: 4px; padding: 4px; background-color: white; color: black; }
            #CustomColorPopupAnimated QLabel { background-color: transparent; color: black; }
            #CustomColorPopupAnimated QLabel#ColorPreview { border: 1px solid #AAAAAA; border-radius: 4px; }
        """)
        
        self.colors = ['#d32f2f','#f57c00','#4caf50','#1976d2','#9c27b0','#e91e63','#b71c1c','#e65100','#1b5e20','#0d47a1','#4a148c','#880e4f','#fbc02d','#8bc34a','#00bcd4','#03a9f4','#ff4081','#ff9800','#ffcdd2','#ffccbc','#c8e6c9','#bbdefb','#e1bee7','#fff9c4','#a1887f','#795548','#8d6e63','#00897b','#455a64','#546e7a','#ffffff','#eeeeee','#bdbdbd','#757575','#424242','#000000','#cddc39','#673ab7','#29b6f6','#ff7043','#ec407a','#7e57c2']
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        grid_layout = QGridLayout(); grid_layout.setSpacing(5)
        cols = 6
        for i, color_hex in enumerate(self.colors):
            row, col = divmod(i, cols)
            color_widget = AnimatedColorSwatch(QColor(color_hex))
            color_widget.clicked.connect(self.on_color_click)
            grid_layout.addWidget(color_widget, row, col)
        main_layout.addLayout(grid_layout)
        
        input_layout = QHBoxLayout()
        self.color_preview = QLabel(); self.color_preview.setObjectName("ColorPreview"); self.color_preview.setFixedSize(24, 24)
        self.hex_input = QLineEdit(); self.hex_input.setPlaceholderText("#RRGGBB"); self.hex_input.setMaxLength(7); self.hex_input.setFixedWidth(100); self.hex_input.textChanged.connect(self._update_preview_from_text); self.hex_input.returnPressed.connect(self._accept_from_text)
        
        input_layout.addWidget(QLabel("色号:")); input_layout.addWidget(self.hex_input); input_layout.addStretch(1); input_layout.addWidget(self.color_preview)
        main_layout.addLayout(input_layout)

        if initial_color:
            self.hex_input.setText(initial_color.name())

        from PyQt5.QtCore import QParallelAnimationGroup
        self.animation_group = QParallelAnimationGroup(self)
        self.pos_animation = QPropertyAnimation(self, b"pos")
        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        
        self.pos_animation.setDuration(130)
        self.opacity_animation.setDuration(130)

        self.animation_group.addAnimation(self.pos_animation)
        self.animation_group.addAnimation(self.opacity_animation)
        self.animation_group.finished.connect(self._on_animation_finished)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        background_color = QColor(255, 255, 255)
        border_color = QColor(204, 204, 204)
        painter.setPen(QPen(border_color))
        painter.setBrush(background_color)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)

    def show_animated(self, target_pos):
        # --- [核心修正] 调整代码执行顺序 ---
        # 1. 先设置好所有动画的起始值和结束值
        self.animation_group.setDirection(QPropertyAnimation.Forward)
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        start_pos = QPoint(target_pos.x(), target_pos.y() - 15)
        self.pos_animation.setStartValue(start_pos)
        self.pos_animation.setEndValue(target_pos)

        # 2. 然后再显示窗口
        self.show()
        
        # 3. 最后启动动画
        self.animation_group.start()
        QApplication.instance().installEventFilter(self)
    
    # ... (其他方法保持不变) ...
    def close_animated(self):
        QApplication.instance().removeEventFilter(self)
        self.animation_group.setDirection(QPropertyAnimation.Backward)
        self.animation_group.start()

    def _on_animation_finished(self):
        if self.animation_group.direction() == QPropertyAnimation.Backward:
            self.close()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and self.isVisible():
            if not self.rect().contains(self.mapFromGlobal(event.globalPos())):
                self.close_animated()
                return True
        return super().eventFilter(obj, event)

    def on_color_click(self, color):
        self.colorSelected.emit(color)
        self.close_animated()

    def _update_preview_from_text(self, text):
        color = QColor(text)
        self.color_preview.setStyleSheet(f"background-color: {color.name() if color.isValid() else 'transparent'};")

    def _accept_from_text(self):
        color = QColor(self.hex_input.text())
        if color.isValid():
            self.on_color_click(color)
        else:
            self.close_animated()

# ==============================================================================
# 5. 自定义颜色选择按钮 (ColorButton) - [v2.1 动画与BUG修复版]
# ==============================================================================
class ColorButton(QLabel):
    """一个支持颜色过渡动画的、可点击的颜色按钮。"""
    colorChanged = pyqtSignal()

    def __init__(self, color=Qt.black, parent=None):
        super().__init__(parent)
        self.setObjectName("AnimatedColorButton")
        self.setFixedSize(50, 20)
        self.setCursor(Qt.PointingHandCursor)

        self._base_color = QColor(color)
        self.__display_color = QColor(color) # 私有变量，由动画控制器修改

        self.color_animation = QPropertyAnimation(self, b"_display_color")
        self.color_animation.setDuration(100) # 颜色动画可以稍快一些
        self.color_animation.setEasingCurve(QEasingCurve.InOutCubic)

        self._popup_instance = None # [核心修正] 用于管理唯一的弹窗实例

        self._update_stylesheet(self._base_color)

    @pyqtProperty(QColor)
    def _display_color(self):
        return self.__display_color
    
    @_display_color.setter
    def _display_color(self, color):
        self.__display_color = color
        self._update_stylesheet(color)

    def _update_stylesheet(self, color):
        self.setStyleSheet(
            f"QLabel#AnimatedColorButton {{"
            f"  background-color: {color.name()};"
            f"  border-radius: 10px;"
            f"  border: 1px solid #AAAAAA;"
            f"}}"
        )
    
    def set_color(self, color):
        self._base_color = QColor(color)
        self.color_animation.stop()
        self._display_color = self._base_color
        self.setToolTip(f"点击选择颜色 (当前: {self._base_color.name()})")
        self.colorChanged.emit()

    def color(self):
        return self._base_color

    def enterEvent(self, event):
        self.color_animation.stop()
        self.color_animation.setEndValue(self._base_color.lighter(130))
        self.color_animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.color_animation.stop()
        self.color_animation.setEndValue(self._base_color)
        self.color_animation.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.color_animation.stop()
            self.color_animation.setEndValue(self._base_color.darker(130))
            self.color_animation.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.color_animation.stop()
            self.color_animation.setEndValue(self._base_color.lighter(130))
            self.color_animation.start()
            
            # [核心修正 3] 管理唯一的弹窗实例，避免重复创建
            if self._popup_instance is None or not self._popup_instance.isVisible():
                self._popup_instance = CustomColorPopup(initial_color=self._base_color, parent=self)
                self._popup_instance.colorSelected.connect(self.set_color)
                target_pos = self.mapToGlobal(self.rect().bottomLeft())
                self._popup_instance.show_animated(target_pos)
        super().mouseReleaseEvent(event)