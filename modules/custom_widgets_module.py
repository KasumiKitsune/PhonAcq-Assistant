# --- START OF FILE modules/custom_widgets_module.py ---
# --- 模块元数据 ---
MODULE_NAME = "自定义UI组件"
MODULE_DESCRIPTION = "提供如开关、滑块、按钮等自定义的UI控件，供其他模块复用。"
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QGridLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QStyle, 
                             QStyledItemDelegate, QVBoxLayout, QWidget, QListWidgetItem, QSlider, QGraphicsOpacityEffect, QPushButton, QFileDialog)
from PyQt5.QtCore import (pyqtProperty, pyqtSignal, QEvent, QEasingCurve, 
                          QParallelAnimationGroup, QPoint, QPropertyAnimation, 
                          QRect, QRectF, QSequentialAnimationGroup, QSize, Qt, QObject, QTimer)
from PyQt5.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen, QPixmap
import json

# ==============================================================================
# 1. 自定义 ToggleSwitch 控件
# ==============================================================================
class ToggleSwitch(QCheckBox):
    """
    [v2.0 - 动画可禁用版]
    一个可自定义样式的切换开关控件，支持并行的、平滑的过渡动画，
    精细的QSS悬停控制，以及标准的“释放时切换”和“拖动切换”交互。
    此版本会检查其顶层窗口的 'animations_enabled' 属性来决定是否播放动画。
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
        self._knob_icon_on = QIcon()
        self._knob_icon_off = QIcon()        
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

        # 初始同步视觉状态到逻辑状态
        self._knob_position_ratio = 1.0 if self.isChecked() else 0.0
        self._knob_margin_anim_value = self._knobMargin

    def _are_animations_enabled(self):
        """
        安全地向上遍历父级，查找顶层窗口，并检查其 'animations_enabled' 属性。
        如果找不到该属性，则安全地回退到 True（默认启用动画）。
        """
        widget = self
        while widget:
            # isWindow() 检查是否为顶层窗口 (如 QMainWindow, QDialog)
            if widget.isWindow():
                return getattr(widget, 'animations_enabled', True)
            widget = widget.parent()
        # 如果控件没有父级或找不到窗口，也默认启用动画
        return True

    def sync_visual_state_to_checked_state(self):
        """
        强制更新开关的视觉状态（旋钮位置），使其与当前的 isChecked() 状态同步。
        即使 isChecked() 状态没有变化，也会执行动画或直接设置到最终位置。
        这用于解决加载时视觉与逻辑脱节的问题。
        """
        # 立即将动画的起始值设置为当前视觉位置
        self.pos_animation.setStartValue(self._knob_position_ratio)
        
        # 目标值是根据当前 isChecked() 状态确定的最终位置
        target_end_value = 1.0 if self.isChecked() else 0.0
        self.pos_animation.setEndValue(target_end_value)
        
        # 直接跳到动画结束，或者短动画播放
        # 为了加载时立即显示正确状态，我们直接设置结束值并更新
        self._knob_position_ratio = target_end_value
        self.update() # 强制重绘
        
        # 如果需要动画，可以改为 self.pos_animation.start()
        # 但对于加载时的同步，通常直接跳到最终状态更合适

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
        """
        [已修改] 启动或跳过旋钮位置的动画。
        """
        end_value = 1.0 if checked else 0.0
        
        if not self._are_animations_enabled():
            # 如果动画被禁用，直接跳到最终状态
            self._knob_position_ratio = end_value
            self.update()
            return

        # 否则，正常启动动画
        self.pos_animation.setStartValue(self._knob_position_ratio)
        self.pos_animation.setEndValue(end_value)
        self.pos_animation.start()

    def _start_margin_animation(self, hover):
        """
        [已修改] 启动或跳过旋钮边距的动画（用于悬停效果）。
        """
        start_value = self._knob_margin_anim_value
        if hover:
            default_offset = -1
            offset = self._hover_knobMarginOffset if self._hover_knobMarginOffset != 0 else default_offset
            end_value = self._knobMargin + offset
        else:
            end_value = self._knobMargin

        if not self._are_animations_enabled():
            # 如果动画被禁用，直接跳到最终状态
            self._knob_margin_anim_value = end_value
            self.update()
            return
        
        # 否则，正常启动动画
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
    # --- 颜色属性 ---
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
    # --- 尺寸与形状属性 ---
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
    @pyqtProperty(int)
    def hoverKnobMarginOffset(self): return self._hover_knobMarginOffset
    @hoverKnobMarginOffset.setter
    def hoverKnobMarginOffset(self, offset): self._hover_knobMarginOffset = offset; self.update()
    # --- 图标属性 ---
    @pyqtProperty(str)
    def knobIconOn(self):
        # Getter 通常不返回对象本身，而是返回一个可识别的字符串（如文件路径或名称）
        return self._knob_icon_on.name()

    @knobIconOn.setter
    def knobIconOn(self, path):
        # Setter 接收一个路径字符串，并创建一个 QIcon 对象
        self._knob_icon_on = QIcon(path)
        self.update()

    @pyqtProperty(str)
    def knobIconOff(self):
        return self._knob_icon_off.name()

    @knobIconOff.setter
    def knobIconOff(self, path):
        self._knob_icon_off = QIcon(path)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        # 根据是否悬停以及QSS是否定义了悬停颜色，选择绘制颜色
        border_color = self._hover_borderColor if self._is_hovering and self._hover_borderColor.isValid() else self._borderColor
        track_on_color = self._hover_trackColorOn if self._is_hovering and self._hover_trackColorOn.isValid() else self._trackColorOn
        track_off_color = self._hover_trackColorOff if self._is_hovering and self._hover_trackColorOff.isValid() else self._trackColorOff
        knob_color = self._hover_knobColor if self._is_hovering and self._hover_knobColor.isValid() else self._knobColor
        
        # 1. 绘制边框（如果存在）
        if self._borderWidth > 0 and border_color.isValid() and border_color.alpha() > 0:
            pen = QPen(border_color, self._borderWidth); pen.setJoinStyle(Qt.RoundJoin); p.setPen(pen)
            border_rect = rect.adjusted(self._borderWidth//2, self._borderWidth//2, -self._borderWidth//2, -self._borderWidth//2)
            p.setBrush(Qt.NoBrush); p.drawRoundedRect(border_rect, self._trackBorderRadius, self._trackBorderRadius)
        
        # 2. 绘制轨道 (渐变色)
        # 根据旋钮位置比例计算轨道的混合颜色
        track_color = QColor(track_off_color)
        track_color.setRed(int(track_off_color.red() + (track_on_color.red() - track_off_color.red()) * self._knob_position_ratio))
        track_color.setGreen(int(track_off_color.green() + (track_on_color.green() - track_off_color.green()) * self._knob_position_ratio))
        track_color.setBlue(int(track_off_color.blue() + (track_on_color.blue() - track_off_color.blue()) * self._knob_position_ratio))
        
        p.setPen(Qt.NoPen); p.setBrush(QBrush(track_color))
        track_rect = rect.adjusted(self._borderWidth, self._borderWidth, -self._borderWidth, -self._borderWidth)
        track_inner_radius = max(0, self._trackBorderRadius - self._borderWidth)
        p.drawRoundedRect(track_rect, track_inner_radius, track_inner_radius)
        
        # 3. 绘制旋钮
        margin = self._knob_margin_anim_value
        knob_height = track_rect.height() - (2 * margin)
        knob_width = knob_height # 确保旋钮是正方形或圆形
        
        # 根据动画位置计算旋钮的x坐标
        start_x = track_rect.left() + margin
        end_x = track_rect.right() - knob_width - margin + 1 # +1 是为了解决像素舍入问题
        current_x = start_x + (end_x - start_x) * self._knob_position_ratio
        
        knob_rect = QRect(int(current_x), track_rect.top() + margin, knob_width, knob_height)
        
        p.setBrush(QBrush(knob_color))
        if self.knobShape == 'rectangle': 
            p.drawRoundedRect(knob_rect, self._knobBorderRadius, self._knobBorderRadius)
        else: 
            p.drawEllipse(knob_rect)
        
        # 4. 绘制图标 (如果存在)
        # 绘制“关”状态图标
        if not self._knob_icon_off.isNull():
            p.setOpacity(1.0 - self._knob_position_ratio) # 根据位置比例设置透明度
            # 计算图标绘制区域（通常比滑块小一点）
            icon_margin = 3
            icon_rect = knob_rect.adjusted(icon_margin, icon_margin, -icon_margin, -icon_margin)
            self._knob_icon_off.paint(p, icon_rect)

        # 绘制“开”状态图标
        if not self._knob_icon_on.isNull():
            p.setOpacity(self._knob_position_ratio) # 透明度与位置比例同步
            icon_margin = 3
            icon_rect = knob_rect.adjusted(icon_margin, icon_margin, -icon_margin, -icon_margin)
            self._knob_icon_on.paint(p, icon_rect)
    
    def resizeEvent(self, event):
        """
        当控件大小变化时，重新计算旋钮的初始位置，
        以确保在尺寸变化后开关的视觉状态依然正确。
        """
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
    def minimum(self):
        """返回滑块的最小值。"""
        return self._min_val

    def maximum(self):
        """返回滑块的最大值。"""
        return self._max_val
    
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
        """
        [已修复] 显示并播放“出现”动画。
        此版本在显示窗口前设置好所有动画参数。
        """
        # 1. 设置动画方向和值
        self.animation_group.setDirection(QPropertyAnimation.Forward)
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        
        start_pos = QPoint(target_pos.x(), target_pos.y() - 15)
        self.pos_animation.setStartValue(start_pos)
        self.pos_animation.setEndValue(target_pos)

        # 2. 显示窗口（此时它在 start_pos 位置且完全透明）
        self.show()
        
        # 3. 启动动画
        self.animation_group.start()
        QApplication.instance().installEventFilter(self)

    def close_animated(self):
        """
        [已修复] 播放“消失”动画并关闭。
        此版本不再依赖 .setDirection(Backward)，而是显式设置动画值。
        """
        QApplication.instance().removeEventFilter(self)
        
        # --- [核心修复] ---
        # 1. 显式设置“消失”动画的起始值和结束值
        #    起始值就是控件当前的几何属性
        self.opacity_animation.setStartValue(self.windowOpacity())
        self.opacity_animation.setEndValue(0.0)
        
        self.pos_animation.setStartValue(self.pos())
        self.pos_animation.setEndValue(QPoint(self.pos().x(), self.pos().y() - 15))

        # 2. 确保方向是 Forward，因为我们是手动设置的
        self.animation_group.setDirection(QPropertyAnimation.Forward)
        
        # 3. 启动动画
        self.animation_group.start()

    def _on_animation_finished(self):
        """当动画（无论是出现还是消失）完成时调用。"""
        # [核心修复]
        # 现在，我们通过检查透明度来判断动画是否是“消失”动画
        if self.windowOpacity() < 0.01: # 接近0时
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
# ==============================================================================
# 6. 自定义动画列表控件 (AnimatedListWidget) - v2.1 [兼容与层级导航版]
# ==============================================================================

# ==============================================================================
#   内部辅助类：_ItemAnimationHolder
# ==============================================================================
class _ItemAnimationHolder(QObject):
    """
    一个继承自 QObject 的内部动画代理类。
    它作为 QPropertyAnimation 的目标，将动画值存储在 QListWidgetItem 的
    自定义数据角色中，并负责在值改变时请求UI重绘。
    v1.1: 增加了主动失效机制，以防止在访问已删除的 QListWidgetItem 时发生崩溃。
    """
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self._is_valid = True # 有效性标志

        # 初始化动画属性
        self._opacity = 0.0
        self._y_offset = 0
        self._bg_brush = QBrush(Qt.transparent)
        
        # 将初始值同步到 QListWidgetItem
        self.sync_to_item()

    def invalidate(self):
        """一个公开的方法，用于在 item 即将被删除前调用，以断开引用。"""
        self._is_valid = False
        self.item = None

    def sync_to_item(self):
        """将当前 holder 中的动画属性值写入到 QListWidgetItem 的数据角色中。"""
        if not self._is_valid: return
        self.item.setData(AnimatedListWidget.ANIM_OPACITY_ROLE, self._opacity)
        self.item.setData(AnimatedListWidget.ANIM_Y_OFFSET_ROLE, self._y_offset)
        self.item.setData(AnimatedListWidget.ANIM_BG_BRUSH_ROLE, self._bg_brush)

    # --- 动画目标属性 (增加安全检查) ---
    @pyqtProperty(float)
    def opacity(self): 
        return self._opacity
    @opacity.setter
    def opacity(self, value): 
        if not self._is_valid: return
        self._opacity = value
        self.item.setData(AnimatedListWidget.ANIM_OPACITY_ROLE, value)

    @pyqtProperty(int)
    def y_offset(self): 
        return self._y_offset
    @y_offset.setter
    def y_offset(self, value): 
        if not self._is_valid: return
        self._y_offset = value
        self.item.setData(AnimatedListWidget.ANIM_Y_OFFSET_ROLE, value)

    @pyqtProperty(QColor)
    def bg_color(self): 
        return self._bg_brush.color()
    @bg_color.setter
    def bg_color(self, color): 
        if not self._is_valid: return
        self._bg_brush = QBrush(color)
        self.item.setData(AnimatedListWidget.ANIM_BG_BRUSH_ROLE, self._bg_brush)
        
    def update_view(self):
        """一个槽函数，当任何动画属性改变时被调用，用于请求UI重绘。"""
        if not self._is_valid or self.item is None: return
        
        list_widget = self.item.listWidget()
        if list_widget:
            index = list_widget.indexFromItem(self.item)
            if index.isValid():
                list_widget.update(index)

# ==============================================================================
#   内部辅助类：AnimatedItemDelegate
# ==============================================================================
class AnimatedItemDelegate(QStyledItemDelegate):
    """
    [v2.1 - 层级感知版]
    一个自定义的项目委托，负责所有列表项的绘制 (paint) 和尺寸计算 (sizeHint)。
    现在能够绘制图标，并为层级列表提供支持。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.list_widget = parent

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # 1. 从数据角色中获取当前动画状态值和层级数据
        opacity = index.data(AnimatedListWidget.ANIM_OPACITY_ROLE) or 0.0
        y_offset = index.data(AnimatedListWidget.ANIM_Y_OFFSET_ROLE) or 0
        bg_brush = index.data(AnimatedListWidget.ANIM_BG_BRUSH_ROLE) or self.list_widget.itemBrush
        item_data = index.data(AnimatedListWidget.HIERARCHY_DATA_ROLE) or {}

        # 2. 应用动画变换
        painter.setOpacity(opacity)
        painter.translate(0, y_offset)
        
        # 3. 绘制背景
        rect = option.rect
        padding = self.list_widget.itemPadding
        bg_rect = rect.adjusted(padding, padding, -padding, -padding)
        
        final_brush = self.list_widget.itemSelectedBrush if option.state & QStyle.State_Selected else bg_brush
        painter.setPen(Qt.NoPen)
        painter.setBrush(final_brush)
        painter.drawRoundedRect(bg_rect, self.list_widget.itemRadius, self.list_widget.itemRadius)
        
        # 4. 准备绘制内容区域
        content_rect = bg_rect.adjusted(self.list_widget.itemTextPadding, 0, -self.list_widget.itemTextPadding, 0)
        
        # 5. 绘制图标（如果存在）
        icon = item_data.get('icon')
        if icon and isinstance(icon, QIcon) and not icon.isNull():
            icon_size = self.list_widget.fontMetrics().height() # 图标大小与文字高度一致
            icon_rect = QRect(content_rect.left(), 0, icon_size, icon_size)
            # 垂直居中
            icon_rect.moveCenter(QPoint(content_rect.left() + icon_size // 2, content_rect.center().y()))
            
            icon.paint(painter, icon_rect)
            
            # 将文本绘制区域向右移动，留出图标空间和间距
            content_rect.setLeft(content_rect.left() + icon_size + self.list_widget.itemTextPadding // 2)

        # 6. 绘制文本
        text_color = self.list_widget.itemSelectedTextColor if option.state & QStyle.State_Selected else self.list_widget.itemTextColor
        painter.setPen(text_color)
        
        text = index.data(Qt.DisplayRole)
        font = self.list_widget.font()
        fm = QFontMetrics(font)
        
        # 如果文本宽度超过可用空间，生成带省略号的文本
        elided_text = fm.elidedText(text, Qt.ElideRight, content_rect.width())
        
        # 绘制单行、左对齐、垂直居中的文本
        flags = Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine
        painter.drawText(content_rect, flags, elided_text)

        painter.restore()

    def sizeHint(self, option, index):
        padding_v = self.list_widget.itemPadding * 2
        text_padding_v = self.list_widget.itemTextPadding * 2
        font = self.list_widget.font()
        fm = QFontMetrics(font)
        
        height = fm.height() + padding_v + text_padding_v
        min_h = self.list_widget.minimumItemHeight
        
        return QSize(20, max(height, min_h))

# ==============================================================================
#   主控件类：AnimatedListWidget
# ==============================================================================
class AnimatedListWidget(QListWidget):
    """
    [v2.2 - 双击导航版]
    一个支持层级目录、向后兼容旧API、图标显示、进入动画和完全QSS主题化的列表控件。
    导航现在由双击或回车键触发，“返回”按钮则响应单击。
    """
    # 定义自定义数据角色
    ANIM_OPACITY_ROLE = Qt.UserRole + 1
    ANIM_Y_OFFSET_ROLE = Qt.UserRole + 2
    ANIM_BG_BRUSH_ROLE = Qt.UserRole + 3
    ANIM_HOLDER_ROLE = Qt.UserRole + 4
    HIERARCHY_DATA_ROLE = Qt.UserRole + 5

    # 定义新的信号，用于最终项目（非文件夹、非返回按钮）的激活
    item_activated = pyqtSignal(QListWidgetItem)
    system_picker_activated = pyqtSignal()
    item_activated = pyqtSignal(QListWidgetItem)

    def __init__(self, parent=None, icon_manager=None):
        super().__init__(parent)
        self.icon_manager = icon_manager
        
        # --- 核心设置 ---
        self.setItemDelegate(AnimatedItemDelegate(self))
        self.setMouseTracking(True)
        self.setUniformItemSizes(False)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrap(False)

        # --- 导航与动画系统 ---
        self._navigation_stack = []
        self._animation_queue = []
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(25) # 较快的交错延迟
        self._animation_timer.timeout.connect(self._process_animation_queue)
        self._animations_enabled = True

        # --- 内部状态变量 ---
        self._hovered_item_id = None
        self._pressed_item_id = None
        self._current_animations = {}

        # --- QSS可配置属性 ---
        self._itemBrush = QBrush(Qt.transparent)
        self._itemHoverBrush = QBrush(QColor("#F0F2F4"))
        self._itemPressedBrush = QBrush(QColor("#E0E2E4"))
        self._itemSelectedBrush = QBrush(QColor("#3B97E3"))
        self._itemTextColor = QColor("#2c3e50")
        self._itemSelectedTextColor = QColor("#FFFFFF")
        self._itemRadius = 4
        self._itemPadding = 4
        self._itemTextPadding = 8
        self._minimumItemHeight = 36
        
        # --- 核心信号连接 ---
        self.itemSelectionChanged.connect(self._on_selection_changed)
        # 单击现在只处理“返回”按钮的特殊情况
        self.itemClicked.connect(self._on_item_single_clicked)
        # 双击用于激活项目和进入文件夹
        self.itemDoubleClicked.connect(self._handle_item_activation)

    # --- QSS 可定义属性 (getter/setter) ---
    @pyqtProperty(int)
    def itemPadding(self): return self._itemPadding
    @itemPadding.setter
    def itemPadding(self, padding): self._itemPadding = padding; self.update()
    @pyqtProperty(int)
    def itemTextPadding(self): return self._itemTextPadding
    @itemTextPadding.setter
    def itemTextPadding(self, padding): self._itemTextPadding = padding; self.update()
    @pyqtProperty(QBrush)
    def itemBrush(self): return self._itemBrush
    @itemBrush.setter
    def itemBrush(self, brush): self._itemBrush = brush; self.update()
    @pyqtProperty(QBrush)
    def itemHoverBrush(self): return self._itemHoverBrush
    @itemHoverBrush.setter
    def itemHoverBrush(self, brush): self._itemHoverBrush = brush; self.update()
    @pyqtProperty(QBrush)
    def itemPressedBrush(self): return self._itemPressedBrush
    @itemPressedBrush.setter
    def itemPressedBrush(self, brush): self._itemPressedBrush = brush; self.update()
    @pyqtProperty(QBrush)
    def itemSelectedBrush(self): return self._itemSelectedBrush
    @itemSelectedBrush.setter
    def itemSelectedBrush(self, brush): self._itemSelectedBrush = brush; self.update()
    @pyqtProperty(QColor)
    def itemTextColor(self): return self._itemTextColor
    @itemTextColor.setter
    def itemTextColor(self, color): self._itemTextColor = color; self.update()
    @pyqtProperty(QColor)
    def itemSelectedTextColor(self): return self._itemSelectedTextColor
    @itemSelectedTextColor.setter
    def itemSelectedTextColor(self, color): self._itemSelectedTextColor = color; self.update()
    @pyqtProperty(int)
    def itemRadius(self): return self._itemRadius
    @itemRadius.setter
    def itemRadius(self, radius): self._itemRadius = radius; self.update()
    @pyqtProperty(int)
    def minimumItemHeight(self): return self._minimumItemHeight
    @minimumItemHeight.setter
    def minimumItemHeight(self, height): self._minimumItemHeight = height; self.update()
    
    # --- 公共 API ---
    def addItemsWithAnimation(self, items_data):
        """
        [v2.1 智能版] 用动画添加一批项目。
        此方法兼容两种数据格式：list[str] (旧版) 和 list[dict] (新版)。
        """
        if not items_data or not isinstance(items_data, list):
            hierarchical_data = []
        elif all(isinstance(x, str) for x in items_data):
            hierarchical_data = [{'type': 'item', 'text': text} for text in items_data]
        else:
            hierarchical_data = items_data
        
        self.setHierarchicalData(hierarchical_data)

    def setHierarchicalData(self, data):
        """
        设置层级数据并显示顶层列表。这是新的核心入口。
        """
        if not isinstance(data, list):
            print("AnimatedListWidget Error: Data must be a list of dictionaries.")
            return
        self._navigation_stack = [data]
        self._populate_list_with_animation(data)

    def clear(self):
        """覆盖原生 clear 方法，以安全地停止动画和清理资源。"""
        self._animation_timer.stop()
        self._animation_queue.clear()
        
        for anim in list(self._current_animations.values()):
            try:
                if anim: anim.stop()
            except RuntimeError: pass
        self._current_animations.clear()
            
        for i in range(self.count()):
            item = self.item(i)
            if item:
                holder = item.data(self.ANIM_HOLDER_ROLE)
                if holder: holder.invalidate()
            
        self._hovered_item_id = None
        self._pressed_item_id = None
        super().clear()

    # --- 键盘与导航事件 ---
    def keyPressEvent(self, event):
        """重写键盘事件，以处理回车键激活。"""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            current_item = self.currentItem()
            if current_item:
                self._handle_item_activation(current_item)
            event.accept()
        else:
            super().keyPressEvent(event)

    def _on_item_single_clicked(self, item):
        """
        处理单击事件。
        现在可以处理 'back' 和 'system_picker' 两种特殊类型的项目。
        """
        if not item: return
        data = item.data(self.HIERARCHY_DATA_ROLE)
        if not data: return

        item_type = data.get('type')

        if item_type == 'back':
            if len(self._navigation_stack) > 1:
                self._navigation_stack.pop()
                parent_items = self._navigation_stack[-1]
                self._populate_list_with_animation(parent_items)
        elif item_type == 'system_picker':
            # 如果点击了 "系统选择器" 项，则发射新信号
            self.system_picker_activated.emit()

    def _handle_item_activation(self, item):
        """统一的激活处理函数，由双击或回车键调用。"""
        if not item: return
        data = item.data(self.HIERARCHY_DATA_ROLE)
        if not data: return

        item_type = data.get('type')

        if item_type == 'folder':
            children = data.get('children', []).copy()
            back_icon = self.icon_manager.get_icon("prev") if self.icon_manager else QIcon()
            children.insert(0, {'type': 'back', 'text': ' 返回上一级', 'icon': back_icon})
            self._navigation_stack.append(children)
            self._populate_list_with_animation(children)
        
        elif item_type == 'item':
            self.item_activated.emit(item)
            
    # --- 内部核心方法 ---
    def _populate_list_with_animation(self, items_data):
        """
        [v1.2 - Pure Component] 内部核心方法，用给定的数据填充列表并启动动画。
        此版本不再包含任何注入特殊项的业务逻辑，成为一个纯粹的UI组件。
        """
        self.clear()
        
        # 检查动画是否启用 (逻辑不变)
        self._animations_enabled = not (len(items_data) > 20)
        main_window = self.window()
        if hasattr(main_window, 'animations_enabled') and not main_window.animations_enabled:
            self._animations_enabled = False

        # 后续的动画/非动画填充逻辑现在直接使用传入的 items_data
        if self._animations_enabled:
            for data in items_data:
                item = self._create_item_from_data(data)
                self._animation_queue.append(item.data(self.ANIM_HOLDER_ROLE))
                super().addItem(item)
            if self._animation_queue: self._animation_timer.start()
        else:
            self.blockSignals(True)
            for data in items_data:
                item = self._create_item_from_data(data, animated=False)
                super().addItem(item)
            self.blockSignals(False)
            self._on_selection_changed()

    def _create_item_from_data(self, data, animated=True):
        """从数据字典创建一个 QListWidgetItem 并设置其所有属性。"""
        text = data.get('text', 'Unnamed Item')
        item = QListWidgetItem(text)
        
        # [核心新增] 从数据字典中获取Tooltip文本并设置
        tooltip_text = data.get('tooltip', text) # 如果没有tooltip，则用项目文本作为后备
        item.setToolTip(tooltip_text)
        
        item.setData(self.HIERARCHY_DATA_ROLE, data)
        
        holder = _ItemAnimationHolder(item, self)
        if not animated:
            holder.opacity = 1.0
            holder.y_offset = 0
            holder.sync_to_item()
        item.setData(self.ANIM_HOLDER_ROLE, holder)
        return item

    def _process_animation_queue(self):
        """从队列中取出一个项目并启动其进入动画。"""
        if not self._animation_queue:
            self._animation_timer.stop()
            return

        holder = self._animation_queue.pop(0)
        if not holder or not holder.parent(): return

        parallel_anim = QParallelAnimationGroup(holder)
        opacity_anim = QPropertyAnimation(holder, b"opacity"); opacity_anim.setDuration(200); opacity_anim.setEasingCurve(QEasingCurve.OutCubic); opacity_anim.setStartValue(0.0); opacity_anim.setEndValue(1.0)
        offset_anim = QPropertyAnimation(holder, b"y_offset"); offset_anim.setDuration(200); offset_anim.setEasingCurve(QEasingCurve.OutCubic); offset_anim.setStartValue(15); offset_anim.setEndValue(0)
        opacity_anim.valueChanged.connect(holder.update_view); offset_anim.valueChanged.connect(holder.update_view)
        parallel_anim.addAnimation(opacity_anim); parallel_anim.addAnimation(offset_anim)
        parallel_anim.start(QPropertyAnimation.DeleteWhenStopped)
    
    def _animate_item_bg(self, item, end_brush):
        """启动单个项目背景色的过渡动画。"""
        if not item: return
        holder = item.data(self.ANIM_HOLDER_ROLE)
        if not holder: return
        
        if not self._animations_enabled:
            holder.bg_color = end_brush.color(); holder.update_view(); return

        item_id = id(item)
        try:
            if self._current_animations.get(item_id): self._current_animations[item_id].stop()
        except RuntimeError: pass

        anim = QPropertyAnimation(holder, b"bg_color", holder); anim.setDuration(120); anim.setEasingCurve(QEasingCurve.OutCubic); anim.setStartValue(holder.bg_color); anim.setEndValue(end_brush.color()); anim.valueChanged.connect(holder.update_view)
        self._current_animations[item_id] = anim; anim.start(QPropertyAnimation.DeleteWhenStopped)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        old_hovered_id = self._hovered_item_id
        current_item = self.itemAt(event.pos())
        self._hovered_item_id = id(current_item) if current_item else None
        if self._hovered_item_id != old_hovered_id:
            if old_hovered_id: self._update_item_visual_state(self._item_from_id(old_hovered_id))
            if self._hovered_item_id: self._update_item_visual_state(current_item)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        old_hovered_id = self._hovered_item_id
        self._hovered_item_id = None
        if old_hovered_id:
            self._update_item_visual_state(self._item_from_id(old_hovered_id))

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item is None:
            self.setCurrentItem(None)
        elif event.button() == Qt.LeftButton:
            self._pressed_item_id = id(item)
            self._update_item_visual_state(item)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pressed_id = self._pressed_item_id
        self._pressed_item_id = None
        if pressed_id:
            QTimer.singleShot(0, lambda: self._update_item_visual_state(self._item_from_id(pressed_id)))
    
    def _on_selection_changed(self):
        """当选择变化时，强制所有项目更新到其正确状态。"""
        QTimer.singleShot(0, lambda: [self._update_item_visual_state(self.item(i)) for i in range(self.count())])

    def _get_target_brush_for_item(self, item):
        """根据项目的当前状态，决定其目标背景颜色。"""
        item_id = id(item)
        if item.isSelected(): return self.itemSelectedBrush
        if item_id == self._pressed_item_id: return self.itemPressedBrush
        if item_id == self._hovered_item_id: return self.itemHoverBrush
        return self.itemBrush

    def _update_item_visual_state(self, item):
        """检查一个项目的目标状态，并启动动画使其过渡。"""
        if not item: return
        target_brush = self._get_target_brush_for_item(item)
        self._animate_item_bg(item, target_brush)
        
    def _item_from_id(self, item_id):
        """辅助函数：通过内存ID查找 QListWidgetItem。"""
        for i in range(self.count()):
            item = self.item(i)
            if item and id(item) == item_id:
                return item
        return None
        
    def resizeEvent(self, event):
        """当控件大小变化时，重新计算布局以确保省略号正确显示。"""
        super().resizeEvent(event)
        self.scheduleDelayedItemsLayout()
    # [新增 v2.3] 新的公共API，用于追加单个项目
    def appendItemWithAnimation(self, item_data):
        """
        用动画在列表末尾追加单个新项目，而不会清空现有项目。

        Args:
            item_data (dict): 描述单个新项目的数据字典。
                                e.g., {'type': 'item', 'text': 'new clip'}
        """
        # 1. 安全检查
        if not isinstance(item_data, dict):
            print("AnimatedListWidget Error: appendItemWithAnimation expects a dictionary.")
            return

        # 2. 创建 QListWidgetItem 并设置其数据和动画持有者
        #    这里的逻辑与 _populate_list_with_animation 中的单项创建逻辑一致
        item = self._create_item_from_data(item_data)
        
        # 3. 将新项目直接添加到列表的末尾
        super().addItem(item)
        
        # 4. 如果动画被启用，将新项目的动画持有者放入队列并启动定时器
        if self._animations_enabled:
            holder = item.data(self.ANIM_HOLDER_ROLE)
            if holder:
                self._animation_queue.append(holder)
                if not self._animation_timer.isActive():
                    self._animation_timer.start()
# ==============================================================================
# 7. 自定义动画进度条 (AnimatedSlider) - v1.1 [尺寸自适应修复版]
# ==============================================================================
class AnimatedSlider(QSlider):
    """
    一个从 QSlider 继承的、支持丰富动画和主题化的单手柄滑块。
    v1.2: 修复了手柄在放大动画时边缘被裁切的问题，并自动继承 RangeSlider 的样式。
    """
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        
        # --- 内部状态 ---
        self._handle_pressed = False
        self._handle_hovered = False
        self._track_hovered = False
        self.handle_rect = QRect()

        # --- QSS 可配置属性 (从 RangeSlider 借鉴并初始化) ---
        # 这些默认值是为了确保即使QSS没有定义，控件也能正常显示
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
        
        self._trackBrush = QBrush(QColor("#E9EDF0")) # 默认浅灰色轨道
        self._rangeBrush = QBrush(QColor("#3B97E3")) # 默认蓝色填充
        self._hoverTrackBrush = QBrush(QColor("#D9DEE4")) # 悬停时轨道颜色
        self._hoverRangeBrush = QBrush(QColor("#5DA9E8")) # 悬停时填充颜色
        self._handleBrush = QBrush(Qt.white)          # 默认白色手柄
        self._hoverHandleBrush = QBrush(QColor("#E9EDF0")) # 悬停时手柄颜色
        self._pressedHandleBrush = QBrush(QColor("#D9DEE4")) # 按下时手柄颜色
        self._handleBorderColor = QColor("#3B97E3")   # 默认手柄边框色
        self._pressedHandleBorderColor = QColor("#2F78C0") # 按下时手柄边框色
        
        # --- 动画系统 ---
        self._bar_height_anim_value = self._bar_height
        self._handle_w_anim = self._handle_width
        self._handle_h_anim = self._handle_height

        self.bar_animation = QPropertyAnimation(self, b"_bar_height_anim_value")
        self.h_w_anim = QPropertyAnimation(self, b"_handle_w_anim")
        self.h_h_anim = QPropertyAnimation(self, b"_handle_h_anim")
        
        ANIMATION_DURATION = 80
        easing = QEasingCurve.OutCubic
        self.bar_animation.setDuration(ANIMATION_DURATION); self.bar_animation.setEasingCurve(easing)
        self.h_w_anim.setDuration(ANIMATION_DURATION); self.h_w_anim.setEasingCurve(easing)
        self.h_h_anim.setDuration(ANIMATION_DURATION); self.h_h_anim.setEasingCurve(easing)

    # --- 覆盖 sizeHint 和 minimumSizeHint ---
    def sizeHint(self):
        """告诉布局系统此控件的理想尺寸。"""
        # 计算最大可能的手柄高度
        _, max_h = self._get_max_handle_dimension()
        
        # 控件的总高度需要容纳最大手柄、其边框以及一些额外的垂直“呼吸空间”
        height = max_h + self._handle_border_width * 2 + 4 # 4px 额外空间
        
        # 宽度可以是一个合理的默认值，因为滑块通常会水平拉伸
        return QSize(150, height)

    def minimumSizeHint(self):
        """告诉布局系统此控件的最小尺寸。"""
        # 在这种情况下，最小尺寸和理想尺寸应该相同，以确保动画空间。
        return self.sizeHint()

    # --- 动画属性的 pyqtProperty (保持不变) ---
    @pyqtProperty(int)
    def _bar_height_anim_value(self): return self.__bar_height_anim_value
    @_bar_height_anim_value.setter
    def _bar_height_anim_value(self, value): self.__bar_height_anim_value = value; self.update()
    @pyqtProperty(int)
    def _handle_w_anim(self): return self.__handle_w_anim
    @_handle_w_anim.setter
    def _handle_w_anim(self, val): self.__handle_w_anim = val; self.update()
    @pyqtProperty(int)
    def _handle_h_anim(self): return self.__handle_h_anim
    @_handle_h_anim.setter
    def _handle_h_anim(self, val): self.__handle_h_anim = val; self.update()
    
    # --- QSS 颜色属性 (QBrush) (保持不变) ---
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
    
    # --- QSS 边框颜色属性 (QColor) (保持不变) ---
    @pyqtProperty(QColor)
    def handleBorderColor(self): return self._handleBorderColor
    @handleBorderColor.setter
    def handleBorderColor(self, color): self._handleBorderColor = color; self.update()
    @pyqtProperty(QColor)
    def pressedHandleBorderColor(self): return self._pressedHandleBorderColor
    @pressedHandleBorderColor.setter
    def pressedHandleBorderColor(self, color): self._pressedHandleBorderColor = color; self.update()
    
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
    def handleWidth(self, w): self._handle_width = w; self._handle_w_anim = w; self.update()
    @pyqtProperty(int)
    def handleHeight(self): return self._handle_height
    @handleHeight.setter
    def handleHeight(self, h): self._handle_height = h; self._handle_h_anim = h; self.update()
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

    # --- [核心修改] 新增QColor兼容性属性 ---
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
    
    # --- [核心修改] 新增 handleSize 等尺寸兼容性属性 ---
    @pyqtProperty(int)
    def handleSize(self): return self._handle_width
    @handleSize.setter
    def handleSize(self, size): 
        self.handleWidth = size
        self.handleHeight = size

    @pyqtProperty(int)
    def hoverHandleSize(self): return self._hover_handle_width
    @hoverHandleSize.setter
    def hoverHandleSize(self, size): 
        self.hoverHandleWidth = size
        self.hoverHandleHeight = size

    @pyqtProperty(int)
    def pressedHandleSize(self): return self._pressed_handle_width
    @pressedHandleSize.setter
    def pressedHandleSize(self, size): 
        self.pressedHandleWidth = size
        self.pressedHandleHeight = size
    # --- 辅助函数：获取最大手柄尺寸 (用于布局) ---
    def _get_max_handle_dimension(self):
        # 考虑默认、悬停和按下状态下的最大手柄尺寸
        hover_w = self._hover_handle_width if self._hover_handle_width > 0 else self._handle_width + 4
        pressed_w = self._pressed_handle_width if self._pressed_handle_width > 0 else self._handle_width - 2
        max_w = max(self._handle_width, hover_w, pressed_w)

        hover_h = self._hover_handle_height if self._hover_handle_height > 0 else self._handle_height + 4
        pressed_h = self._pressed_handle_height if self._pressed_handle_height > 0 else self._handle_height - 2
        max_h = max(self._handle_height, hover_h, pressed_h)
        return max_w, max_h

    # --- 核心绘制方法 (PaintEvent) ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 阻止原生 QSlider 绘制任何东西，完全由我们接管
        # super().paintEvent(event) # 不要调用父类的 paintEvent
        
        w, h = self.width(), self.height()
        
        # 计算手柄中心点所需的安全边距
        margin = (self._get_max_handle_dimension()[0] + self._handle_border_width) // 2
        
        # 绘制轨道
        current_bar_height = self._bar_height_anim_value
        track_b = self._hoverTrackBrush if self._track_hovered else self._trackBrush
        bar_y = (h - current_bar_height) // 2
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_b)
        painter.drawRoundedRect(margin, bar_y, w - 2 * margin, current_bar_height, current_bar_height//2, current_bar_height//2)
        
        # 绘制已填充部分 (从起始到当前值)
        current_x = self._value_to_pixel(self.value())
        range_b = self._hoverRangeBrush if self._track_hovered else self._rangeBrush
        painter.setBrush(range_b)
        painter.drawRoundedRect(margin, bar_y, current_x - margin, current_bar_height, current_bar_height//2, current_bar_height//2)
        
        # 绘制手柄
        handle_w, handle_h = self._handle_w_anim, self._handle_h_anim
        handle_b, border_c = self._get_handle_brushes(self._handle_pressed, self._handle_hovered)
        painter.setBrush(handle_b)
        painter.setPen(QPen(border_c, self._handle_border_width))
        self.handle_rect = QRect(current_x - handle_w//2, (h-handle_h)//2, handle_w, handle_h)
        painter.drawRoundedRect(self.handle_rect, self._handleRadius, self._handleRadius)

    # --- 动画启动逻辑 ---
    def _start_animations(self):
        bar_target = self._hover_bar_height if self._hover_bar_height > 0 else self._bar_height + 2
        # 如果 QSS 没有定义 hoverBarHeight，就使用默认的 +2 放大效果
        # 如果 QSS 定义了 hoverBarHeight 为 0，则表示不放大
        if self._hover_bar_height == 0 and self._track_hovered:
            self.bar_animation.setEndValue(self._bar_height) # 不放大
        else:
            self.bar_animation.setEndValue(bar_target if self._track_hovered or self._handle_pressed else self._bar_height)
        self.bar_animation.start()
        
        w_target = self._handle_width; h_target = self._handle_height
        if self._handle_pressed:
            w_target = self._pressed_handle_width if self._pressed_handle_width > 0 else self._handle_width - 2
            h_target = self._pressed_handle_height if self._pressed_handle_height > 0 else self._handle_height - 2
        elif self._handle_hovered:
            w_target = self._hover_handle_width if self._hover_handle_width > 0 else self._handle_width + 4
            h_target = self._hover_handle_height if self._hover_handle_height > 0 else self._handle_height + 4
            
        self.h_w_anim.setEndValue(w_target); self.h_h_anim.setEndValue(h_target)
        self.h_w_anim.start(); self.h_h_anim.start()
    
    # --- 辅助方法：获取手柄的画刷和边框颜色 ---
    def _get_handle_brushes(self, pressed, hovered):
        if pressed: 
            return self._pressedHandleBrush, self._pressedHandleBorderColor
        elif hovered: 
            # 如果 QSS 没有定义 hoverHandleBrush，就回退到默认手柄画刷
            if not self._hoverHandleBrush.color().isValid() and self._hoverHandleBrush.style() == Qt.NoBrush:
                return self._handleBrush, self._handleBorderColor
            return self._hoverHandleBrush, self._handleBorderColor
        else: 
            return self._handleBrush, self._handleBorderColor
        
    # --- 事件处理 (MousePress, MouseMove, MouseRelease, Leave) ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            new_val = self._pixel_to_value(event.pos().x())
            self.setValue(new_val) # 立即跳转到点击位置
            self._handle_pressed = True
            self._start_animations()
            # 发射 sliderMoved 信号，让播放器立即响应（QSlider 的标准行为）
            self.sliderMoved.emit(new_val) 
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._handle_pressed:
            new_val = self._pixel_to_value(event.pos().x())
            self.setValue(new_val)
            self.sliderMoved.emit(new_val) # 拖动时持续发射
        
        old_handle_hovered, old_track_hovered = self._handle_hovered, self._track_hovered
        self._handle_hovered = self.handle_rect.contains(event.pos())
        
        # 只有当手柄没有被悬停时，才检查是否悬停在轨道上
        bar_y = (self.height() - self._bar_height_anim_value) // 2
        bar_rect = QRect(0, bar_y, self.width(), self._bar_height_anim_value)
        self._track_hovered = bar_rect.contains(event.pos()) and not self._handle_hovered

        if old_handle_hovered != self._handle_hovered or old_track_hovered != self._track_hovered:
            self._start_animations()
        
        super().mouseMoveEvent(event) # 确保QSlider的原生行为不被完全阻断

    def mouseReleaseEvent(self, event):
        self._handle_pressed = False
        self._start_animations()
        super().mouseReleaseEvent(event) # 确保QSlider的原生行为

    def leaveEvent(self, event):
        self._handle_hovered = False
        self._track_hovered = False
        self._start_animations()
        super().leaveEvent(event) # 确保QSlider的原生行为
    
    # --- 像素与值转换 (与 RangeSlider 几乎相同) ---
    def _value_to_pixel(self, value):
        # 这里的 margin 必须考虑最大手柄尺寸，以确保手柄完全在可见区域内
        margin = (self._get_max_handle_dimension()[0] + self._handle_border_width) // 2
        pixel_span = self.width() - 2 * margin
        span = self.maximum() - self.minimum()
        if span == 0: return margin # 避免除以零
        return int(margin + pixel_span * (value - self.minimum()) / span)

    def _pixel_to_value(self, pixel):
        margin = (self._get_max_handle_dimension()[0] + self._handle_border_width) // 2
        pixel_span = self.width() - 2 * margin
        clamped_pixel = max(margin, min(pixel, self.width() - margin)) # 钳制像素值在有效范围内
        pixel_ratio = (clamped_pixel - margin) / pixel_span if pixel_span > 0 else 0
        span = self.maximum() - self.minimum()
        val = self.minimum() + span * pixel_ratio
        return int(max(self.minimum(), min(self.maximum(), val))) # 钳制结果值在有效范围内
# ==============================================================================
# 8. 自定义动画图标按钮 (AnimatedIconButton) - v2.1 [主题感知版]
# ==============================================================================
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtGui import QIcon, QTransform, QPixmap

class AnimatedIconButton(QPushButton):
    """
    一个能完全继承 QPushButton QSS样式的、支持双图标动态切换动画的图标按钮。
    v2.1: 增加了对 IconManager 的感知，能够在主题切换时自动更新图标颜色。
    """
    def __init__(self, icon_manager=None, parent=None):
        super().__init__(parent)
        self.setText("")

        # [核心修正] 存储 IconManager 引用和图标名称
        self.icon_manager = icon_manager
        self._icon1_name = ""
        self._icon2_name = ""
        self._pixmap1 = QPixmap()
        self._pixmap2 = QPixmap()

        # ... (动画属性和 QSS 属性部分保持不变) ...
        self._scale = 1.0; self._rotation1 = 0.0; self._opacity1 = 1.0
        self._rotation2 = -90.0; self._opacity2 = 0.0
        self._pressedScale = 0.95
        self.scale_anim = QPropertyAnimation(self, b"_scale")
        self.rot1_anim = QPropertyAnimation(self, b"_rotation1")
        self.op1_anim = QPropertyAnimation(self, b"_opacity1")
        self.rot2_anim = QPropertyAnimation(self, b"_rotation2")
        self.op2_anim = QPropertyAnimation(self, b"_opacity2")
        ANIM_DURATION = 150; easing = QEasingCurve.OutCubic
        for anim in [self.scale_anim, self.rot1_anim, self.op1_anim, 
                     self.rot2_anim, self.op2_anim]:
            anim.setDuration(ANIM_DURATION); anim.setEasingCurve(easing)
        self.setCheckable(True)
        self.toggled.connect(self._start_toggle_animation)
        self._sync_visual_to_state(self.isChecked())
        
    # --- 动画和QSS属性的 pyqtProperty (这部分完全不变) ---
    @pyqtProperty(float)
    def _scale(self): return self.__scale
    @_scale.setter
    def _scale(self, value): self.__scale = value; self.update()
    @pyqtProperty(float)
    def _rotation1(self): return self.__rotation1
    @_rotation1.setter
    def _rotation1(self, value): self.__rotation1 = value; self.update()
    @pyqtProperty(float)
    def _opacity1(self): return self.__opacity1
    @_opacity1.setter
    def _opacity1(self, value): self.__opacity1 = value; self.update()
    @pyqtProperty(float)
    def _rotation2(self): return self.__rotation2
    @_rotation2.setter
    def _rotation2(self, value): self.__rotation2 = value; self.update()
    @pyqtProperty(float)
    def _opacity2(self): return self.__opacity2
    @_opacity2.setter
    def _opacity2(self, value): self.__opacity2 = value; self.update()
    @pyqtProperty(float)
    def pressedScale(self): return self._pressedScale
    @pressedScale.setter
    def pressedScale(self, scale): self._pressedScale = scale

    # --- 核心方法 ---
    def setIcons(self, icon1_name, icon2_name):
        """[API变更] 设置按钮的两个状态图标的名称。"""
        self.setIcon(QIcon())
        self._icon1_name = icon1_name
        self._icon2_name = icon2_name
        self._update_pixmaps()

    def setIconSize(self, size):
        super().setIconSize(size)
        if self._icon1_name: # 检查名称是否存在
            self._update_pixmaps()
        self.updateGeometry()

    def sizeHint(self):
        if not self.iconSize().isValid(): return super().sizeHint()
        left = self.style().pixelMetric(QStyle.PM_ButtonMargin, None, self)
        right, top, bottom = left, left, left
        w = self.iconSize().width() + left + right
        h = self.iconSize().height() + top + bottom
        return QSize(w, h)

    def _update_pixmaps(self):
        """[核心重构] 通过 IconManager 实时获取着色后的图标。"""
        size = self.iconSize()
        if self.icon_manager and self._icon1_name:
            icon1 = self.icon_manager.get_icon(self._icon1_name)
            self._pixmap1 = icon1.pixmap(size)
        
        if self.icon_manager and self._icon2_name:
            icon2 = self.icon_manager.get_icon(self._icon2_name)
            self._pixmap2 = icon2.pixmap(size)
            
        self.update()

    # --- [核心新增] paintEvent 现在会先更新pixmap ---
    def paintEvent(self, event):
        # 在每次重绘前，都重新获取一次pixmap，以响应主题变化
        # 这是一种简单有效的策略，因为IconManager内部有缓存，所以性能开销极小。
        self._update_pixmaps()
        
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        contents_rect = self.contentsRect()
        center = contents_rect.center()

        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)
        
        # ... (后续的 painter.save/restore/drawPixmap 逻辑保持完全不变) ...
        if not self._pixmap1.isNull() and self._opacity1 > 0.01:
            painter.save()
            painter.setOpacity(self._opacity1)
            painter.translate(center)
            painter.rotate(self._rotation1)
            painter.translate(-center)
            painter.drawPixmap(center.x() - self._pixmap1.width() // 2, 
                               center.y() - self._pixmap1.height() // 2,
                               self._pixmap1)
            painter.restore()
        if not self._pixmap2.isNull() and self._opacity2 > 0.01:
            painter.save()
            painter.setOpacity(self._opacity2)
            painter.translate(center)
            painter.rotate(self._rotation2)
            painter.translate(-center)
            painter.drawPixmap(center.x() - self._pixmap2.width() // 2, 
                               center.y() - self._pixmap2.height() // 2,
                               self._pixmap2)
            painter.restore()

    # --- 其他方法 (事件处理, 动画逻辑) 保持完全不变 ---
    def _sync_visual_to_state(self, checked):
        if checked: self._rotation1, self._opacity1, self._rotation2, self._opacity2 = 90.0, 0.0, 0.0, 1.0
        else: self._rotation1, self._opacity1, self._rotation2, self._opacity2 = 0.0, 1.0, -90.0, 0.0
        self.update()
    def _start_toggle_animation(self, checked):
        for anim in [self.rot1_anim, self.op1_anim, self.rot2_anim, self.op2_anim]: anim.stop()
        self.rot1_anim.setStartValue(self._rotation1); self.op1_anim.setStartValue(self._opacity1)
        self.rot2_anim.setStartValue(self._rotation2); self.op2_anim.setStartValue(self._opacity2)
        if checked:
            self.rot1_anim.setEndValue(90.0); self.op1_anim.setEndValue(0.0)
            self.rot2_anim.setEndValue(0.0); self.op2_anim.setEndValue(1.0)
        else:
            self.rot1_anim.setEndValue(0.0); self.op1_anim.setEndValue(1.0)
            self.rot2_anim.setEndValue(-90.0); self.op2_anim.setEndValue(0.0)
        self.rot1_anim.start(); self.op1_anim.start()
        self.rot2_anim.start(); self.op2_anim.start()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.scale_anim.stop(); self.scale_anim.setEndValue(self._pressedScale); self.scale_anim.start()
        super().mousePressEvent(event)
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.scale_anim.stop(); self.scale_anim.setEndValue(1.0); self.scale_anim.start()
        super().mouseReleaseEvent(event)

import os
import sys
import subprocess
from PyQt5.QtWidgets import (QMenu, QMessageBox,QGroupBox)
class WordlistSelectionDialog(QDialog):
    """
    [v2.1 - 动画可禁用版]
    一个可复用的、弹出式的对话框，使用 AnimatedListWidget 来提供层级式词表选择。
    
    特性:
    - 支持无限层级的文件夹导航。
    - 顶置搜索栏，可对所有层级的词表进行实时、不区分大小写的模糊搜索。
    - 列表和搜索结果中不显示 '.json' 文件后缀，界面更简洁。
    - 支持右键菜单，提供“固定/取消固定”、“打开文件”、“打开目录”等功能。
    - 界面元素被包裹在 QGroupBox 中，以获得更佳的视觉分组和边距。
    - 内部的 AnimatedListWidget 会自动响应全局的动画禁用设置。
    """
    
    # [核心重构] 修改 __init__ 签名，使其更通用
    def __init__(self, parent, word_list_dir, icon_manager, pin_handler=None):
        """
        构造函数。
        
        Args:
            parent: 父QObject。
            word_list_dir (str): 要扫描的词表根目录。
            icon_manager: IconManager 实例。
            pin_handler (optional): 一个可选的对象，如果提供，
                                    必须实现 is_wordlist_pinned(rel_path) 和
                                    toggle_pin_wordlist(rel_path) 方法。
                                    如果为 None，则禁用固定功能。
        """
        super().__init__(parent)
        # [核心重构] 直接使用传入的参数
        self.word_list_dir = word_list_dir
        self.icon_manager = icon_manager
        self.pin_handler = pin_handler
        
        # [核心重构] parent_page 不再是一个必需的、具有特定接口的复杂对象
        self.parent_page = parent
        
        self.selected_file_relpath = None 
        self._all_items_cache = []

        self.animations_enabled = getattr(self.window(), 'animations_enabled', True)

        self.setWindowTitle("选择单词表")
        self.setWindowIcon(self.window().windowIcon())
        self.setStyleSheet(self.window().styleSheet())
        self.setMinimumSize(400, 500)
        
        self._init_ui()
        self._connect_signals()
        self.populate_list()

    def _init_ui(self):
        """构建对话框的用户界面。"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        container_groupbox = QGroupBox("可用的单词表")
        container_layout = QVBoxLayout(container_groupbox)
        container_layout.setContentsMargins(10, 15, 10, 10)
        container_layout.setSpacing(8)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索词表 (例如: animals)...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setObjectName("WordlistSearchInput")

        self.list_widget = AnimatedListWidget(icon_manager=self.parent_page.icon_manager)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        
        container_layout.addWidget(self.search_input)
        container_layout.addWidget(self.list_widget)
        main_layout.addWidget(container_groupbox)

    def _connect_signals(self):
        """连接所有UI控件的信号到对应的槽函数。"""
        self.list_widget.item_activated.connect(self.on_item_selected)
        self.search_input.textChanged.connect(self._filter_list)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        # [核心新增] 连接来自 AnimatedListWidget 的新信号
        self.list_widget.system_picker_activated.connect(self.open_system_file_dialog)

    def _parse_wordlist_for_tooltip(self, file_path):
        """解析指定的词表JSON文件，并生成一个用于Tooltip的HTML字符串。"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            meta = data.get('meta', {})
            # 优先使用元数据中的描述，否则使用文件名
            name = os.path.splitext(os.path.basename(file_path))[0]
            description = meta.get('description', '无详细描述。')
            author = meta.get('author', '未知')
            version = meta.get('version', 'N/A')

            # 构建HTML头部
            html = (f"<b>{name}</b> (v{version})<br>"
                    f"<i>{description}</i><br>"
                    f"作者: {author}<hr>")

            # 提取前三项作为预览
            groups = data.get('groups', [])
            preview_items = []
            item_count = 0
            for group in groups:
                if item_count >= 3:
                    break
                for item in group.get('items', []):
                    if item_count >= 3:
                        break
                    preview_items.append(item.get('text', ''))
                    item_count += 1
            
            if preview_items:
                html += "<b>内容预览:</b><br>"
                for text in preview_items:
                    # 使用HTML实体编码以防止特殊字符破坏布局
                    import html as html_converter
                    safe_text = html_converter.escape(text)
                    html += f"• {safe_text}<br>"
            
            return html.rstrip('<br>')

        except Exception as e:
            return f"无法解析词表: {os.path.basename(file_path)}\n错误: {e}"

    # [核心新增] 实现打开系统文件选择器的槽函数
    def open_system_file_dialog(self):
        """
        当用户点击 "从其他位置选择..." 时，打开一个标准的 QFileDialog。
        """
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "选择词表文件",
            self.word_list_dir, # 对话框默认打开词表根目录
            "JSON 文件 (*.json)"
        )
        
        if filepath:
            # 如果用户选择了一个文件，则执行与 on_item_selected 相同的逻辑
            rel_path = os.path.relpath(filepath, self.word_list_dir)
            self.selected_file_relpath = rel_path.replace("\\", "/")
            self.accept() # 以成功状态关闭对话框

    def on_item_selected(self, item):
        """当用户选择一个文件后，存储其相对路径并关闭对话框。"""
        item_data = item.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
        full_path = item_data.get('data', {}).get('path')
        if full_path:
            # [核心重构] 使用 self.word_list_dir 计算相对路径
            rel_path = os.path.relpath(full_path, self.word_list_dir)
            self.selected_file_relpath = rel_path.replace("\\", "/")
            self.accept()

    def _filter_list(self, text):
        """根据搜索框的文本实时过滤列表显示内容。"""
        search_term = text.strip().lower()
        if not search_term:
            if self.list_widget._navigation_stack:
                 top_level_data = self.list_widget._navigation_stack[0]
                 self.list_widget._populate_list_with_animation(top_level_data)
            return
        matching_items = [item for item in self._all_items_cache if search_term in item['search_text']]
        for item in matching_items:
            item['text'] = item['search_text'].replace("/", " / ")
        self.list_widget._populate_list_with_animation(matching_items)

    def show_context_menu(self, position):
        """当用户在列表上右键单击时，显示上下文菜单。"""
        item = self.list_widget.itemAt(position)
        if not item: return
        
        item_data = item.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
        if not item_data: return

        item_type = item_data.get('type')
        full_path = item_data.get('data', {}).get('path')
        # [核心修复] 使用 self.icon_manager
        icon_manager = self.icon_manager
        menu = QMenu(self.list_widget)

        if item_type == 'item':
            # [核心修复] 使用 self.word_list_dir 计算相对路径
            rel_path = os.path.relpath(full_path, self.word_list_dir).replace("\\", "/")
            
            pin_action = None
            if self.pin_handler:
                is_pinned = self.pin_handler.is_wordlist_pinned(rel_path)
                pin_action = menu.addAction(
                    icon_manager.get_icon("unpin" if is_pinned else "pin"), 
                    "取消固定" if is_pinned else "固定到顶部"
                )
                menu.addSeparator()

            open_file_action = menu.addAction(icon_manager.get_icon("open_external"), "用默认程序打开")
            open_folder_action = menu.addAction(icon_manager.get_icon("show_in_explorer"), "打开所在目录")
            
            action = menu.exec_(self.list_widget.mapToGlobal(position))
            
            if action == pin_action and self.pin_handler:
                self.pin_handler.toggle_pin_wordlist(rel_path)
                self.populate_list()
            elif action == open_file_action: 
                self._open_system_default(full_path)
            elif action == open_folder_action: 
                self._open_system_default(os.path.dirname(full_path))

        elif item_type == 'folder':
            first_child_path = item_data.get('children', [{}])[0].get('data', {}).get('path')
            if not first_child_path: return
            
            folder_path = os.path.dirname(first_child_path)
            open_folder_action = menu.addAction(icon_manager.get_icon("open_folder"), "打开目录")
            
            action = menu.exec_(self.list_widget.mapToGlobal(position))
            
            if action == open_folder_action: 
                self._open_system_default(folder_path)

    def _open_system_default(self, path):
        """跨平台地使用系统默认程序打开文件或文件夹。"""
        try:
            if sys.platform == 'win32': os.startfile(os.path.realpath(path))
            elif sys.platform == 'darwin': subprocess.check_call(['open', path])
            else: subprocess.check_call(['xdg-open', path])
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法打开路径: {path}\n错误: {e}")
            
    def populate_list(self):
        """
        [v1.1] 扫描词表目录，构建列表，并手动添加 "从其他位置选择" 选项。
        """
        base_dir = self.word_list_dir
        icon_manager = self.icon_manager
        
        pinned_shortcuts, regular_items = [], []
        self._all_items_cache.clear()
        folder_map = {}

        try:
            # --- (扫描文件和构建列表的逻辑保持不变) ---
            for root, _, files in os.walk(base_dir):
                for filename in files:
                    if not filename.endswith('.json'): continue
                    
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, base_dir).replace("\\", "/")
                    display_name, _ = os.path.splitext(filename)
                    
                    is_pinned = self.pin_handler.is_wordlist_pinned(rel_path) if self.pin_handler else False
                    
                    tooltip_html = self._parse_wordlist_for_tooltip(full_path)

                    item_data = {
                        'type': 'item',
                        'icon': icon_manager.get_icon("document"),
                        'data': {'path': full_path},
                        'tooltip': tooltip_html
                    }
                    
                    if is_pinned:
                        shortcut = item_data.copy()
                        shortcut['icon'] = icon_manager.get_icon("pin")
                        shortcut['text'] = f"{os.path.basename(root)} / {display_name}" if root != base_dir else display_name
                        pinned_shortcuts.append(shortcut)
                    else:
                        item_data['text'] = display_name
                        if root not in folder_map: folder_map[root] = []
                        folder_map[root].append(item_data)
                    
                    search_item = item_data.copy()
                    search_item['search_text'] = f"{os.path.basename(root)}/{display_name}".lower() if root != base_dir else display_name.lower()
                    self._all_items_cache.append(search_item)
            
            if base_dir in folder_map:
                root_files = sorted(folder_map[base_dir], key=lambda x: x['text'])
                regular_items.extend(root_files)
                del folder_map[base_dir]
            
            for folder_path in sorted(folder_map.keys()):
                children = sorted(folder_map[folder_path], key=lambda x: x['text'])
                folder_tooltip = f"文件夹: {os.path.basename(folder_path)}"
                regular_items.append({
                    'type': 'folder', 
                    'text': os.path.basename(folder_path), 
                    'icon': icon_manager.get_icon("folder"), 
                    'children': children,
                    'tooltip': folder_tooltip
                })
            
            # --- (排序逻辑保持不变) ---
            regular_items.sort(key=lambda x: (x['type'] != 'folder', x['text']))
            pinned_shortcuts.sort(key=lambda x: x['text'])
            
            # [核心修改] 在这里构建最终的显示列表，并手动添加特殊项
            final_display_list = pinned_shortcuts + regular_items
            
            icon = self.icon_manager.get_icon("open_folder") if self.icon_manager else QIcon()
            final_display_list.append({
                'type': 'system_picker',
                'text': '从其他位置选择词表...',
                'icon': icon,
                'tooltip': '打开系统文件选择器来浏览并选择一个词表文件。'
            })
            
            # 将构建完成的、包含特殊项的列表传递给 AnimatedListWidget
            self.list_widget.setHierarchicalData(final_display_list)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"扫描并构建词表列表时发生错误: {e}")
