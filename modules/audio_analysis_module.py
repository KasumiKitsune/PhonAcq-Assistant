# --- START OF FILE modules/audio_analysis_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "音频分析"
MODULE_DESCRIPTION = "对单个音频文件进行声学分析，包括波形、语谱图、基频(F0)、强度和共振峰的可视化，并支持对长音频的流畅缩放与导航。"
# ---

import os
import re
import sys
from datetime import timedelta
import math # 新增导入

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QMessageBox, QGroupBox, QFormLayout, QSizePolicy, QSlider,
                             QScrollBar, QProgressDialog, QFileDialog, QCheckBox, QLineEdit,
                             QMenu, QAction, QDialog, QDialogButtonBox, QComboBox) # 新增导入 QMenu, QAction
from PyQt5.QtCore import Qt, QUrl, QPointF, QThread, pyqtSignal, QObject, pyqtProperty, QRect, QPoint
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPalette, QImage, QIntValidator, QPixmap, QRegion, QFont, QCursor

# 模块级别依赖检查
try:
    import numpy as np
    import soundfile as sf
    import librosa
    import pandas as pd
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: audio_analysis_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)


# --- 后台工作器 (无变化) ---
class AudioTaskWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, task_type, filepath=None, audio_data=None, sr=None, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.filepath = filepath
        self.y = audio_data
        self.sr = sr
        self.kwargs = kwargs

    def run(self):
        try:
            if self.task_type == 'load': self._run_load_task()
            elif self.task_type == 'analyze': self._run_analyze_task()
            elif self.task_type == 'analyze_formants_view': self._run_formant_view_task()
        except Exception as e: self.error.emit(str(e))

    def _run_load_task(self):
        y, sr = librosa.load(self.filepath, sr=None, mono=True)
        overview_points = 4096
        if len(y) > overview_points:
            chunk_size = len(y) // overview_points
            y_overview = np.array([np.mean(y[i:i+chunk_size]) for i in range(0, len(y), chunk_size)])
        else:
            y_overview = y
        self.finished.emit({ 'y_full': y, 'sr': sr, 'y_overview': y_overview })

    def _run_analyze_task(self):
        is_wide_band = self.kwargs.get('is_wide_band', False)
        density_level = self.kwargs.get('density_level', 3)
        pre_emphasis = self.kwargs.get('pre_emphasis', False)
        f0_min = self.kwargs.get('f0_min', librosa.note_to_hz('C2'))
        f0_max = self.kwargs.get('f0_max', librosa.note_to_hz('C7'))
        y_analyzed = librosa.effects.preemphasis(self.y) if pre_emphasis else self.y
        analysis_density_level = min(density_level, 5)
        narrow_band_window_s = 0.035
        base_n_fft_for_hop = 1 << (int(self.sr * narrow_band_window_s) - 1).bit_length()
        overlap_ratio = 1 - (1 / (2**analysis_density_level))
        hop_length = int(base_n_fft_for_hop * (1 - overlap_ratio)) or 1
        spectrogram_window_s = 0.005 if is_wide_band else narrow_band_window_s
        n_fft_spectrogram = 1 << (int(self.sr * spectrogram_window_s) - 1).bit_length()
        f0_frame_length = 1 << (int(self.sr * 0.040) - 1).bit_length()
        f0_raw, voiced_flag, _ = librosa.pyin(y_analyzed, fmin=f0_min, fmax=f0_max, frame_length=f0_frame_length, hop_length=hop_length)
        times = librosa.times_like(f0_raw, sr=self.sr, hop_length=hop_length)
        f0_raw[~voiced_flag] = np.nan
        f0_series = pd.Series(f0_raw)
        f0_interpolated = f0_series.interpolate(method='linear', limit_direction='both').to_numpy()
        intensity = librosa.feature.rms(y=self.y, frame_length=n_fft_spectrogram, hop_length=hop_length)[0]
        D = librosa.stft(y_analyzed, hop_length=hop_length, n_fft=n_fft_spectrogram)
        S_db = librosa.amplitude_to_db(np.abs(D), ref=np.max)
        self.finished.emit({'f0_raw': (times, f0_raw), 'f0_derived': (times, f0_interpolated), 'intensity': intensity, 'S_db': S_db, 'hop_length': hop_length})

    def _run_formant_view_task(self):
        start_sample, end_sample = self.kwargs.get('start_sample', 0), self.kwargs.get('end_sample', len(self.y))
        hop_length = self.kwargs.get('hop_length', 128)
        pre_emphasis = self.kwargs.get('pre_emphasis', False)
        
        y_view_orig = self.y[start_sample:end_sample]
        y_view = librosa.effects.preemphasis(y_view_orig) if pre_emphasis else y_view_orig
        
        frame_length = int(self.sr * 0.025)
        order = 2 + self.sr // 1000
        formant_points = []

        # --- [核心修改] 新增：计算RMS能量和阈值 ---
        # 1. 计算整个视图区域的RMS能量，用于确定一个动态的阈值
        rms = librosa.feature.rms(y=y_view_orig, frame_length=frame_length, hop_length=hop_length)[0]
        
        # 2. 设置一个动态能量阈值。例如，最大能量的10%。
        # 这个百分比可以根据需要调整，0.05到0.15是比较常用的范围。
        # 我们使用一个较低的阈值（如5%）以避免切掉弱元音，但足以过滤掉大部分静音。
        energy_threshold = np.max(rms) * 0.05 
        
        # 确保RMS数组和我们接下来的循环是对齐的
        frame_index = 0

        for i in range(0, len(y_view) - frame_length, hop_length):
            # --- [核心修改] 在分析前检查能量 ---
            # 3. 检查当前帧的能量是否高于阈值
            if frame_index < len(rms) and rms[frame_index] < energy_threshold:
                frame_index += 1
                continue # 能量太低，跳过此帧，不进行分析

            y_frame = y_view[i : i + frame_length]

            # 之前的检查（如np.max, np.isfinite）仍然保留，作为双重保障
            if np.max(np.abs(y_frame)) < 1e-5 or not np.isfinite(y_frame).all():
                frame_index += 1
                continue

            try:
                a = librosa.lpc(y_frame, order=order)
                if not np.isfinite(a).all(): 
                    frame_index += 1
                    continue
                roots = [r for r in np.roots(a) if np.imag(r) >= 0]
                freqs = sorted(np.angle(roots) * (self.sr / (2 * np.pi)))
                
                # ... (后续的共振峰筛选逻辑保持不变) ...
                found_formants, formant_ranges = [], [(250, 800), (800, 2200), (2200, 3000), (3000, 4000)]
                candidate_freqs = list(freqs)
                for f_min, f_max in formant_ranges:
                    band_freqs = [f for f in candidate_freqs if f_min <= f <= f_max]
                    if band_freqs:
                        best_f = band_freqs[0]; found_formants.append(best_f); candidate_freqs.remove(best_f)
                if found_formants:
                    formant_points.append((start_sample + i + frame_length // 2, found_formants))
            except Exception:
                # 即使出错也要增加索引
                frame_index += 1
                continue
            
            # 成功处理完一帧后，增加帧索引
            frame_index += 1

        self.finished.emit({'formants_view': formant_points})

class ExportDialog(QDialog):
    """一个让用户选择导出图片分辨率和样式的对话框。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出图片选项")
        
        layout = QFormLayout(self)
        
        # --- 分辨率部分 (不变) ---
        self.presets_combo = QComboBox()
        self.presets = {
            "当前窗口大小": None,
            "HD (1280x720)": (1280, 720),
            "Full HD (1920x1080)": (1920, 1080),
            "2K (2560x1440)": (2560, 1440),
            "4K (3840x2160)": (3840, 2160)
        }
        self.presets_combo.addItems(self.presets.keys())
        self.presets_combo.currentTextChanged.connect(self.on_preset_changed)
        
        custom_layout = QHBoxLayout()
        self.width_input = QLineEdit("1920")
        self.width_input.setValidator(QIntValidator(100, 8000))
        self.height_input = QLineEdit("1080")
        self.height_input.setValidator(QIntValidator(100, 8000))
        custom_layout.addWidget(QLabel("宽:"))
        custom_layout.addWidget(self.width_input)
        custom_layout.addWidget(QLabel("高:"))
        custom_layout.addWidget(self.height_input)
        custom_layout.addWidget(QLabel("px"))
        
        layout.addRow("分辨率:", self.presets_combo)
        layout.addRow("自定义:", custom_layout)
        
        # --- 新增: 样式选项 (修改后) ---
        options_group = QGroupBox("样式选项")
        options_layout = QVBoxLayout(options_group)
        
        self.info_label_check = QCheckBox("添加信息标签")
        self.info_label_check.setToolTip("在图片的右上角添加包含文件名、时长等基本信息的标签。")
        self.info_label_check.setChecked(True)

        self.time_axis_check = QCheckBox("在底部添加时间轴")
        self.time_axis_check.setToolTip("在图片底部渲染一个与视图范围匹配的时间轴。")
        self.time_axis_check.setChecked(True)
        
        options_layout.addWidget(self.info_label_check)
        options_layout.addWidget(self.time_axis_check)
        
        layout.addWidget(options_group)

        # --- 按钮部分 (不变) ---
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # 初始化状态
        self.on_preset_changed(self.presets_combo.currentText())

    def on_preset_changed(self, text):
        # ... (此方法不变)
        resolution = self.presets.get(text)
        if resolution:
            self.width_input.setText(str(resolution[0]))
            self.height_input.setText(str(resolution[1]))
            self.width_input.setEnabled(False)
            self.height_input.setEnabled(False)
        else:
            self.width_input.setEnabled(True)
            self.height_input.setEnabled(True)

    def get_options(self):
        """返回所有导出选项。"""
        resolution = None
        if self.presets_combo.currentText() != "当前窗口大小":
            try:
                resolution = (int(self.width_input.text()), int(self.height_input.text()))
            except ValueError:
                resolution = (1920, 1080)

        return {
            "resolution": resolution,
            "info_label": self.info_label_check.isChecked(),
            "add_time_axis": self.time_axis_check.isChecked()
        }
# --- 新增: 时间轴控件 ---
class TimeAxisWidget(QWidget):
    """一个用于在波形和语谱图之间显示动态时间轴的控件。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(25)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._view_start_sample = 0
        self._view_end_sample = 1
        self._sr = 1
        self.font_color = QColor(Qt.black)
        self.line_color = QColor(Qt.darkGray)

    def update_view(self, start_sample, end_sample, sr):
        """更新视图范围和采样率，并触发重绘。"""
        self._view_start_sample = start_sample
        self._view_end_sample = end_sample
        self._sr = sr
        # 主题颜色适配
        self.font_color = self.palette().color(QPalette.Text)
        self.line_color = self.palette().color(QPalette.Mid)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        painter.fillRect(rect, self.palette().color(QPalette.Window))

        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0 or self._sr <= 1:
            return

        view_duration_s = view_width_samples / self._sr
        start_time_s = self._view_start_sample / self._sr
        
        # --- 智能刻度计算 ---
        # 目标是在屏幕上显示5-10个主刻度
        target_ticks = 10
        raw_interval = view_duration_s / target_ticks
        
        # 将原始间隔规整到人类友好的单位 (1, 2, 5的倍数)
        power = 10.0 ** math.floor(math.log10(raw_interval))
        if raw_interval / power < 1.5:
            interval = 1 * power
        elif raw_interval / power < 3.5:
            interval = 2 * power
        elif raw_interval / power < 7.5:
            interval = 5 * power
        else:
            interval = 10 * power

        # 设置绘图属性
        painter.setPen(QPen(self.line_color, 1))
        font = self.font()
        font.setPointSize(8)
        painter.setFont(font)
        
        # 确定第一个刻度的起始时间
        first_tick_time = math.ceil(start_time_s / interval) * interval

        for i in range(int(target_ticks * 2)): # 绘制足够多的刻度以覆盖视图
            tick_time = first_tick_time + i * interval
            if tick_time > start_time_s + view_duration_s:
                break

            # 将时间转换为X坐标
            x_pos = (tick_time - start_time_s) / view_duration_s * rect.width()
            
            # 绘制主刻度线
            painter.drawLine(int(x_pos), rect.height() - 8, int(x_pos), rect.height())
            
            # 绘制时间标签
            label = f"{tick_time:.2f}"
            
            painter.setPen(self.font_color)
            painter.drawText(QRect(int(x_pos) - 30, 0, 60, rect.height() - 10), Qt.AlignCenter, label)
            painter.setPen(self.line_color) # 换回线条颜色


# --- 语谱图控件 (修改版) ---
class SpectrogramWidget(QWidget):
    # 新增信号，用于与主页面通信
    selectionChanged = pyqtSignal(object)  # object可以是(start, end)元组或None
    zoomToSelectionRequested = pyqtSignal(int, int)
    exportViewAsImageRequested = pyqtSignal()
    exportAnalysisToCsvRequested = pyqtSignal()
    exportSelectionAsWavRequested = pyqtSignal()
    spectrumSliceRequested = pyqtSignal(int)

    # 修改构造函数以接收IconManager
    def __init__(self, parent, icon_manager):
        super().__init__(parent)
        self.icon_manager = icon_manager # 保存icon_manager实例
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True) # 开启鼠标跟踪以实时更新信息
        
        # 选区相关属性
        self._is_selecting = False
        self._selection_start_pos = None
        self._selection_end_pos = None
        self._selection_start_sample = None
        self._selection_end_sample = None
        self._selection_color = QColor(135, 206, 250, 70) # 淡蓝色半透明

        # --- 其他所有旧属性保持不变 ---
        self.spectrogram_image = None
        self._view_start_sample, self._view_end_sample = 0, 1
        self.sr, self.hop_length = 1, 256
        self._playback_pos_sample = -1
        self._f0_data, self._intensity_data, self._formants_data = None, None, []
        self._f0_derived_data = None
        self._show_f0, self._show_f0_points, self._show_f0_derived = False, True, True
        self._show_intensity, self._smooth_intensity = False, False
        self._show_formants, self._highlight_f1, self._highlight_f2, self._show_other_formants = False, True, True, True
        self.max_display_freq = 5000
        self._cursor_info_text = ""
        self.waveform_sibling = None
        self._f0_display_min, self._f0_display_max = 75, 400
        self._f0_axis_enabled = False
        self._backgroundColor = Qt.white
        self._spectrogramMinColor, self._spectrogramMaxColor = Qt.white, Qt.black
        self._intensityColor = QColor("#4CAF50")
        self._f0Color = QColor("#FFA726")
        self._f0DerivedColor = QColor(150, 150, 255, 150)
        self._f1Color = QColor("#FF6F00")
        self._f2Color = QColor("#9C27B0")
        self._formantColor = QColor("#29B6F6")
        self._cursorColor = QColor("red")
        self._infoTextColor, self._infoBackgroundColor = Qt.white, QColor(0, 0, 0, 150)
        self._f0AxisColor = QColor(150, 150, 150)
        self._info_box_position = 'top_left' # 'top_left' or 'bottom_right'

    # --- 所有 @pyqtProperty 装饰器和 set_overlay_visibility 方法保持不变 ---
    @pyqtProperty(QColor)
    def backgroundColor(self): return self._backgroundColor
    @backgroundColor.setter
    def backgroundColor(self, color): self._backgroundColor = color; self.update()
    @pyqtProperty(QColor)
    def spectrogramMinColor(self): return self._spectrogramMinColor
    @spectrogramMinColor.setter
    def spectrogramMinColor(self, color): self._spectrogramMinColor = color; self.update()
    @pyqtProperty(QColor)
    def spectrogramMaxColor(self): return self._spectrogramMaxColor
    @spectrogramMaxColor.setter
    def spectrogramMaxColor(self, color): self._spectrogramMaxColor = color; self.update()
    @pyqtProperty(QColor)
    def intensityColor(self): return self._intensityColor
    @intensityColor.setter
    def intensityColor(self, color): self._intensityColor = color; self.update()
    @pyqtProperty(QColor)
    def f0Color(self): return self._f0Color
    @f0Color.setter
    def f0Color(self, color): self._f0Color = color; self.update()
    @pyqtProperty(QColor)
    def f0DerivedColor(self): return self._f0DerivedColor
    @f0DerivedColor.setter
    def f0DerivedColor(self, color): self._f0DerivedColor = color; self.update()
    @pyqtProperty(QColor)
    def f1Color(self): return self._f1Color
    @f1Color.setter
    def f1Color(self, color): self._f1Color = color; self.update()
    @pyqtProperty(QColor)
    def f2Color(self): return self._f2Color
    @f2Color.setter
    def f2Color(self, color): self._f2Color = color; self.update()
    @pyqtProperty(QColor)
    def formantColor(self): return self._formantColor
    @formantColor.setter
    def formantColor(self, color): self._formantColor = color; self.update()
    @pyqtProperty(QColor)
    def cursorColor(self): return self._cursorColor
    @cursorColor.setter
    def cursorColor(self, color): self._cursorColor = color; self.update()
    @pyqtProperty(QColor)
    def infoTextColor(self): return self._infoTextColor
    @infoTextColor.setter
    def infoTextColor(self, color): self._infoTextColor = color; self.update()
    @pyqtProperty(QColor)
    def infoBackgroundColor(self): return self._infoBackgroundColor
    @infoBackgroundColor.setter
    def infoBackgroundColor(self, color): self._infoBackgroundColor = color; self.update()
    @pyqtProperty(QColor)
    def f0AxisColor(self): return self._f0AxisColor
    @f0AxisColor.setter
    def f0AxisColor(self, color): self._f0AxisColor = color; self.update()
    
    def set_overlay_visibility(self, show_f0, show_f0_points, show_f0_derived,
                               show_intensity, smooth_intensity,
                               show_formants, highlight_f1, highlight_f2, show_other_formants):
        self._show_f0, self._show_f0_points, self._show_f0_derived = show_f0, show_f0_points, show_f0_derived
        self._show_intensity, self._smooth_intensity = show_intensity, smooth_intensity
        self._show_formants, self._highlight_f1, self._highlight_f2, self._show_other_formants = show_formants, highlight_f1, highlight_f2, show_other_formants
        self.update()

    def _get_plot_rect(self):
        """[新增] 辅助函数，获取绘图安全区"""
        padding_left, padding_right = 45, 45
        padding_top, padding_bottom = 10, 10
        return self.rect().adjusted(padding_left, padding_top, -padding_right, -padding_bottom)

    def _pixel_to_sample(self, x_pixel):
        """[新增] 辅助函数，将绘图区内的像素X坐标转换为音频采样点索引"""
        plot_rect = self._get_plot_rect()
        if not plot_rect.isValid() or plot_rect.width() == 0:
            return 0
        
        view_width_samples = self._view_end_sample - self._view_start_sample
        x_ratio = (x_pixel - plot_rect.left()) / plot_rect.width()
        sample_offset = x_ratio * view_width_samples
        return int(self._view_start_sample + sample_offset)

    def _sample_to_pixel(self, sample_index):
        """[新增] 辅助函数，将音频采样点索引转换为绘图区内的像素X坐标"""
        plot_rect = self._get_plot_rect()
        if not plot_rect.isValid():
            return 0
        
        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples == 0:
            return plot_rect.left()

        sample_offset = sample_index - self._view_start_sample
        x_ratio = sample_offset / view_width_samples
        return int(plot_rect.left() + x_ratio * plot_rect.width())

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self._backgroundColor)

        plot_rect = self._get_plot_rect()
        
        if not plot_rect.isValid(): return

        w, h = plot_rect.width(), plot_rect.height()
        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0: return

        # --- 绘制语谱图背景 ---
        if self.spectrogram_image:
            start_frame = self._view_start_sample // self.hop_length
            end_frame = self._view_end_sample // self.hop_length
            view_width_frames = end_frame - start_frame
            if view_width_frames > 0:
                source_rect = QRect(start_frame, 0, view_width_frames, self.spectrogram_image.height())
                painter.drawImage(plot_rect, self.spectrogram_image, source_rect)

        # --- 绘制坐标轴和网格线 ---
        painter.setPen(QPen(self._f0AxisColor, 1, Qt.DotLine)); font = self.font(); font.setPointSize(8); painter.setFont(font)
        # 左侧频率轴 (Hz)
        for freq in range(0, int(self.max_display_freq) + 1, 1000):
            if freq == 0 and self.max_display_freq > 0: continue
            y = plot_rect.bottom() - (freq / self.max_display_freq * h)
            painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y)) 
            painter.drawText(QPointF(plot_rect.left() - 35, int(y) + 4), f"{freq}")
        # 右侧基频轴 (Hz)
        if self._f0_axis_enabled:
            f0_display_range = self._f0_display_max - self._f0_display_min
            if f0_display_range > 0:
                step = 50 if f0_display_range > 200 else 25 if f0_display_range > 100 else 10
                for freq in range(int(self._f0_display_min // step * step), int(self._f0_display_max) + 1, step):
                    if freq < self._f0_display_min: continue
                    y = plot_rect.bottom() - ((freq - self._f0_display_min) / f0_display_range * h)
                    painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y))
                    painter.drawText(QRect(plot_rect.right() + 5, int(y) - 6, plot_rect.right() - plot_rect.left() - 10, 12), Qt.AlignLeft | Qt.AlignVCenter, f"{freq}")

        # --- 在plot_rect内绘制所有叠加层 ---
        # 强度曲线
        if self._show_intensity and self._intensity_data is not None:
            painter.setPen(QPen(self._intensityColor, 2)); intensity_points = []
            data_to_plot = self._intensity_data
            if self._smooth_intensity:
                data_to_plot = pd.Series(data_to_plot).rolling(window=5, center=True, min_periods=1).mean().to_numpy()
            max_intensity = np.max(data_to_plot) if len(data_to_plot) > 0 else 1.0
            if max_intensity == 0: max_intensity = 1.0
            for i, val in enumerate(data_to_plot):
                sample_pos = i * self.hop_length
                if self._view_start_sample <= sample_pos < self._view_end_sample:
                    x = plot_rect.left() + (sample_pos - self._view_start_sample) * w / view_width_samples
                    y = plot_rect.bottom() - (val / max_intensity * h * 0.3) 
                    intensity_points.append(QPointF(x, y))
            if len(intensity_points) > 1: painter.drawPolyline(*intensity_points)

        # 基频曲线
        if self._show_f0 and self._f0_axis_enabled and f0_display_range > 0:
            if self._show_f0_derived and self._f0_derived_data:
                painter.setPen(QPen(self._f0DerivedColor, 1.5, Qt.DashLine)); derived_points = []
                derived_times, derived_f0 = self._f0_derived_data
                for i, t in enumerate(derived_times):
                    sample_pos = t * self.sr
                    if self._view_start_sample <= sample_pos < self._view_end_sample and np.isfinite(derived_f0[i]):
                        x = plot_rect.left() + (sample_pos - self._view_start_sample) * w / view_width_samples
                        y = plot_rect.bottom() - ((derived_f0[i] - self._f0_display_min) / f0_display_range * h)
                        derived_points.append(QPointF(x, y))
                if len(derived_points) > 1: painter.drawPolyline(*derived_points)
            if self._show_f0_points and self._f0_data:
                painter.setPen(Qt.NoPen); painter.setBrush(self._f0Color)
                raw_times, raw_f0 = self._f0_data
                for i, t in enumerate(raw_times):
                    sample_pos = t * self.sr
                    if self._view_start_sample <= sample_pos < self._view_end_sample and np.isfinite(raw_f0[i]):
                        x = plot_rect.left() + (sample_pos - self._view_start_sample) * w / view_width_samples
                        y = plot_rect.bottom() - ((raw_f0[i] - self._f0_display_min) / f0_display_range * h)
                        painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
        
        # 共振峰点
        if self._show_formants and self._formants_data:
            max_freq_y_axis = self.max_display_freq
            for sample_pos, formants in self._formants_data:
                if self._view_start_sample <= sample_pos < self._view_end_sample:
                    x = plot_rect.left() + (sample_pos - self._view_start_sample) * w / view_width_samples
                    for i, f in enumerate(formants):
                        brush, should_draw, is_highlighted = None, False, False
                        if i == 0 and self._highlight_f1:
                            brush, should_draw, is_highlighted = self._f1Color, True, True
                        elif i == 1 and self._highlight_f2:
                            brush, should_draw, is_highlighted = self._f2Color, True, True
                        elif i > 1 and self._show_other_formants:
                            brush, should_draw, is_highlighted = self._formantColor, True, False
                        
                        if should_draw:
                            y = plot_rect.bottom() - (f / max_freq_y_axis * h)
                            if plot_rect.top() <= y <= plot_rect.bottom():
                                if is_highlighted:
                                    painter.setPen(QPen(Qt.red, 1)); painter.setBrush(Qt.NoBrush)
                                    painter.drawEllipse(QPointF(x, y), 3, 3)
                                painter.setPen(Qt.NoPen); painter.setBrush(brush)
                                painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
        
        # 播放光标
        if self._view_start_sample <= self._playback_pos_sample < self._view_end_sample:
            pos_x = plot_rect.left() + (self._playback_pos_sample - self._view_start_sample) * w / view_width_samples
            painter.setPen(QPen(self._cursorColor, 2)); painter.drawLine(int(pos_x), 0, int(pos_x), self.height())

        # --- 新增: 绘制选区 ---
        selection_rect = QRect()
        if self._is_selecting and self._selection_start_pos and self._selection_end_pos:
            # 在拖动时，使用原始像素位置绘制
            selection_rect = QRect(self._selection_start_pos, self._selection_end_pos).normalized()
        elif self._selection_start_sample is not None and self._selection_end_sample is not None:
            # 在静态显示时，将采样点位置转换回像素位置
            start_x = self._sample_to_pixel(self._selection_start_sample)
            end_x = self._sample_to_pixel(self._selection_end_sample)
            selection_rect = QRect(start_x, plot_rect.top(), end_x - start_x, plot_rect.height()).normalized()
        
        if not selection_rect.isEmpty():
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._selection_color)
            # 将矩形限制在绘图区域内
            painter.drawRect(selection_rect.intersected(plot_rect))


        # --- 悬浮信息框的绘制保持不变 ---
        if self._cursor_info_text:
            font = self.font(); font.setPointSize(10); painter.setFont(font); metrics = painter.fontMetrics()
            
            # 先计算文本矩形的大小
            text_rect = metrics.boundingRect(QRect(0, 0, self.width(), self.height()), Qt.AlignLeft, self._cursor_info_text)
            text_rect.adjust(-5, -5, 5, 5) # 添加内边距

            # 根据状态决定绘制位置
            margin = 10
            if self._info_box_position == 'top_left':
                text_rect.moveTo(margin, margin)
            else: # 'bottom_right'
                text_rect.moveTo(self.width() - text_rect.width() - margin, 
                                 self.height() - text_rect.height() - margin)

            painter.setBrush(self._infoBackgroundColor)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(text_rect, 5, 5)
            
            painter.setPen(self._infoTextColor)
            painter.drawText(text_rect, Qt.AlignCenter, self._cursor_info_text)

    # --- 新增: 鼠标事件处理 ---
    def mousePressEvent(self, event):
        if self.spectrogram_image is None:
            return
        
        # 只响应绘图区域内的点击
        plot_rect = self._get_plot_rect()
        if not plot_rect.contains(event.pos()):
            return

        if event.button() == Qt.LeftButton:
            self._is_selecting = True
            self._selection_start_pos = event.pos()
            self._selection_end_pos = event.pos()
            # 清除旧的采样点选区，并通知上层
            if self._selection_start_sample is not None:
                self._selection_start_sample = None
                self._selection_end_sample = None
                self.selectionChanged.emit(None)
            self.update()
        
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_selecting:
            self._selection_end_pos = event.pos()
            self.update()
        
        # 原有的悬停信息逻辑保持不变
        if self.spectrogram_image is None: super().mouseMoveEvent(event); return
        plot_rect = self._get_plot_rect()
        w, h = self.width(), self.height() # 使用总宽高计算比例
        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0: super().mouseMoveEvent(event); return

        # 将鼠标位置的坐标转换为数据坐标
        x_ratio = (event.x() - plot_rect.left()) / plot_rect.width()
        y_ratio = (plot_rect.bottom() - event.y()) / plot_rect.height()
        x_ratio = max(0, min(1, x_ratio)) # 限制在0-1之间
        y_ratio = max(0, min(1, y_ratio)) # 限制在0-1之间
        
        current_sample = self._view_start_sample + x_ratio * view_width_samples
        current_time_s = current_sample / self.sr
        current_freq_hz = y_ratio * self.max_display_freq

        info_parts = [f"Time: {current_time_s:.3f} s", f"Freq: {current_freq_hz:.0f} Hz"]
        if self._show_f0 and self._f0_data and self._show_f0_points:
            times, f0_values = self._f0_data
            if len(times) > 0:
                time_diffs = np.abs(times - current_time_s); closest_idx = np.argmin(time_diffs)
                if time_diffs[closest_idx] < (self.hop_length / self.sr) and np.isfinite(f0_values[closest_idx]): info_parts.append(f"F0: {f0_values[closest_idx]:.1f} Hz")
        if self._show_formants and self._formants_data:
            closest_formant_dist, closest_formants = float('inf'), None
            for sample_pos, formants in self._formants_data:
                dist = abs(sample_pos - current_sample)
                if dist < closest_formant_dist: closest_formant_dist, closest_formants = dist, formants
            if closest_formants and closest_formant_dist < (self.hop_length * 3): info_parts.append(" | ".join([f"F{i+1}: {int(f)}" for i, f in enumerate(closest_formants)]))
        self._cursor_info_text = "\n".join(info_parts);
                # --- 新增: 动态调整信息框位置的逻辑 ---
        if self._cursor_info_text:
            metrics = self.fontMetrics()
            # 计算左上角的位置
            top_left_rect = metrics.boundingRect(QRect(0, 0, self.width(), self.height()), Qt.AlignLeft, self._cursor_info_text).adjusted(-5, -5, 5, 5)
            top_left_rect.moveTo(10, 10)

            if top_left_rect.contains(event.pos()):
                self._info_box_position = 'bottom_right'
            else:
                # 仅当鼠标也不在右下角区域时，才恢复到左上角
                bottom_right_rect = top_left_rect.translated(
                    self.width() - top_left_rect.width() - 20,
                    self.height() - top_left_rect.height() - 20
                )
                if not bottom_right_rect.contains(event.pos()):
                    self._info_box_position = 'top_left'

        self.update() # 触发重绘
        super().mouseMoveEvent(event)


    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._is_selecting:
            self._is_selecting = False
            
            # 检查是否只是单击 (拖动距离很小)
            if (self._selection_end_pos - self._selection_start_pos).manhattanLength() < 5:
                # 单击，清除选区
                self._selection_start_pos = None
                self._selection_end_pos = None
                self._selection_start_sample = None
                self._selection_end_sample = None
                self.selectionChanged.emit(None)
            else:
                # 拖动结束，计算并保存最终的采样点选区
                start_sample = self._pixel_to_sample(self._selection_start_pos.x())
                end_sample = self._pixel_to_sample(self._selection_end_pos.x())
                
                # 保证start < end
                self._selection_start_sample = min(start_sample, end_sample)
                self._selection_end_sample = max(start_sample, end_sample)
                
                # 发射信号，通知控制器选区已确定
                self.selectionChanged.emit((self._selection_start_sample, self._selection_end_sample))
            
            self.update()
        super().mouseReleaseEvent(event)
    
    def create_context_menu(self):
        """
        创建一个包含所有内置动作和潜在插件动作的右键菜单。
        此方法通过检查预定义的钩子属性来动态添加插件功能。
        """
        menu = QMenu(self)
        has_selection = self._selection_start_sample is not None and self._selection_end_sample is not None
        has_analysis = self._f0_data is not None or self._intensity_data is not None or self._formants_data

        info_to_copy = self._cursor_info_text
        
        click_pos = self.mapFromGlobal(QCursor.pos())
        sample_pos_at_click = self._pixel_to_sample(click_pos.x())

        # ==========================================================
        # 第一部分：添加所有原生菜单项
        # ==========================================================

        # 1. "分析" 子菜单
        analysis_menu = QMenu("分析", self)
        analysis_menu.setIcon(self.icon_manager.get_icon("analyze"))
        
        slice_action = QAction(self.icon_manager.get_icon("spectrum"), "获取此处频谱切片...", self)
        slice_action.triggered.connect(lambda: self.spectrumSliceRequested.emit(sample_pos_at_click))
        analysis_menu.addAction(slice_action)
        
        menu.addMenu(analysis_menu)
        menu.addSeparator()

        # 2. 选区相关操作
        if has_selection:
            zoom_icon = self.icon_manager.get_icon("zoom_selection") 
            if zoom_icon.isNull(): zoom_icon = self.icon_manager.get_icon("zoom")
            zoom_to_selection_action = QAction(zoom_icon, "伸展选区到视图", self)
            zoom_to_selection_action.triggered.connect(lambda: self.zoomToSelectionRequested.emit(self._selection_start_sample, self._selection_end_sample))
            menu.addAction(zoom_to_selection_action)

        # 3. 复制信息
        copy_action = QAction(self.icon_manager.get_icon("copy"), "复制光标处信息", self)
        copy_action.setEnabled(bool(info_to_copy.strip()))
        copy_action.triggered.connect(lambda checked, text=info_to_copy: QApplication.clipboard().setText(text))
        menu.addAction(copy_action)
        
        # 4. "导出" 子菜单 (原生导出功能)
        export_menu = QMenu("导出", self)
        export_menu.setIcon(self.icon_manager.get_icon("export"))
        
        export_image_action = QAction(self.icon_manager.get_icon("image"), "将当前视图保存为图片...", self)
        export_image_action.triggered.connect(self.exportViewAsImageRequested.emit)
        export_menu.addAction(export_image_action)

        csv_icon = self.icon_manager.get_icon("csv")
        if csv_icon.isNull(): csv_icon = self.icon_manager.get_icon("document")
        export_csv_action = QAction(csv_icon, "将选区内分析数据导出为CSV...", self)
        export_csv_action.setEnabled(has_selection and has_analysis)
        export_csv_action.setToolTip("需要存在选区和已运行的分析数据。")
        export_csv_action.triggered.connect(self.exportAnalysisToCsvRequested.emit)
        export_menu.addAction(export_csv_action)
        
        wav_icon = self.icon_manager.get_icon("audio")
        if wav_icon.isNull(): wav_icon = self.icon_manager.get_icon("save")
        export_wav_action = QAction(wav_icon, "将选区音频导出为WAV...", self)
        export_wav_action.setEnabled(has_selection)
        export_wav_action.setToolTip("需要存在一个有效的选区。")
        export_wav_action.triggered.connect(self.exportSelectionAsWavRequested.emit)
        export_menu.addAction(export_wav_action)

        menu.addMenu(export_menu)
        
        # ==========================================================
        # 第二部分：在末尾添加由插件注入的菜单项
        # ==========================================================
        
        # 检查是否有任何插件被注入
        plotter_plugin = getattr(self, 'vowel_plotter_plugin_active', None)
        exporter_plugin = getattr(self, 'praat_exporter_plugin_active', None)
        
        # 如果至少有一个插件被注入，则添加一个主分隔符
        if plotter_plugin or exporter_plugin:
            menu.addSeparator()

        # 钩子检查点: Praat 导出器插件
        if exporter_plugin:
            # 从插件实例动态创建菜单动作
            exporter_action = exporter_plugin.create_action_for_menu(self)
            menu.addAction(exporter_action)
        
        # 钩子检查点: 元音空间图绘制器插件
        if plotter_plugin:
            # 创建菜单动作
            plotter_action = QAction(self.icon_manager.get_icon("chart"), "发送数据到元音绘制器...", self)
            
            # 检查动作的可用性
            has_formants_in_selection = False
            if has_selection:
                start_sample, end_sample = self._selection_start_sample, self._selection_end_sample
                has_formants_in_selection = any(start_sample <= point[0] < end_sample for point in self._formants_data)
            
            plotter_action.setEnabled(has_formants_in_selection)
            if not has_formants_in_selection:
                plotter_action.setToolTip("请先在选区内运行共振峰分析。")

            # 连接信号
            plotter_action.triggered.connect(self._send_data_to_plotter)
            
            # 将动作添加到菜单的末尾
            menu.addAction(plotter_action)
        
        # 返回最终构建好的菜单
        return menu

    # --- [新增] _send_data_to_plotter 辅助方法 ---
    def _send_data_to_plotter(self):
        """收集选区内的共振峰数据，并通过钩子调用插件的execute方法。"""
        if not self.vowel_plotter_plugin_active:
            return
        
        start_sample, end_sample = self._selection_start_sample, self._selection_end_sample
        
        # 1. 筛选出选区内的数据点
        data_points = []
        for sample_pos, formants in self._formants_data:
            if start_sample <= sample_pos < end_sample:
                # 只取前两个共振峰 F1, F2
                if len(formants) >= 2:
                    # --- [核心修改] 把时间戳也加进去 ---
                    timestamp = sample_pos / self.sr
                    data_points.append({'timestamp': timestamp, 'F1': formants[0], 'F2': formants[1]})
        
        if not data_points:
            QMessageBox.warning(self, "无数据", "在选区内未找到有效的 F1/F2 数据点。")
            return
            
        # 2. 转换为 Pandas DataFrame
        import pandas as pd
        df = pd.DataFrame(data_points)
        
        # 3. 通过插件实例的 execute 方法传递数据
        self.vowel_plotter_plugin_active.execute(dataframe=df)

    # --- [修改] 精简后的原始方法 ---
    def contextMenuEvent(self, event):
        """
        默认的右键菜单事件处理器。
        现在它只负责创建并显示菜单。
        """
        menu = self.create_context_menu()
        if not menu.isEmpty():
            menu.exec_(self.mapToGlobal(event.pos()))

    # --- 其他方法保持不变 ---
    def set_data(self, S_db, sr, hop_length):
        self.sr, self.hop_length = sr, hop_length; S_norm = (S_db - S_db.min()) / (S_db.max() - S_db.min() + 1e-6); h, w = S_norm.shape; rgba_data = np.zeros((h, w, 4), dtype=np.uint8)
        min_color_obj, max_color_obj = QColor(self._spectrogramMinColor), QColor(self._spectrogramMaxColor); min_c, max_c = np.array(min_color_obj.getRgb()), np.array(max_color_obj.getRgb())
        interpolated_colors = min_c + (max_c - min_c) * (S_norm[..., np.newaxis]); rgba_data[..., :4] = interpolated_colors.astype(np.uint8); image_data = np.flipud(rgba_data)
        self.spectrogram_image = QImage(image_data.tobytes(), w, h, QImage.Format_RGBA8888).copy(); self.update()
    def set_waveform_sibling(self, widget): self.waveform_sibling = widget
    def wheelEvent(self, event):
        if self.waveform_sibling: self.waveform_sibling.wheelEvent(event)
        else: super().wheelEvent(event)
    def leaveEvent(self, event):
        if self._cursor_info_text:
            self._cursor_info_text = ""
            self._info_box_position = 'top_left' # --- 新增: 重置位置 ---
            self.update()
        super().leaveEvent(event)
    def set_analysis_data(self, f0_data=None, f0_derived_data=None, intensity_data=None, formants_data=None, clear_previous_formants=True):
        if f0_data is not None:
            self._f0_data = f0_data; times, f0_values = f0_data; valid_f0 = f0_values[np.isfinite(f0_values)]
            if len(valid_f0) > 1:
                default_min, default_max = 50, 500; actual_min, actual_max = np.min(valid_f0), np.max(valid_f0)
                self._f0_display_min, self._f0_display_max = min(default_min, actual_min - 20), max(default_max, actual_max + 20); self._f0_axis_enabled = True
            else: self._f0_display_min, self._f0_display_max = 50, 500; self._f0_axis_enabled = False
        if f0_derived_data is not None: self._f0_derived_data = f0_derived_data
        if intensity_data is not None: self._intensity_data = intensity_data
        if formants_data is not None:
            if clear_previous_formants: self._formants_data = formants_data
            else: self._formants_data.extend(formants_data)
        self.update()
    def update_playback_position(self, position_ms):
        if self.sr > 1: self._playback_pos_sample = int(position_ms / 1000 * self.sr); self.update()
    def set_view_window(self, start_sample, end_sample): self._view_start_sample, self._view_end_sample = start_sample, end_sample; self.update()
    def clear(self):
        # 在原有clear逻辑上新增对选区状态的重置
        self._is_selecting = False
        self._selection_start_pos = None
        self._selection_end_pos = None
        self._selection_start_sample = None
        self._selection_end_sample = None
        
        # 原有逻辑
        self.spectrogram_image, self._f0_data, self._intensity_data = None, None, None
        self._formants_data = []
        self._playback_pos_sample = -1
        self._info_box_position = 'top_left' # --- 新增: 重置位置 ---
        self.update()

    def render_to_pixmap(self):
        """将当前控件的内容渲染到一个QPixmap上并返回。"""
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.transparent) # 使用透明背景，以便保存为PNG
        self.render(pixmap)
        return pixmap


# --- 波形控件 (无变化) ---
class WaveformWidget(QWidget):
    view_changed = pyqtSignal(int, int)
    @pyqtProperty(QColor)
    def waveformColor(self): return self._waveformColor
    @waveformColor.setter
    def waveformColor(self, color): self._waveformColor = color; self.update()
    @pyqtProperty(QColor)
    def cursorColor(self): return QColor("red")
    @cursorColor.setter
    def cursorColor(self, color): pass
    @pyqtProperty(QColor)
    def selectionColor(self): return QColor(0,0,0,0)
    @selectionColor.setter
    def selectionColor(self, color): pass
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._y_full, self._y_overview, self._sr = None, None, 1
        self._view_start_sample, self._view_end_sample = 0, 1
        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._backgroundColor = self.palette().color(QPalette.Base)
    def set_audio_data(self, y_full, sr, y_overview):
        self.clear()
        if y_full is not None and sr is not None:
            self._y_full, self._sr, self._y_overview = y_full, sr, y_overview
            self._view_start_sample, self._view_end_sample = 0, len(self._y_full)
        self.update(); self.view_changed.emit(self._view_start_sample, self._view_end_sample)
    def set_view_window(self, start_sample, end_sample):
        if self._y_full is None: return
        self._view_start_sample, self._view_end_sample = max(0, start_sample), min(len(self._y_full), end_sample)
        if self._view_end_sample <= self._view_start_sample: self._view_end_sample = self._view_start_sample + 1
        self.update()
    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and self._y_full is not None:
            anchor_ratio = event.x() / self.width(); view_width = self._view_end_sample - self._view_start_sample
            anchor_sample = self._view_start_sample + anchor_ratio * view_width
            zoom_factor = 1.25 if event.angleDelta().y() < 0 else 1 / 1.25
            new_width = view_width * zoom_factor
            if new_width < 50: new_width = 50 
            if new_width > len(self._y_full): new_width = len(self._y_full)
            new_start = anchor_sample - anchor_ratio * new_width; new_end = new_start + new_width
            if new_start < 0: new_start, new_end = 0, new_width
            if new_end > len(self._y_full): new_end = len(self._y_full); new_start = new_end - new_width
            self.set_view_window(int(new_start), int(new_end)); self.view_changed.emit(self._view_start_sample, self._view_end_sample)
        else: super().wheelEvent(event)
    def clear(self): self._y_full, self._y_overview = None, None; self.update(); self.view_changed.emit(0, 1)
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().color(QPalette.Base))
        if self._y_full is None: painter.setPen(self.palette().color(QPalette.Mid)); painter.drawText(self.rect(), Qt.AlignCenter, "波形"); return
        view_width_samples = self._view_end_sample - self._view_start_sample; w, h, half_h = self.width(), self.height(), self.height() / 2
        y_to_draw = self._y_overview if view_width_samples > w * 4 else self._y_full
        start_idx = int(self._view_start_sample / len(self._y_full) * len(y_to_draw)); end_idx = int(self._view_end_sample / len(self._y_full) * len(y_to_draw))
        view_y = y_to_draw[start_idx:end_idx]
        if len(view_y) == 0: return
        painter.setPen(QPen(self._waveformColor, 1))
        max_val = np.max(np.abs(view_y)) or 1.0
        points = [QPointF(i * w / len(view_y), half_h - (val / max_val * half_h * 0.95)) for i, val in enumerate(view_y)]
        if points: painter.drawPolyline(*points)


# --- 主页面 ---
def create_page(parent_window, icon_manager, ToggleSwitchClass):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"音频分析模块加载失败...\n请运行: pip install numpy soundfile librosa pandas\n错误: {MISSING_ERROR_MESSAGE}")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    return AudioAnalysisPage(parent_window, icon_manager, ToggleSwitchClass)

class AudioAnalysisPage(QWidget):
    DENSITY_LABELS = {1: "最快", 2: "较快", 3: "标准", 4: "精细", 5: "最高（速度慢）"}
    REQUIRES_ANALYSIS_HINT = '<b><font color="#e57373">注意：更改此项需要重新运行分析才能生效。</font></b>'

    def __init__(self, parent_window, icon_manager, ToggleSwitchClass):
        super().__init__()
        self.parent_window = parent_window
        self.icon_manager = icon_manager
        self.ToggleSwitch = ToggleSwitchClass
        self.setAcceptDrops(True)
        self.audio_data, self.sr, self.overview_data, self.current_filepath = None, None, None, None
        
        # --- 新增 ---
        self.current_selection = None # (start_sample, end_sample) or None
        self.is_playing_selection = False # 标记是否正在播放选区
        self.is_player_ready = False # [新增] 标志，用于检查播放器是否已预热
        self._pending_csv_path = None # 用于在加载音频后应用CSV数据
        self.player = QMediaPlayer(); self.player.setNotifyInterval(30)
        self.known_duration = 0
        self.task_thread, self.worker = None, None
        self.is_task_running = False
        self.recommended_density = 3
        self._init_ui()
        self._connect_signals()
        self.update_icons()
        self._update_dependent_widgets()
        self._load_persistent_settings()
        self.DENSITY_LABELS = {
            1: "最低 (极速)", 2: "很低", 3: "较低", 4: "标准", 5: "较高",
            6: "精细", 7: "很高", 8: "极高", 9: "最高 (极慢)"
        }

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        # 左侧面板：信息与动作
        self.info_panel = QWidget(); self.info_panel.setFixedWidth(300)
        info_layout = QVBoxLayout(self.info_panel)
        
        self.open_file_btn = QPushButton(" 从文件加载音频")
        self.open_file_btn.setToolTip("打开文件浏览器选择一个音频文件进行分析。")
        
        self.info_group = QGroupBox("音频信息")
        info_layout_form = QFormLayout(self.info_group)
        self.filename_label, self.duration_label, self.samplerate_label, self.channels_label, self.bitdepth_label = [QLabel("N/A") for _ in range(5)]
        self.filename_label.setWordWrap(True)
        info_layout_form.addRow("文件名:", self.filename_label); info_layout_form.addRow("时长:", self.duration_label); info_layout_form.addRow("采样率:", self.samplerate_label); info_layout_form.addRow("通道数:", self.channels_label); info_layout_form.addRow("位深度:", self.bitdepth_label)
        
        self.playback_group = QGroupBox("播放控制")
        playback_layout = QVBoxLayout(self.playback_group)
        self.play_pause_btn, self.playback_slider, self.time_label = QPushButton("播放"), QSlider(Qt.Horizontal), QLabel("00:00.00 / 00:00.00")
        self.play_pause_btn.setEnabled(False); self.playback_slider.setEnabled(False)
        playback_layout.addWidget(self.play_pause_btn); playback_layout.addWidget(self.playback_slider); playback_layout.addWidget(self.time_label)

        self.analysis_actions_group = QGroupBox("分析动作")
        actions_layout = QVBoxLayout(self.analysis_actions_group)
        self.analyze_button = QPushButton("运行完整分析")
        self.analyze_button.setToolTip("根据右侧面板的所有设置，对整个音频进行声学分析。")
        self.analyze_formants_button = QPushButton(" 分析共振峰")
        self.analyze_formants_button.setToolTip("仅对屏幕上可见区域进行共振峰分析，速度更快。\n此分析同样会应用右侧“高级分析参数”中的设置。")
        actions_layout.addWidget(self.analyze_button)
        actions_layout.addWidget(self.analyze_formants_button)
        self.analysis_actions_group.setEnabled(False)

        info_layout.addWidget(self.open_file_btn)
        info_layout.addWidget(self.info_group)
        info_layout.addWidget(self.playback_group)
        info_layout.addWidget(self.analysis_actions_group)
        info_layout.addStretch()

        # 中心可视化区域 (修改)
        self.center_panel = QWidget()
        center_layout = QVBoxLayout(self.center_panel)
        center_layout.setSpacing(0)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.waveform_widget = WaveformWidget()
        self.waveform_widget.setToolTip("音频波形概览。\n使用 Ctrl+鼠标滚轮 进行水平缩放。")

        # --- 新增 ---
        self.time_axis_widget = TimeAxisWidget()
        self.time_axis_widget.hide() # 默认隐藏

        # --- 修改 SpectrogramWidget 的实例化 ---
        self.spectrogram_widget = SpectrogramWidget(self, self.icon_manager)
        self.spectrogram_widget.setToolTip("音频语谱图。\n悬停查看信息，滚动缩放，左键拖动选择区域。")
        
        self.spectrogram_widget.set_waveform_sibling(self.waveform_widget)
        self.h_scrollbar = QScrollBar(Qt.Horizontal)
        self.h_scrollbar.setToolTip("在放大的视图中水平导航（平移）。")
        self.h_scrollbar.setEnabled(False)
        
        # --- 修改布局顺序 ---
        center_layout.addWidget(self.waveform_widget, 1)
        center_layout.addWidget(self.time_axis_widget) # 添加到中间
        center_layout.addWidget(self.spectrogram_widget, 2)
        center_layout.addWidget(self.h_scrollbar)

        # 右侧面板：设置
        self.settings_panel = QWidget(); self.settings_panel.setFixedWidth(300)
        settings_layout = QVBoxLayout(self.settings_panel)

        self.visualization_group = QGroupBox("可视化选项")
        vis_layout = QFormLayout(self.visualization_group)
        self.visualization_group.setToolTip("控制在语谱图上叠加显示哪些声学特征。\n这些选项的更改会<b>立即生效</b>，无需重新分析。")
        
        self.show_f0_toggle = self.ToggleSwitch()
        self.show_f0_toggle.setToolTip("总开关：是否显示任何与<b>基频（F0）</b>相关的信息。<br>基频是声带振动的频率，人耳感知为音高。")
        self.show_f0_points_checkbox = QCheckBox("显示原始点")
        self.show_f0_points_checkbox.setToolTip("显示算法直接计算出的离散基频点（橙色点）。")
        self.show_f0_derived_checkbox = QCheckBox("显示派生曲线")
        self.show_f0_derived_checkbox.setToolTip("显示通过对原始点进行线性插值后得到的连续基频曲线（蓝色虚线）。")
        f0_sub_layout = QVBoxLayout(); f0_sub_layout.setSpacing(2); f0_sub_layout.setContentsMargins(15, 0, 0, 0)
        f0_sub_layout.addWidget(self.show_f0_points_checkbox); f0_sub_layout.addWidget(self.show_f0_derived_checkbox)
        vis_layout.addRow("显示基频 (F0)", self.show_f0_toggle)
        vis_layout.addRow(f0_sub_layout)
        
        self.show_intensity_toggle = self.ToggleSwitch()
        self.show_intensity_toggle.setToolTip("总开关：是否显示音频的<b>强度</b>曲线。<br>强度是声波的振幅，人耳感知为响度。")
        self.smooth_intensity_checkbox = QCheckBox("平滑处理")
        self.smooth_intensity_checkbox.setToolTip("对强度曲线进行移动平均平滑（窗口=5），以观察其总体趋势，滤除微小波动。")
        intensity_sub_layout = QVBoxLayout(); intensity_sub_layout.setSpacing(2); intensity_sub_layout.setContentsMargins(15, 0, 0, 0)
        intensity_sub_layout.addWidget(self.smooth_intensity_checkbox)
        vis_layout.addRow("显示强度", self.show_intensity_toggle)
        vis_layout.addRow(intensity_sub_layout)

        self.show_formants_toggle = self.ToggleSwitch()
        self.show_formants_toggle.setToolTip("总开关：是否显示<b>共振峰</b>。<br>共振峰是声道（口腔、鼻腔）的共鸣频率，它决定了元音的音色，如[a],[i],[u]的区别。")
        self.highlight_f1_checkbox = QCheckBox("突出显示 F1")
        self.highlight_f1_checkbox.setToolTip("使用醒目的橙色并加描边来显示<b>第一共振峰（F1）</b>。<br>F1与元音的【开口度】（舌位高低）密切相关。")
        self.highlight_f2_checkbox = QCheckBox("突出显示 F2")
        self.highlight_f2_checkbox.setToolTip("使用醒目的紫色并加描边来显示<b>第二共振峰（F2）</b>。<br>F2与元音的【前后】（舌位前后）密切相关。")
        self.show_other_formants_checkbox = QCheckBox("显示其他共振峰")
        self.show_other_formants_checkbox.setToolTip("显示除F1/F2以外的其他共振峰（F3, F4...），通常为蓝色。")
        formant_sub_layout = QVBoxLayout(); formant_sub_layout.setSpacing(2); formant_sub_layout.setContentsMargins(15, 0, 0, 0)
        formant_sub_layout.addWidget(self.highlight_f1_checkbox); formant_sub_layout.addWidget(self.highlight_f2_checkbox); formant_sub_layout.addWidget(self.show_other_formants_checkbox)
        vis_layout.addRow("显示共振峰", self.show_formants_toggle)
        vis_layout.addRow(formant_sub_layout)

        self.advanced_params_group = QGroupBox("高级分析参数")
        adv_layout = QFormLayout(self.advanced_params_group)
        self.advanced_params_group.setToolTip(f"调整声学分析算法的核心参数，会直接影响计算结果的准确性。<br>{self.REQUIRES_ANALYSIS_HINT}")
        self.pre_emphasis_checkbox = QCheckBox("应用预加重")
        self.pre_emphasis_checkbox.setToolTip(f"在分析前通过一个高通滤波器提升高频部分的能量。<br>这对于在高频区域寻找共振峰（尤其是女声和童声）非常有帮助。<br>{self.REQUIRES_ANALYSIS_HINT}")
        f0_range_layout = QHBoxLayout()
        self.f0_min_input = QLineEdit("75"); self.f0_min_input.setValidator(QIntValidator(10, 2000))
        self.f0_max_input = QLineEdit("500"); self.f0_max_input.setValidator(QIntValidator(50, 5000))
        f0_range_layout.addWidget(self.f0_min_input); f0_range_layout.addWidget(QLabel(" - ")); f0_range_layout.addWidget(self.f0_max_input); f0_range_layout.addWidget(QLabel("Hz"))
        f0_range_row_widget = QWidget(); f0_range_row_widget.setLayout(f0_range_layout)
        f0_range_row_widget.setToolTip(f"设置基频（F0）搜索的频率范围（单位：Hz）。<br>根据说话人类型设置合适的范围能极大提高F0提取的准确率。<br><li>典型男声: 75-300 Hz</li><li>典型女声: 100-500 Hz</li><li>典型童声: 150-600 Hz</li><br>{self.REQUIRES_ANALYSIS_HINT}")
        adv_layout.addRow(self.pre_emphasis_checkbox)
        adv_layout.addRow("F0 范围:", f0_range_row_widget)
        
        self.spectrogram_settings_group = QGroupBox("语谱图设置")
        spec_settings_layout = QFormLayout(self.spectrogram_settings_group)
        self.spectrogram_settings_group.setToolTip(f"调整语谱图本身的生成方式，影响其外观和分辨率。<br>{self.REQUIRES_ANALYSIS_HINT}")
        self.density_slider = QSlider(Qt.Horizontal); self.density_slider.setRange(1, 9); self.density_slider.setValue(4)
        self.density_slider.setToolTip(f"调整语谱图分析帧的重叠率，决定了图像在时间轴上的平滑度。<br>值越高，图像越精细平滑，但计算也越慢。<br>{self.REQUIRES_ANALYSIS_HINT}")
        self.density_label = QLabel()
        self._update_density_label(4)
        self.accept_recommendation_btn = QPushButton("建议")
        self.accept_recommendation_btn.setToolTip("根据您的设备性能和当前音频长度，自动设置一个最佳的精细度等级。")
        self.accept_recommendation_btn.setVisible(False)
        self.accept_recommendation_btn.setMinimumWidth(120)
        self.spectrogram_type_checkbox = QCheckBox("宽带模式")
        self.spectrogram_type_checkbox.setToolTip(f"切换语谱图的分析窗长，决定了时间和频率分辨率的取舍。<br><li><b>宽带 (勾选)</b>: 短窗，时间分辨率高，能清晰看到声门的每一次振动（垂直线），但频率分辨率低。</li><li><b>窄带 (不勾选)</b>: 长窗，频率分辨率高，能清晰看到基频的各次谐波（水平线），但时间分辨率低。</li><br>{self.REQUIRES_ANALYSIS_HINT}")
        spec_settings_layout.addRow("精细度:", self.density_slider)
        spec_settings_layout.addRow("", self.density_label)
        spec_settings_layout.addRow("", self.accept_recommendation_btn)
        spec_settings_layout.addRow(self.spectrogram_type_checkbox)
        
        settings_layout.addWidget(self.visualization_group)
        settings_layout.addWidget(self.advanced_params_group)
        settings_layout.addWidget(self.spectrogram_settings_group)
        settings_layout.addStretch()

        main_layout.addWidget(self.info_panel)
        main_layout.addWidget(self.center_panel, 1)
        main_layout.addWidget(self.settings_panel)

    def _connect_signals(self):
        self.open_file_btn.clicked.connect(self.open_file_dialog)
        self.play_pause_btn.clicked.connect(self.toggle_playback)
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.player.stateChanged.connect(self.on_player_state_changed)
        self.playback_slider.sliderMoved.connect(self.player.setPosition)
        self.waveform_widget.view_changed.connect(self.on_view_changed)
        self.h_scrollbar.valueChanged.connect(self.on_scrollbar_moved)
        self.density_slider.valueChanged.connect(self._update_density_label)
        self.analyze_button.clicked.connect(self.run_full_analysis)
        self.analyze_formants_button.clicked.connect(self.run_view_formant_analysis)

        # --- 新增 ---
        self.spectrogram_widget.selectionChanged.connect(self.on_selection_changed)
        self.spectrogram_widget.zoomToSelectionRequested.connect(self.zoom_to_selection)
        self.spectrogram_widget.exportViewAsImageRequested.connect(self.handle_export_image)
        self.spectrogram_widget.exportAnalysisToCsvRequested.connect(self.handle_export_csv)
        self.spectrogram_widget.exportSelectionAsWavRequested.connect(self.handle_export_wav)
        self.spectrogram_widget.spectrumSliceRequested.connect(self.handle_spectrum_slice_request)
        all_toggles = [self.show_f0_toggle, self.show_intensity_toggle, self.show_formants_toggle]
        for toggle in all_toggles:
            toggle.stateChanged.connect(self._update_dependent_widgets)
            toggle.stateChanged.connect(self.update_overlays)
        self.accept_recommendation_btn.clicked.connect(self.apply_recommended_density)

        all_checkboxes = [self.show_f0_points_checkbox, self.show_f0_derived_checkbox,
                          self.smooth_intensity_checkbox, self.highlight_f1_checkbox,
                          self.highlight_f2_checkbox, self.show_other_formants_checkbox]
        for cb in all_checkboxes:
            cb.stateChanged.connect(self.update_overlays)
# --- [新增] 连接所有持久化设置的信号 ---
        
        # 可视化选项
        self.show_f0_toggle.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_f0', bool(s)))
        self.show_f0_points_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_f0_points', bool(s)))
        self.show_f0_derived_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_f0_derived', bool(s)))
        self.show_intensity_toggle.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_intensity', bool(s)))
        self.smooth_intensity_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('smooth_intensity', bool(s)))
        self.show_formants_toggle.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_formants', bool(s)))
        self.highlight_f1_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('highlight_f1', bool(s)))
        self.highlight_f2_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('highlight_f2', bool(s)))
        self.show_other_formants_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_other_formants', bool(s)))

        # 高级分析参数
        self.pre_emphasis_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('pre_emphasis', bool(s)))
        self.f0_min_input.textChanged.connect(lambda t: self._on_persistent_setting_changed('f0_min', t))
        self.f0_max_input.textChanged.connect(lambda t: self._on_persistent_setting_changed('f0_max', t))
        
        # 语谱图设置
        self.density_slider.valueChanged.connect(lambda v: self._on_persistent_setting_changed('density', v))
        self.spectrogram_type_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('is_wide_band', bool(s)))


    def handle_spectrum_slice_request(self, sample_pos):
        """处理频谱切片请求，计算FFT并显示对话框。"""
        if self.audio_data is None: return

        try:
            # 1. 定义FFT参数
            n_fft = 2048
            
            # 2. 获取以sample_pos为中心的音频帧
            start = max(0, sample_pos - n_fft // 2)
            end = min(len(self.audio_data), start + n_fft)
            frame = self.audio_data[start:end]
            
            # 如果帧太短，则补零
            if len(frame) < n_fft:
                frame = np.pad(frame, (0, n_fft - len(frame)), 'constant')

            # 3. 应用汉明窗
            window = np.hanning(n_fft)
            windowed_frame = frame * window

            # 4. 计算FFT和频率轴
            mags = np.abs(np.fft.rfft(windowed_frame))
            freqs = np.fft.rfftfreq(n_fft, d=1.0/self.sr)

            # 5. 转换为dB
            # 避免 log(0)
            mags_db = 20 * np.log10(mags + 1e-9)

            # 6. 显示对话框
            time_s = sample_pos / self.sr
            dialog = SpectrumSliceDialog(freqs, mags_db, time_s, self.sr, self)
            dialog.exec_()
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "频谱分析失败", f"计算频谱切片时发生错误: {e}")

    def _update_dependent_widgets(self):
        is_f0_on = self.show_f0_toggle.isChecked()
        self.show_f0_points_checkbox.setEnabled(is_f0_on); self.show_f0_derived_checkbox.setEnabled(is_f0_on)
        if not is_f0_on: self.show_f0_points_checkbox.setChecked(False); self.show_f0_derived_checkbox.setChecked(False)
        is_intensity_on = self.show_intensity_toggle.isChecked()
        self.smooth_intensity_checkbox.setEnabled(is_intensity_on)
        if not is_intensity_on: self.smooth_intensity_checkbox.setChecked(False)
        is_formants_on = self.show_formants_toggle.isChecked()
        self.highlight_f1_checkbox.setEnabled(is_formants_on); self.highlight_f2_checkbox.setEnabled(is_formants_on); self.show_other_formants_checkbox.setEnabled(is_formants_on)
        if not is_formants_on: self.highlight_f1_checkbox.setChecked(False); self.highlight_f2_checkbox.setChecked(False); self.show_other_formants_checkbox.setChecked(False)

    def update_overlays(self):
        self.spectrogram_widget.set_overlay_visibility(
            show_f0=self.show_f0_toggle.isChecked(),
            show_f0_points=self.show_f0_points_checkbox.isChecked(),
            show_f0_derived=self.show_f0_derived_checkbox.isChecked(),
            show_intensity=self.show_intensity_toggle.isChecked(),
            smooth_intensity=self.smooth_intensity_checkbox.isChecked(),
            show_formants=self.show_formants_toggle.isChecked(),
            highlight_f1=self.highlight_f1_checkbox.isChecked(),
            highlight_f2=self.highlight_f2_checkbox.isChecked(),
            show_other_formants=self.show_other_formants_checkbox.isChecked()
        )
    
    # --- 新增槽函数 ---
    def on_selection_changed(self, selection):
        """当语谱图上的选区改变时被调用。"""
        self.current_selection = selection
        if self.is_playing_selection and selection is None:
            # 如果正在播放选区时选区被清除了，则停止播放
            self.player.stop()
            self.is_playing_selection = False
            self.is_player_ready = False # [新增] 重置预热标志
    def zoom_to_selection(self, start_sample, end_sample):
        """将视图缩放到给定的采样点范围。"""
        if self.audio_data is None:
            return
        # 确保范围有效
        if end_sample <= start_sample:
            end_sample = start_sample + 1
            
        self.waveform_widget.set_view_window(start_sample, end_sample)
        self.on_view_changed(start_sample, end_sample)

    # --- 修改 on_view_changed ---
    def on_view_changed(self, start_sample, end_sample):
        if self.audio_data is None:
            self.h_scrollbar.setEnabled(False)
            self.time_axis_widget.hide() # 确保隐藏
            return

        total_samples = len(self.audio_data)
        view_width = end_sample - start_sample

        # 更新滚动条
        self.h_scrollbar.setRange(0, total_samples - view_width)
        self.h_scrollbar.setPageStep(view_width)
        self.h_scrollbar.setValue(start_sample)
        self.h_scrollbar.setEnabled(total_samples > view_width)
        
        # 同步语谱图视图
        self.spectrogram_widget.set_view_window(start_sample, end_sample)
        
        # --- 新增: 控制和更新时间轴 ---
        # 如果视图宽度和总宽度几乎一样（允许1个采样点的误差），则认为是全览
        if abs(view_width - total_samples) < 2:
            self.time_axis_widget.hide()
        else:
            self.time_axis_widget.update_view(start_sample, end_sample, self.sr)
            self.time_axis_widget.show()

    # --- 修改 update_position ---
    def update_position(self, position):
        # --- 新增: 检查是否超出选区播放范围 ---
        if self.is_playing_selection and self.current_selection:
            selection_end_ms = (self.current_selection[1] / self.sr) * 1000
            if position >= selection_end_ms:
                self.player.stop()
                # 停止后将滑块和光标设回选区起点
                selection_start_ms = (self.current_selection[0] / self.sr) * 1000
                self.player.setPosition(int(selection_start_ms))
                self.playback_slider.setValue(int(selection_start_ms))
                self.spectrogram_widget.update_playback_position(selection_start_ms)
                return # 提前返回，避免下面的常规更新

        if not self.playback_slider.isSliderDown():
            self.playback_slider.setValue(position)
        
        self.time_label.setText(f"{self.format_time(position)} / {self.format_time(self.known_duration)}")
        self.spectrogram_widget.update_playback_position(position)

    # --- 修改 toggle_playback ---
    def toggle_playback(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
            # self.is_playing_selection = False # pause should not reset this flag
        else:
            # --- 新增: 检查是否有选区 ---
            if self.current_selection and self.player.state() != QMediaPlayer.PausedState:
                start_sample, end_sample = self.current_selection
                start_ms = (start_sample / self.sr) * 1000
                
                self.is_playing_selection = True
                self.player.setPosition(int(start_ms))
                self.player.play()
            else:
                # 原有逻辑：从当前位置播放或恢复播放
                self.is_playing_selection = False
                self.player.play()

    # --- 修改 on_player_state_changed ---
    def on_player_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.play_pause_btn.setIcon(self.icon_manager.get_icon("pause"))
            self.play_pause_btn.setText("暂停")
        else:
            self.play_pause_btn.setIcon(self.icon_manager.get_icon("play"))
            self.play_pause_btn.setText("播放")
            # --- 新增: 播放结束后清除标记 ---
            self.is_playing_selection = False

    # --- 修改 clear_all ---
    def clear_all(self):
        if hasattr(self, 'progress_dialog') and self.progress_dialog and self.progress_dialog.isVisible(): self.progress_dialog.close()
        self.progress_dialog = None
        if self.player.state() != QMediaPlayer.StoppedState: self.player.stop()
        self.waveform_widget.clear()
        self.spectrogram_widget.clear() # 这个clear方法已经被我们修改过了，会清除选区
        for label in [self.filename_label, self.duration_label, self.samplerate_label, self.channels_label, self.bitdepth_label]: label.setText("N/A")
        self.time_label.setText("00:00.00 / 00:00.00"); self.play_pause_btn.setEnabled(False); self.playback_slider.setEnabled(False); self.analysis_actions_group.setEnabled(False)
        self.density_slider.setValue(4)
        self.known_duration = 0
        self.audio_data, self.sr, self.overview_data, self.current_filepath = None, None, None, None
        
        # --- 新增: 确保重置选区状态 ---
        self.current_selection = None
        self.is_playing_selection = False
        self.time_axis_widget.hide() # 确保时间轴隐藏
        self.accept_recommendation_btn.setVisible(False)


    # --- 其他所有方法保持不变 ---
    def _update_density_label(self, value): self.density_label.setText(f"{self.DENSITY_LABELS.get(value, '未知')}")
    def on_load_finished(self, result):
        if self.progress_dialog: self.progress_dialog.close()
        self.audio_data, self.sr, self.overview_data = result['y_full'], result['sr'], result['y_overview']
        info = sf.info(self.current_filepath); self.filename_label.setText(os.path.basename(self.current_filepath)); self.known_duration = info.duration * 1000; self.duration_label.setText(self.format_time(self.known_duration)); self.time_label.setText(f"00:00.00 / {self.format_time(self.known_duration)}"); self.samplerate_label.setText(f"{info.samplerate} Hz")
        channel_desc = {1: "Mono", 2: "Stereo"}.get(info.channels, f"{info.channels} Channels"); self.channels_label.setText(f"{info.channels} ({channel_desc})"); bit_depth_str = info.subtype.replace('PCM_', '') + "-bit PCM" if 'PCM' in info.subtype else info.subtype; self.bitdepth_label.setText(bit_depth_str if bit_depth_str else "N/A")
        self.waveform_widget.set_audio_data(self.audio_data, self.sr, self.overview_data); self.player.setMedia(QMediaContent(QUrl.fromLocalFile(self.current_filepath))); self.playback_slider.setRange(0, int(self.known_duration)); self.play_pause_btn.setEnabled(True); self.playback_slider.setEnabled(True); self.analysis_actions_group.setEnabled(True)
        self.calculate_and_show_recommendation()
        if self._pending_csv_path:
            self._apply_csv_data(self._pending_csv_path)
            self._pending_csv_path = None # 清除状态
    def calculate_and_show_recommendation(self):
        try:
            cpu_cores = os.cpu_count() or 4; duration_sec = self.known_duration / 1000
            if duration_sec < 2: duration_score = 7
            elif duration_sec < 5: duration_score = 6
            elif duration_sec < 30: duration_score = 5
            elif duration_sec < 60: duration_score = 3
            else: duration_score = 1
            if cpu_cores >= 12: cpu_score = 7
            elif cpu_cores >= 8: cpu_score = 6
            elif cpu_cores >= 4: cpu_score = 5
            else: cpu_score = 3
            recommended = round(duration_score * 0.6 + cpu_score * 0.4)
            final_recommendation = max(1, min(recommended, 7))
            self.recommended_density = final_recommendation
            self.accept_recommendation_btn.setText(f"建议 (Lvl {self.recommended_density})")
            self.accept_recommendation_btn.setVisible(True)
        except Exception as e:
            print(f"智能密度推荐计算失败: {e}")
            self.accept_recommendation_btn.setVisible(False)
    def apply_recommended_density(self):
        self.density_slider.setValue(self.recommended_density)
        self.accept_recommendation_btn.setVisible(False)
    def run_full_analysis(self):
        if self.audio_data is None: return
        try:
            f0_min = int(self.f0_min_input.text()); f0_max = int(self.f0_max_input.text())
            if f0_min >= f0_max: QMessageBox.warning(self, "参数错误", "F0最小值必须小于最大值。"); return
        except ValueError: QMessageBox.warning(self, "参数错误", "F0范围必须是有效的整数。"); return
        self.run_task('analyze', audio_data=self.audio_data, sr=self.sr, is_wide_band=self.spectrogram_type_checkbox.isChecked(), density_level=self.density_slider.value(), pre_emphasis=self.pre_emphasis_checkbox.isChecked(), f0_min=f0_min, f0_max=f0_max, progress_text="正在进行完整声学分析...")
    def run_view_formant_analysis(self):
        if self.audio_data is None: return
        start, end = self.waveform_widget._view_start_sample, self.waveform_widget._view_end_sample
        narrow_band_window_s = 0.035; base_n_fft_for_hop = 1 << (int(self.sr * narrow_band_window_s) - 1).bit_length()
        overlap_ratio = 1 - (1 / (2**self.density_slider.value())); hop_length = int(base_n_fft_for_hop * (1 - overlap_ratio)) or 1
        self.run_task('analyze_formants_view', audio_data=self.audio_data, sr=self.sr, start_sample=start, end_sample=end, hop_length=hop_length, pre_emphasis=self.pre_emphasis_checkbox.isChecked(), progress_text="正在分析可见区域共振峰...")
    def on_analysis_finished(self, results):
        if self.progress_dialog: self.progress_dialog.close()
        hop_length = results.get('hop_length', 256); self.spectrogram_widget.set_data(results.get('S_db'), self.sr, hop_length)
        self.spectrogram_widget.set_analysis_data(f0_data=results.get('f0_raw'), f0_derived_data=results.get('f0_derived'), intensity_data=results.get('intensity'))
    def on_formant_view_finished(self, results):
        if self.progress_dialog: self.progress_dialog.close()
        formant_data = results.get('formants_view', [])
        self.spectrogram_widget.set_analysis_data(formants_data=formant_data, clear_previous_formants=False); QMessageBox.information(self, "分析完成", f"已在可见区域找到并显示了 {len(formant_data)} 个有效音框的共振峰。")
    def on_scrollbar_moved(self, value):
        if self.audio_data is None: return
        view_width = self.waveform_widget._view_end_sample - self.waveform_widget._view_start_sample
    
        # 为了清晰，我们定义开始和结束采样点
        start_sample = value
        end_sample = value + view_width

        # 更新波形和语谱图 (已有逻辑)
        self.waveform_widget.set_view_window(start_sample, end_sample)
        self.spectrogram_widget.set_view_window(start_sample, end_sample)

        # 新增下面这行，用来同步更新时间轴
        self.time_axis_widget.update_view(start_sample, end_sample, self.sr)
    def update_duration(self, duration):
        """
        当播放器成功加载媒体并获取到时长时被调用。
        我们在此处执行播放器的“预热”操作。
        """
        if duration > 0:
            # 如果总时长尚未记录，则记录下来
            if self.known_duration == 0:
                self.known_duration = duration

            # 如果播放器尚未“预热”，则执行预热操作
            if not self.is_player_ready:
                # 1. 短暂播放一下
                self.player.play()
                # 2. 立即暂停
                self.player.pause()
                # 3. 将播放头重置到开头
                self.player.setPosition(0)
                # 4. 设置标志，防止重复预热
                self.is_player_ready = True
    def run_task(self, task_type, progress_text="正在处理...", **kwargs):
        if self.is_task_running: QMessageBox.warning(self, "操作繁忙", "请等待当前分析任务完成后再试。"); return
        self.is_task_running = True; self.progress_dialog = QProgressDialog(progress_text, "取消", 0, 0, self); self.progress_dialog.setWindowModality(Qt.WindowModal); self.progress_dialog.show(); self.task_thread = QThread(); self.worker = AudioTaskWorker(task_type, **kwargs); self.worker.moveToThread(self.task_thread); self.task_thread.started.connect(self.worker.run); self.worker.error.connect(self.on_task_error)
        if task_type == 'load': self.worker.finished.connect(self.on_load_finished)
        elif task_type == 'analyze': self.worker.finished.connect(self.on_analysis_finished)
        elif task_type == 'analyze_formants_view': self.worker.finished.connect(self.on_formant_view_finished)
        self.worker.finished.connect(self.task_thread.quit); self.worker.finished.connect(self.worker.deleteLater); self.task_thread.finished.connect(self.task_thread.deleteLater); self.task_thread.finished.connect(self.on_thread_finished)
        if self.progress_dialog: self.progress_dialog.canceled.connect(self.task_thread.requestInterruption)
        self.task_thread.start()
    def load_audio_file(self, filepath): self.clear_all(); self.current_filepath = filepath; self.run_task('load', filepath=filepath, progress_text=f"正在加载音频...")
    def open_file_dialog(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "选择音频文件", "", "音频文件 (*.wav *.mp3 *.flac *.ogg *.m4a);;所有文件 (*.*)");
        if filepath: self.load_audio_file(filepath)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile():
                filepath = url.toLocalFile().lower()
                # --- 修改: 接受音频文件或CSV文件 ---
                if filepath.endswith(('.wav', '.mp3', '.flac', 'ogg', '.m4a', '.csv')):
                    event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            filepath = event.mimeData().urls()[0].toLocalFile()
            # --- 修改: 根据文件类型分派任务 ---
            if filepath.lower().endswith('.csv'):
                self.load_from_csv(filepath)
            else:
                self.load_audio_file(filepath)
    def on_thread_finished(self): self.task_thread, self.worker = None, None; self.is_task_running = False
    def on_task_error(self, error_msg):
        if hasattr(self, 'progress_dialog') and self.progress_dialog: self.progress_dialog.close()
        QMessageBox.critical(self, "任务失败", f"处理过程中发生错误:\n{error_msg}"); self.clear_all()
    def update_icons(self): 
        self.open_file_btn.setIcon(self.icon_manager.get_icon("open_file")); self.on_player_state_changed(self.player.state())
        self.analyze_button.setIcon(self.icon_manager.get_icon("analyze_dark")); formant_icon = self.icon_manager.get_icon("analyze_dark")
        if formant_icon.isNull(): formant_icon = self.icon_manager.get_icon("analyze")
        self.analyze_formants_button.setIcon(formant_icon)
    def format_time(self, ms):
        if ms <= 0: return "00:00.00"
        td = timedelta(milliseconds=ms); minutes, seconds = divmod(td.seconds, 60); milliseconds = td.microseconds // 10000
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:02d}"
    def handle_export_image(self):
        """处理将当前视图以高质量渲染并导出为图片的请求。"""
        if self.current_filepath is None: return

        # 1. 弹出对话框让用户选择选项
        dialog = ExportDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return # 用户取消
        
        options = dialog.get_options()

        # 2. 获取保存路径
        base_name = os.path.splitext(os.path.basename(self.current_filepath))[0]
        default_path = os.path.join(os.path.dirname(self.current_filepath), f"{base_name}_view.png")
        save_path, _ = QFileDialog.getSaveFileName(self, "保存视图为图片", default_path, "PNG 图片 (*.png);;JPEG 图片 (*.jpg)")
        
        if not save_path: return
        
        # 3. 执行高质量渲染
        try:
            pixmap = self.render_high_quality_image(options)
            if not pixmap.save(save_path):
                QMessageBox.critical(self, "保存失败", f"无法将图片保存到:\n{save_path}")
            else:
                QMessageBox.information(self, "保存成功", f"视图已成功保存为图片:\n{save_path}")
        except Exception as e:
            # 打印更详细的错误信息到控制台，方便调试
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "渲染失败", f"生成高分辨率图片时发生错误: {e}")

    def render_high_quality_image(self, options):
        """
        根据给定选项，创建一个临时的 SpectrogramWidget，以指定的分辨率和样式
        将其渲染到一个 QPixmap 上。UI元素（文字、轴）的大小保持固定，不随分辨率缩放。
        """
        source_widget = self.spectrogram_widget
        resolution = options["resolution"]
        
        # --- 定义固定的UI元素尺寸 ---
        INFO_FONT_PIXEL_SIZE = 14
        TIME_AXIS_FONT_PIXEL_SIZE = 12
        SPECTROGRAM_AXIS_FONT_PIXEL_SIZE = 12
        TIME_AXIS_HEIGHT = 35 # 固定像素高度

        if resolution is None:
            target_width, target_height = source_widget.width(), source_widget.height()
        else:
            target_width, target_height = resolution
        
        # --- 布局计算 (使用固定高度) ---
        axis_height = TIME_AXIS_HEIGHT if options["add_time_axis"] else 0
        spectrogram_height = target_height - axis_height

        # --- 创建渲染目标 ---
        pixmap = QPixmap(target_width, target_height)
        pixmap.fill(source_widget.backgroundColor)

        # --- 渲染语谱图部分 ---
        if spectrogram_height > 0:
            temp_widget = SpectrogramWidget(None, self.icon_manager)
            temp_widget.setAttribute(Qt.WA_DontShowOnScreen)
            temp_widget.show()
            
            # **核心修改**: 为临时控件设置固定的字体大小
            fixed_font = QFont()
            fixed_font.setPixelSize(SPECTROGRAM_AXIS_FONT_PIXEL_SIZE)
            temp_widget.setFont(fixed_font)
            
            meta_obj = temp_widget.metaObject()
            for i in range(meta_obj.propertyOffset(), meta_obj.propertyCount()):
                prop = meta_obj.property(i)
                if prop.isWritable(): temp_widget.setProperty(prop.name(), source_widget.property(prop.name()))
            
            temp_widget.spectrogram_image = source_widget.spectrogram_image
            temp_widget.sr = source_widget.sr; temp_widget.hop_length = source_widget.hop_length
            temp_widget.max_display_freq = source_widget.max_display_freq
            temp_widget.set_view_window(source_widget._view_start_sample, source_widget._view_end_sample)
            temp_widget.set_analysis_data(
                f0_data=source_widget._f0_data, f0_derived_data=source_widget._f0_derived_data,
                intensity_data=source_widget._intensity_data, formants_data=source_widget._formants_data
            )
            temp_widget.set_overlay_visibility(
                show_f0=source_widget._show_f0, show_f0_points=source_widget._show_f0_points, show_f0_derived=source_widget._show_f0_derived,
                show_intensity=source_widget._show_intensity, smooth_intensity=source_widget._smooth_intensity,
                show_formants=source_widget._show_formants, highlight_f1=source_widget._highlight_f1, highlight_f2=source_widget._highlight_f2, show_other_formants=source_widget._show_other_formants
            )

            temp_widget.resize(target_width, spectrogram_height)
            
            temp_widget.render(pixmap, QPoint(0, 0), QRegion(0, 0, target_width, spectrogram_height))

            temp_widget.hide()
            temp_widget.deleteLater()

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # --- 渲染时间轴部分 ---
        if options["add_time_axis"] and axis_height > 0:
            axis_rect = QRect(0, spectrogram_height, target_width, axis_height)
            
            view_start_sample = source_widget._view_start_sample
            view_end_sample = source_widget._view_end_sample
            sr = source_widget.sr
            view_duration_s = (view_end_sample - view_start_sample) / sr if sr > 0 else 0
            start_time_s = view_start_sample / sr if sr > 0 else 0

            target_ticks = max(5, int(target_width / 150))
            raw_interval = view_duration_s / target_ticks if target_ticks > 0 else 0
            
            if raw_interval > 0:
                power = 10.0 ** math.floor(math.log10(raw_interval))
                if raw_interval / power < 1.5: interval = 1 * power
                elif raw_interval / power < 3.5: interval = 2 * power
                elif raw_interval / power < 7.5: interval = 5 * power
                else: interval = 10 * power
                
                # **核心修改**: 使用固定的像素字体大小
                font = QFont(); font.setPixelSize(TIME_AXIS_FONT_PIXEL_SIZE)
                painter.setFont(font)
                painter.setPen(source_widget.palette().color(QPalette.Text))

                first_tick_time = math.ceil(start_time_s / interval) * interval
                
                for i in range(int(target_ticks * 2)):
                    tick_time = first_tick_time + i * interval
                    if tick_time > start_time_s + view_duration_s: break

                    x_pos = (tick_time - start_time_s) / view_duration_s * target_width if view_duration_s > 0 else 0
                    
                    painter.drawLine(int(x_pos), axis_rect.top(), int(x_pos), axis_rect.top() + 5)
                    
                    if interval >= 1: label = f"{tick_time:.1f}s"
                    elif interval >= 0.1: label = f"{tick_time:.2f}"
                    elif interval >= 0.01: label = f"{tick_time:.3f}"
                    else: label = f"{tick_time * 1000:.1f}ms"
                    
                    painter.drawText(QRect(int(x_pos) - 50, axis_rect.top() + 5, 100, axis_rect.height() - 5), Qt.AlignCenter | Qt.TextDontClip, label)

        # --- 渲染信息标签部分 ---
        if options["info_label"]:
            # **核心修改**: 使用固定的像素字体大小
            font = QFont(); font.setPixelSize(INFO_FONT_PIXEL_SIZE)
            painter.setFont(font)
            painter.setPen(QColor(Qt.darkGray))
            
            info_text = f"File: {os.path.basename(self.current_filepath)}\n" \
                        f"Duration: {self.format_time(self.known_duration)}\n" \
                        f"Sample Rate: {self.sr} Hz"
            
            margin = 15 # 固定边距
            text_rect = QRect(0, 0, target_width - margin, target_height - margin)
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignTop, info_text)
        
        painter.end()
        return pixmap
    def handle_export_csv(self):
        """处理将选区内的分析数据导出为CSV的请求。"""
        if self.current_selection is None or self.sr is None: return

        start_s = self.current_selection[0] / self.sr
        end_s = self.current_selection[1] / self.sr
        
        base_name = os.path.splitext(os.path.basename(self.current_filepath))[0]
        default_path = os.path.join(os.path.dirname(self.current_filepath), f"{base_name}_analysis_{start_s:.2f}-{end_s:.2f}s.csv")
        
        save_path, _ = QFileDialog.getSaveFileName(self, "导出分析数据为CSV", default_path, "CSV 文件 (*.csv)")

        if not save_path: return

        try:
            # 准备数据
            all_data = []

            # F0 数据
            if self.spectrogram_widget._f0_data:
                times, f0_vals = self.spectrogram_widget._f0_data
                for t, f0 in zip(times, f0_vals):
                    if start_s <= t < end_s:
                        all_data.append({'timestamp': t, 'f0_hz': f0})

            # 强度数据
            if self.spectrogram_widget._intensity_data is not None:
                hop_length = self.spectrogram_widget.hop_length
                intensity_times = librosa.frames_to_time(np.arange(len(self.spectrogram_widget._intensity_data)), sr=self.sr, hop_length=hop_length)
                for t, intensity in zip(intensity_times, self.spectrogram_widget._intensity_data):
                     if start_s <= t < end_s:
                        all_data.append({'timestamp': t, 'intensity': intensity})
            
            # 共振峰数据
            if self.spectrogram_widget._formants_data:
                for sample_pos, formants in self.spectrogram_widget._formants_data:
                    t = sample_pos / self.sr
                    if start_s <= t < end_s:
                        formant_dict = {'timestamp': t}
                        for i, f in enumerate(formants):
                            formant_dict[f'f{i+1}_hz'] = f
                        all_data.append(formant_dict)
            
            if not all_data:
                QMessageBox.warning(self, "无数据", "在选定区域内没有可导出的分析数据。")
                return

            # 合并数据
            df = pd.DataFrame(all_data)
            df = df.groupby('timestamp').first().reset_index() # 合并同一时间戳的数据
            df = df.sort_values(by='timestamp').round(4) # 排序并四舍五入
            
            df.to_csv(save_path, index=False, encoding='utf-8-sig')
            QMessageBox.information(self, "导出成功", f"分析数据已成功导出到CSV文件:\n{save_path}")

        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出CSV时发生错误: {e}")

    def handle_export_wav(self):
        """处理将选区音频导出为WAV的请求。"""
        if self.current_selection is None or self.audio_data is None: return

        start_sample, end_sample = self.current_selection
        
        start_s = start_sample / self.sr
        end_s = end_sample / self.sr

        base_name = os.path.splitext(os.path.basename(self.current_filepath))[0]
        default_path = os.path.join(os.path.dirname(self.current_filepath), f"{base_name}_slice_{start_s:.2f}-{end_s:.2f}s.wav")
        
        save_path, _ = QFileDialog.getSaveFileName(self, "导出音频切片为WAV", default_path, "WAV 音频 (*.wav)")
        
        if save_path:
            try:
                audio_slice = self.audio_data[start_sample:end_sample]
                sf.write(save_path, audio_slice, self.sr)
                QMessageBox.information(self, "导出成功", f"音频切片已成功保存到:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"保存音频切片时发生错误: {e}")

    def load_from_csv(self, csv_path):
        """处理拖入的CSV文件，查找关联音频并加载。"""
        try:
            # 1. 解析文件名以找到 base_name
            filename = os.path.basename(csv_path)
            match = re.match(r'(.+)_analysis_.*\.csv', filename)
            if not match:
                QMessageBox.warning(self, "文件名格式不匹配", "无法从此CSV文件名中识别出原始音频文件。\n\n文件名应为 '[原始文件名]_analysis_...' 格式。")
                return
            
            base_name = match.group(1)
            csv_dir = os.path.dirname(csv_path)

            # 2. 搜索关联的音频文件
            audio_path = None
            for ext in ['.wav', '.mp3', '.flac', '.ogg', '.m4a']:
                potential_path = os.path.join(csv_dir, base_name + ext)
                if os.path.exists(potential_path):
                    audio_path = potential_path
                    break
            
            if not audio_path:
                QMessageBox.critical(self, "未找到音频文件", f"在与CSV文件相同的目录下，找不到名为 '{base_name}' 的原始音频文件。")
                return

            # 3. 设置待处理状态并加载音频文件
            self._pending_csv_path = csv_path
            self.load_audio_file(audio_path)

        except Exception as e:
            QMessageBox.critical(self, "处理CSV失败", f"处理拖入的CSV文件时发生错误: {e}")

    def _apply_csv_data(self, csv_path):
        """读取CSV文件并将其中的分析数据应用到语谱图上。"""
        try:
            df = pd.read_csv(csv_path)
            if 'timestamp' not in df.columns:
                QMessageBox.warning(self, "CSV格式错误", "CSV文件中缺少必需的 'timestamp' 列。")
                return

            # 清除旧的分析数据，但不清除语谱图本身
            self.spectrogram_widget.set_analysis_data(f0_data=None, intensity_data=None, formants_data=None)

            # 准备新的数据容器
            f0_data, intensity_data, formants_data = None, None, []
            
            # --- 提取F0数据 ---
            if 'f0_hz' in df.columns:
                f0_df = df[['timestamp', 'f0_hz']].dropna()
                f0_times = f0_df['timestamp'].to_numpy()
                f0_values = f0_df['f0_hz'].to_numpy()
                f0_data = (f0_times, f0_values)

            # --- 提取强度数据 ---
            if 'intensity' in df.columns:
                intensity_df = df[['timestamp', 'intensity']].dropna()
                # 注意: 强度数据需要是一个没有时间戳的纯数组，因为它的时间由 hop_length 决定
                # 这里我们假设CSV中的时间戳与hop_length匹配，直接提取值
                intensity_data = intensity_df['intensity'].to_numpy()

            # --- 提取共振峰数据 ---
            formant_cols = [col for col in df.columns if col.startswith('f') and col.endswith('_hz')]
            if formant_cols:
                formant_df = df[['timestamp'] + formant_cols].dropna(subset=formant_cols, how='all')
                for _, row in formant_df.iterrows():
                    sample_pos = int(row['timestamp'] * self.sr)
                    formants = [row[col] for col in formant_cols if pd.notna(row[col])]
                    if formants:
                        formants_data.append((sample_pos, formants))
            
            # 应用提取的数据
            self.spectrogram_widget.set_analysis_data(
                f0_data=f0_data,
                intensity_data=intensity_data,
                formants_data=formants_data,
                clear_previous_formants=True
            )
            QMessageBox.information(self, "加载成功", "已从CSV加载分析数据。\n\n请注意，语谱图背景需要手动点击“运行完整分析”来生成。")

        except Exception as e:
            QMessageBox.critical(self, "应用CSV数据失败", f"读取并应用CSV数据时发生错误: {e}")
# [新增] 用于处理和保存持久化设置的槽函数
    def _on_persistent_setting_changed(self, key, value):
        """当用户更改任何可记忆的设置时，调用此方法以保存状态。"""
        self.parent_window.update_and_save_module_state('audio_analysis', key, value)
    def _load_persistent_settings(self):
        """加载并应用所有持久化的用户设置。"""
        # 从全局配置中安全地获取本模块的状态字典
        module_states = self.parent_window.config.get("module_states", {}).get("audio_analysis", {})
        
        # 定义所有需要加载的控件及其属性、键名和默认值
        controls_to_load = [
            # 可视化选项 (Toggles)
            (self.show_f0_toggle, 'setChecked', 'show_f0', True),
            (self.show_f0_points_checkbox, 'setChecked', 'show_f0_points', True),
            (self.show_f0_derived_checkbox, 'setChecked', 'show_f0_derived', True),
            (self.show_intensity_toggle, 'setChecked', 'show_intensity', True),
            (self.smooth_intensity_checkbox, 'setChecked', 'smooth_intensity', False),
            (self.show_formants_toggle, 'setChecked', 'show_formants', True),
            (self.highlight_f1_checkbox, 'setChecked', 'highlight_f1', True),
            (self.highlight_f2_checkbox, 'setChecked', 'highlight_f2', True),
            (self.show_other_formants_checkbox, 'setChecked', 'show_other_formants', True),
            # 高级分析参数
            (self.pre_emphasis_checkbox, 'setChecked', 'pre_emphasis', False),
            (self.f0_min_input, 'setText', 'f0_min', "75"),
            (self.f0_max_input, 'setText', 'f0_max', "500"),
            # 语谱图设置
            (self.density_slider, 'setValue', 'density', 4),
            (self.spectrogram_type_checkbox, 'setChecked', 'is_wide_band', False),
        ]

        # 批量加载
        for control, setter_method_name, key, default_value in controls_to_load:
            control.blockSignals(True)
            value_to_set = module_states.get(key, default_value)
            # 使用 getattr 动态调用控件的 setter 方法
            getattr(control, setter_method_name)(value_to_set)
            control.blockSignals(False)
            
        # 手动触发一次UI更新，确保依赖关系和标签正确显示
        self._update_dependent_widgets()
        self.update_overlays()
        self._update_density_label(self.density_slider.value())



class SpectrumSliceDialog(QDialog):
    """一个显示频谱切片的对话框。"""
    def __init__(self, freqs, mags_db, time_s, sr, parent=None):
        super().__init__(parent)
        self.freqs = freqs
        self.mags_db = mags_db
        self.time_s = time_s
        self.sr = sr
        
        self.setWindowTitle(f"频谱切片 @ {self.time_s:.3f} s")
        self.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(self)
        self.plot_widget = QWidget()
        self.plot_widget.paintEvent = self.paint_plot
        self.plot_widget.setMouseTracking(True)
        self.plot_widget.mouseMoveEvent = self.plot_mouse_move
        layout.addWidget(self.plot_widget)

        self.info_label = QLabel(" ")
        self.info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_label)
        
        self.max_freq = self.sr / 2
        self.min_db = np.max(self.mags_db) - 80 # 显示80dB的动态范围
        self.max_db = np.max(self.mags_db)

    def paint_plot(self, event):
        painter = QPainter(self.plot_widget)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.plot_widget.rect().adjusted(40, 10, -10, -30)
        painter.fillRect(self.plot_widget.rect(), self.palette().color(QPalette.Window))

        if not rect.isValid(): return
        
        # 绘制坐标轴
        painter.setPen(self.palette().color(QPalette.Mid))
        painter.drawRect(rect)
        
        # X轴 (频率)
        for i in range(6):
            freq = i * self.max_freq / 5
            x = rect.left() + i * rect.width() / 5
            painter.drawLine(int(x), rect.bottom(), int(x), rect.bottom() + 5)
            painter.drawText(QPoint(int(x) - 20, rect.bottom() + 20), f"{freq/1000:.1f}k")
        painter.drawText(rect.center().x() - 20, rect.bottom() + 25, "频率 (Hz)")

        # Y轴 (幅度 dB)
        for i in range(5):
            db = self.min_db + i * (self.max_db - self.min_db) / 4
            y = rect.bottom() - i * rect.height() / 4
            painter.drawLine(rect.left(), int(y), rect.left() - 5, int(y))
            painter.drawText(QRect(0, int(y) - 10, rect.left() - 10, 20), Qt.AlignRight, f"{db:.0f}")
        
        # 绘制频谱曲线
        painter.setPen(QPen(self.palette().color(QPalette.Highlight), 2))
        points = []
        for f, m_db in zip(self.freqs, self.mags_db):
            if f > self.max_freq: break
            x = rect.left() + (f / self.max_freq) * rect.width()
            y_ratio = (m_db - self.min_db) / (self.max_db - self.min_db) if (self.max_db - self.min_db) > 0 else 0
            y = rect.bottom() - max(0, min(1, y_ratio)) * rect.height()
            points.append(QPointF(x, y))
        
        if points:
            painter.drawPolyline(*points)
            
    def plot_mouse_move(self, event):
        rect = self.plot_widget.rect().adjusted(40, 10, -10, -30)
        if rect.contains(event.pos()):
            x_ratio = (event.x() - rect.left()) / rect.width()
            y_ratio = (rect.bottom() - event.y()) / rect.height()
            
            freq = x_ratio * self.max_freq
            db = self.min_db + y_ratio * (self.max_db - self.min_db)
            
            self.info_label.setText(f"频率: {freq:.1f} Hz  |  幅度: {db:.1f} dB")
        else:
            self.info_label.setText(" ")