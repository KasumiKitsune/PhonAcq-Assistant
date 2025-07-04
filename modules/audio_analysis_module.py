# --- START OF FILE modules/audio_analysis_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "音频分析"
MODULE_DESCRIPTION = "对单个音频文件进行声学分析，包括波形、语谱图、基频(F0)、强度和共振峰的可视化，并支持对长音频的流畅缩放与导航。"
# ---

import os
import sys
from datetime import timedelta

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QMessageBox, QGroupBox, QFormLayout, QSizePolicy, QSlider,
                             QScrollBar, QProgressDialog)
from PyQt5.QtCore import Qt, QUrl, QPointF, QThread, pyqtSignal, QObject, pyqtProperty, QRect
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPalette, QImage

# 模块级别依赖检查
try:
    import numpy as np
    import soundfile as sf
    import librosa
    import pandas as pd # [新增] 导入 pandas 用于插值
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: audio_analysis_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)


# --- 后台工作器 ---
class AudioTaskWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)


    def __init__(self, task_type, filepath=None, audio_data=None, sr=None, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.filepath = filepath
        self.y = audio_data
        self.sr = sr
        self.hop_length = kwargs.get('hop_length', 256)
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
        # 1. 计算原始 F0 (不变)
        f0_raw, voiced_flag, _ = librosa.pyin(self.y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), frame_length=2048, hop_length=self.hop_length)
        times = librosa.times_like(f0_raw, sr=self.sr, hop_length=self.hop_length)
        f0_raw[~voiced_flag] = np.nan

        # 2. [新增] 进行线性插值以创建“派生基频”
        f0_series = pd.Series(f0_raw)
        f0_interpolated = f0_series.interpolate(method='linear', limit_direction='both').to_numpy()
        
        # 3. 计算其他分析 (不变)
        intensity = librosa.feature.rms(y=self.y, frame_length=2048, hop_length=self.hop_length)[0]
        D = librosa.stft(self.y, hop_length=self.hop_length, n_fft=2048)
        S_db = librosa.amplitude_to_db(np.abs(D), ref=np.max)

        # 4. [修改] 将两组 F0 数据都传回UI
        self.finished.emit({
            'f0_raw': (times, f0_raw),
            'f0_derived': (times, f0_interpolated),
            'intensity': intensity,
            'S_db': S_db,
            'hop_length': self.hop_length
        })
    
    def _run_formant_view_task(self):
        start_sample, end_sample = self.kwargs.get('start_sample', 0), self.kwargs.get('end_sample', len(self.y))
        y_view = self.y[start_sample:end_sample]
        frame_length = int(self.sr * 0.025) # 25ms frame
        order = 2 + self.sr // 1000
        
        formant_points = []
        for i in range(0, len(y_view) - frame_length, self.hop_length):
            y_frame = y_view[i : i + frame_length]
            
            # 帧有效性检查 (不变)
            if np.max(np.abs(y_frame)) < 1e-5 or not np.isfinite(y_frame).all(): continue

            try:
                a = librosa.lpc(y_frame, order=order)
                if not np.isfinite(a).all(): continue

                roots = [r for r in np.roots(a) if np.imag(r) >= 0]
                freqs = sorted(np.angle(roots) * (self.sr / (2 * np.pi)))

                # [修复] 引入更稳健的共振峰识别逻辑，而不是简单取前几个
                # 这是简化的跟踪，寻找每个共振峰区域内最强的峰
                found_formants = []
                # F1: 250-800, F2: 800-2200, F3: 2200-3000, F4: 3000-4000 (大致范围)
                formant_ranges = [(250, 800), (800, 2200), (2200, 3000), (3000, 4000)]
                
                # 创建一个副本以安全地从中移除元素
                candidate_freqs = list(freqs)
                
                for f_min, f_max in formant_ranges:
                    band_freqs = [f for f in candidate_freqs if f_min <= f <= f_max]
                    if band_freqs:
                        # 在该频带内选择一个频率 (这里简化为取第一个，更复杂的可以计算能量)
                        best_f = band_freqs[0]
                        found_formants.append(best_f)
                        # 从候选中移除，防止被重复选为其他共振峰
                        candidate_freqs.remove(best_f)

                if found_formants:
                    formant_points.append((start_sample + i + frame_length // 2, found_formants))

            except Exception as e:
                # print(f"Formant frame analysis failed: {e}") # for debugging
                continue
                
        self.finished.emit({'formants_view': formant_points})

# --- [重构] 语谱图控件现在是分析结果的主显示区 ---
class SpectrogramWidget(QWidget):
    
# In SpectrogramWidget class

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.spectrogram_image = None
        self._view_start_sample = 0
        self._view_end_sample = 1
        self.sr = 1
        self.hop_length = 256
        self._playback_pos_sample = -1
        self._f0_data, self._intensity_data, self._formants_data = None, None, []
        self._f0_derived_data = None
        self._show_f0, self._show_intensity, self._show_formants = True, True, True
        self._show_f0_derived = True
        self.max_display_freq = 5000
        self._highlight_f1 = True
        self._cursor_info_text = ""
        self._f0_display_min = 75   # Y轴显示的最小值 (Hz)
        self._f0_display_max = 400  # Y轴显示的最大值 (Hz)
        self._f0_axis_enabled = False # 是否绘制F0坐标轴
        self._backgroundColor = Qt.white
        self._spectrogramMinColor = Qt.white # [新增] 能量最低处的颜色
        self._spectrogramMaxColor = Qt.black # [新增] 能量最高处的颜色
        self._intensityColor = QColor("#4CAF50")

        # [新增] 为QSS定义颜色属性和默认值
        # 默认值设计为在没有主题时也能清晰显示
        self._backgroundColor = Qt.white
        self._intensityColor = QColor("#4CAF50") # Green
        self._f0Color = QColor("#FFA726") # Amber
        self._f0DerivedColor = QColor(150, 150, 255, 150) # Semi-transparent blue
        self._f1Color = QColor("#FF6F00") # Deep Orange
        self._formantColor = QColor("#29B6F6") # Light Blue
        self._cursorColor = QColor("red")
        self._infoTextColor = Qt.white
        self._infoBackgroundColor = QColor(0, 0, 0, 150)
        self._f0AxisColor = QColor(150, 150, 150) # [新增] F0坐标轴颜色
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


    def set_data(self, S_db, sr, hop_length):
        self.sr, self.hop_length = sr, hop_length
        
        # 1. 归一化能量值 (0.0 to 1.0)
        S_norm = (S_db - S_db.min()) / (S_db.max() - S_db.min() + 1e-6)
        
        # 2. [重构] 创建 RGBA 图像
        h, w = S_norm.shape
        rgba_data = np.zeros((h, w, 4), dtype=np.uint8)
        
        # 3. [修复] 健壮地获取 RGBA 分量，处理 GlobalColor 枚举
        min_color_obj = QColor(self._spectrogramMinColor)
        max_color_obj = QColor(self._spectrogramMaxColor)

        min_c = np.array(min_color_obj.getRgb())
        max_c = np.array(max_color_obj.getRgb())
        
        # 4. 使用 numpy 的广播进行线性插值，计算每个像素的颜色
        interpolated_colors = min_c + (max_c - min_c) * (S_norm[..., np.newaxis])
        rgba_data[..., :4] = interpolated_colors.astype(np.uint8)

        # 5. 上下翻转图像以匹配频率轴
        image_data = np.flipud(rgba_data)
        
        # 6. 创建 QImage.Format_RGBA8888 格式的图像
        self.spectrogram_image = QImage(image_data.tobytes(), w, h, QImage.Format_RGBA8888).copy()
        self.update()

    def leaveEvent(self, event):
        """鼠标离开控件时，清除信息文本并重绘。"""
        if self._cursor_info_text:
            self._cursor_info_text = ""
            self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标在控件上移动时，计算并更新要显示的信息。"""
        if self.spectrogram_image is None:
            super().mouseMoveEvent(event)
            return

        w, h = self.width(), self.height()
        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0:
            super().mouseMoveEvent(event)
            return

        # 计算鼠标位置对应的时间和频率
        x_ratio = event.x() / w
        y_ratio = (h - event.y()) / h # Y轴是反的
        
        current_sample = self._view_start_sample + x_ratio * view_width_samples
        current_time_s = current_sample / self.sr
        current_freq_hz = y_ratio * self.max_display_freq

        info_parts = [f"Time: {current_time_s:.3f} s", f"Freq: {current_freq_hz:.0f} Hz"]

        # 寻找最近的 F0 点
        if self._f0_data and self._show_f0:
            times, f0_values = self._f0_data
            if len(times) > 0:
                # 找到时间上最接近的点的索引
                time_diffs = np.abs(times - current_time_s)
                closest_idx = np.argmin(time_diffs)
                # 如果这个点足够近，并且是有效值，则显示它
                if time_diffs[closest_idx] < (self.hop_length / self.sr) and np.isfinite(f0_values[closest_idx]):
                    info_parts.append(f"F0: {f0_values[closest_idx]:.1f} Hz")
        
        # 寻找最近的共振峰点
        if self._formants_data and self._show_formants:
            closest_formant_dist = float('inf')
            closest_formants = None
            for sample_pos, formants in self._formants_data:
                dist = abs(sample_pos - current_sample)
                if dist < closest_formant_dist:
                    closest_formant_dist = dist
                    closest_formants = formants
            
            # 如果最近的共振峰点在几个帧的距离内
            if closest_formants and closest_formant_dist < (self.hop_length * 3):
                formant_str = " | ".join([f"F{i+1}: {int(f)}" for i, f in enumerate(closest_formants)])
                info_parts.append(formant_str)

        self._cursor_info_text = "\n".join(info_parts)
        self.update() # 请求重绘以显示新文本
        super().mouseMoveEvent(event)


    def set_analysis_data(self, f0_data=None, f0_derived_data=None, intensity_data=None, formants_data=None, clear_previous_formants=True):
        """
        累积式地更新分析数据。
        只会更新非 None 的参数，不会清除其他已有的数据。
        """
        # --- F0 Data Handling ---
        if f0_data is not None:
            self._f0_data = f0_data
            times, f0_values = f0_data
            valid_f0 = f0_values[np.isfinite(f0_values)]
            if len(valid_f0) > 1:
                self._f0_display_min = max(50, np.min(valid_f0) - 20)
                self._f0_display_max = np.max(valid_f0) + 20
                self._f0_axis_enabled = True
            else:
                self._f0_axis_enabled = False
        
        # --- Derived F0 Data Handling ---
        if f0_derived_data is not None:
            self._f0_derived_data = f0_derived_data

        # --- Intensity Data Handling ---
        if intensity_data is not None:
            self._intensity_data = intensity_data

        # --- Formants Data Handling ---
        if formants_data is not None:
            if clear_previous_formants:
                # 当运行“分析可见区域共振峰”时，我们希望覆盖掉所有旧的点
                self._formants_data = formants_data
            else:
                # 否则，我们是添加点（例如单击分析），应该合并
                # 但当前没有这个用例，所以直接赋值
                self._formants_data = formants_data

        self.update()

    def set_overlay_visibility(self, show_f0, show_f0_derived, show_intensity, show_formants, highlight_f1): # 新增 show_f0_derived
        self._show_f0, self._show_f0_derived, self._show_intensity, self._show_formants = show_f0, show_f0_derived, show_intensity, show_formants # [修改]
        self._highlight_f1 = highlight_f1
        self.update()
    
    def update_playback_position(self, position_ms):
        if self.sr > 1: self._playback_pos_sample = int(position_ms / 1000 * self.sr); self.update()

    def set_view_window(self, start_sample, end_sample):
        self._view_start_sample, self._view_end_sample = start_sample, end_sample; self.update()

    def clear(self):
        self.spectrogram_image, self._f0_data, self._intensity_data = None, None, None
        self._formants_data = []; self._playback_pos_sample = -1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        painter.fillRect(self.rect(), self._backgroundColor)
        w, h = self.width(), self.height()
        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0:
            return

        # 1. 绘制语谱图 (如果存在)
        if self.spectrogram_image:
            start_frame = self._view_start_sample // self.hop_length
            end_frame = self._view_end_sample // self.hop_length
            view_width_frames = end_frame - start_frame
            if view_width_frames > 0:
                source_rect = QRect(start_frame, 0, view_width_frames, self.spectrogram_image.height())
                painter.drawImage(self.rect(), self.spectrogram_image, source_rect)

        # 2. 绘制 F0 的独立 Y 轴 (在右侧)
        if self._f0_axis_enabled:
            painter.setPen(QPen(self._f0AxisColor, 1, Qt.DotLine))
            font = self.font()
            font.setPointSize(8)
            painter.setFont(font)
            
            f0_display_range = self._f0_display_max - self._f0_display_min
            if f0_display_range > 0:
                step = 50 if f0_display_range > 200 else 25 if f0_display_range > 100 else 10
                
                for freq in range(int(self._f0_display_min // step * step), int(self._f0_display_max) + 1, step):
                    if freq < self._f0_display_min: continue
                    y = h - ((freq - self._f0_display_min) / f0_display_range * h)
                    painter.drawLine(0, int(y), w - 30, int(y))
                    painter.drawText(w - 28, int(y) + 4, f"{freq}")

        # 3. 绘制强度曲线 (在底部区域)
        if self._show_intensity and self._intensity_data is not None:
            painter.setPen(QPen(self._intensityColor, 2))
            intensity_points = []
            max_intensity = np.max(self._intensity_data) if len(self._intensity_data) > 0 else 1.0
            if max_intensity == 0: max_intensity = 1.0
            
            for i, val in enumerate(self._intensity_data):
                sample_pos = i * self.hop_length
                if self._view_start_sample <= sample_pos < self._view_end_sample:
                    x = (sample_pos - self._view_start_sample) * w / view_width_samples
                    y = h - (val / max_intensity * h * 0.3) 
                    intensity_points.append(QPointF(x, y))
            if len(intensity_points) > 1:
                painter.drawPolyline(*intensity_points)

        # 4. 绘制 F0 曲线 (使用其独立坐标系)
        if self._f0_axis_enabled:
            f0_display_range = self._f0_display_max - self._f0_display_min
            if f0_display_range > 0:
                # 绘制派生基频
                if self._show_f0_derived and self._f0_derived_data:
                    painter.setPen(QPen(self._f0DerivedColor, 1.5, Qt.DashLine))
                    derived_points = []
                    derived_times, derived_f0 = self._f0_derived_data
                    for i, t in enumerate(derived_times):
                        sample_pos = t * self.sr
                        if self._view_start_sample <= sample_pos < self._view_end_sample and np.isfinite(derived_f0[i]):
                            x = (sample_pos - self._view_start_sample) * w / view_width_samples
                            y = h - ((derived_f0[i] - self._f0_display_min) / f0_display_range * h)
                            derived_points.append(QPointF(x, y))
                    if len(derived_points) > 1:
                        painter.drawPolyline(*derived_points)
                
                # 绘制原始 F0 点
                if self._show_f0 and self._f0_data:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(self._f0Color)
                    raw_times, raw_f0 = self._f0_data
                    for i, t in enumerate(raw_times):
                        sample_pos = t * self.sr
                        if self._view_start_sample <= sample_pos < self._view_end_sample and np.isfinite(raw_f0[i]):
                            x = (sample_pos - self._view_start_sample) * w / view_width_samples
                            y = h - ((raw_f0[i] - self._f0_display_min) / f0_display_range * h)
                            painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
        
        # 5. 绘制共振峰点 (使用语谱图的Y轴)
        if self._show_formants and self._formants_data:
            max_freq_y_axis = self.max_display_freq
            for sample_pos, formants in self._formants_data:
                if self._view_start_sample <= sample_pos < self._view_end_sample:
                    x = (sample_pos - self._view_start_sample) * w / view_width_samples
                    for i, f in enumerate(formants):
                        if i == 0 and self._highlight_f1:
                            painter.setBrush(self._f1Color)
                        else:
                            painter.setBrush(self._formantColor)
                        painter.setPen(Qt.NoPen)
                        
                        y = h - (f / max_freq_y_axis * h)
                        if 0 <= y <= h:
                            painter.drawEllipse(QPointF(x, y), 2, 2)
        
        # 6. 绘制播放头光标
        if self._view_start_sample <= self._playback_pos_sample < self._view_end_sample:
            pos_x = (self._playback_pos_sample - self._view_start_sample) * w / view_width_samples
            painter.setPen(QPen(self._cursorColor, 2))
            painter.drawLine(int(pos_x), 0, int(pos_x), h)
            
        # 7. 绘制鼠标悬停信息文本
        if self._cursor_info_text:
            font = self.font()
            font.setPointSize(10)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            text_rect = metrics.boundingRect(QRect(0, 0, w, h), Qt.AlignLeft, self._cursor_info_text)
            text_rect.translate(10, 10)
            text_rect.adjust(-5, -5, 5, 5)
            painter.setBrush(self._infoBackgroundColor)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(text_rect, 5, 5)
            painter.setPen(self._infoTextColor)
            painter.drawText(text_rect, Qt.AlignCenter, self._cursor_info_text)

# --- [重构] 波形控件现在只负责波形和简单的视图变化信号 ---
class WaveformWidget(QWidget):
    view_changed = pyqtSignal(int, int)
    @pyqtProperty(QColor)
    def waveformColor(self): return self._waveformColor
    @waveformColor.setter
    def waveformColor(self, color): self._waveformColor = color; self.update()

    # 只是为了兼容性，让QSS不报错
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
        self._backgroundColor = self.palette().color(QPalette.Base) # [新增] 初始化背景色属性

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
        
    def clear(self):
        self._y_full, self._y_overview = None, None; self.update(); self.view_changed.emit(0, 1)

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
            
def create_page(parent_window, icon_manager, ToggleSwitchClass):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"音频分析模块加载失败...\n请运行: pip install numpy soundfile librosa\n错误: {MISSING_ERROR_MESSAGE}")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    return AudioAnalysisPage(parent_window, icon_manager, ToggleSwitchClass)

class AudioAnalysisPage(QWidget):
    DENSITY_MAP, DENSITY_LABELS = {1: 1024, 2: 512, 3: 256, 4: 128, 5: 64}, {1: "最快", 2: "较快", 3: "标准", 4: "精细", 5: "最高"}
    def __init__(self, parent_window, icon_manager, ToggleSwitchClass):
        super().__init__(); self.parent_window = parent_window; self.icon_manager = icon_manager; self.ToggleSwitch = ToggleSwitchClass; self.setAcceptDrops(True)
        self.audio_data, self.sr, self.overview_data, self.current_filepath = None, None, None, None
        self.player = QMediaPlayer(); self.player.setNotifyInterval(30); self.known_duration = 0
        self.task_thread, self.worker = None, None
        self._init_ui(); self._connect_signals(); self.update_icons()


    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        # --------------------------------------------------------------------
        # 左侧侧边栏 - 分析与设置
        # --------------------------------------------------------------------
        self.left_panel = QWidget()
        self.left_panel.setFixedWidth(300)
        left_layout = QVBoxLayout(self.left_panel)

        self.settings_group = QGroupBox("分析设置")
        self.settings_group.setToolTip("在这里调整分析的精细度和计算速度。")
        settings_layout = QFormLayout(self.settings_group)
        self.density_slider = QSlider(Qt.Horizontal)
        self.density_slider.setRange(1, 5); self.density_slider.setValue(3)
        self.density_slider.setToolTip(
            "调整语谱图和各项分析的时间密度（帧移）。\n"
            "密度越高（滑块越靠右），分析越精细，但计算所需时间越长。\n"
            "对于快速概览，使用较低密度；对于精细分析，使用较高密度。"
        )
        self.density_label = QLabel()
        settings_layout.addRow("密度:", self.density_slider)
        settings_layout.addRow("", self.density_label)
        self._update_density_label(3)

        self.analysis_group = QGroupBox("声学分析")
        self.analysis_group.setToolTip("运行声学分析并控制其在图上的显示。")
        analysis_layout = QVBoxLayout(self.analysis_group)
        self.analysis_group.setEnabled(False)
        self.analyze_button, self.analyze_formants_button = QPushButton("运行完整分析"), QPushButton("分析共振峰")
        self.analyze_button.setToolTip(
            "对整个音频进行F0, 强度和语谱图分析。\n"
            "对于非常长的音频文件，这可能需要几十秒甚至更长时间。"
        )
        self.analyze_formants_button.setToolTip(
            "仅对当前屏幕上可见的区域进行共振峰分析。\n"
            "这是一个快速操作，用于在高放大倍率下查看共振峰。"
        )
        self.show_f0_switch, self.show_f0_derived_switch, self.show_intensity_switch, self.show_formants_switch, self.highlight_f1_switch = [self.ToggleSwitch() for _ in range(5)]
        [s.setChecked(True) for s in [self.show_f0_switch, self.show_f0_derived_switch, self.show_intensity_switch, self.show_formants_switch, self.highlight_f1_switch]]
        
        self.show_f0_switch.setToolTip("在语谱图上显示/隐藏原始的基频（F0）点。")
        self.show_f0_derived_switch.setToolTip("在语谱图上显示/隐藏通过插值生成的、连续的基频曲线。")
        self.show_intensity_switch.setToolTip("在语谱图底部显示/隐藏音频的强度（音量）曲线。")
        self.show_formants_switch.setToolTip("在语谱图上显示/隐藏分析出的共振峰点。")
        self.highlight_f1_switch.setToolTip("开启后，第一共振峰(F1)将以特殊的醒目颜色显示。")

        toggle_layout = QFormLayout()
        toggle_layout.addRow("显示 F0 (原始点)", self.show_f0_switch)
        toggle_layout.addRow("显示派生基频曲线", self.show_f0_derived_switch)
        toggle_layout.addRow("显示强度", self.show_intensity_switch)
        toggle_layout.addRow("显示共振峰", self.show_formants_switch)
        toggle_layout.addRow("突出显示 F1", self.highlight_f1_switch)
        
        analysis_layout.addWidget(self.analyze_button)
        analysis_layout.addWidget(self.analyze_formants_button)
        analysis_layout.addLayout(toggle_layout)
        
        left_layout.addWidget(self.settings_group)
        left_layout.addWidget(self.analysis_group)
        left_layout.addStretch()

        # --------------------------------------------------------------------
        # 中心部件 - 纯粹的可视化区域
        # --------------------------------------------------------------------
        self.center_panel = QWidget()
        center_layout = QVBoxLayout(self.center_panel)
        center_layout.setSpacing(0)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        self.waveform_widget = WaveformWidget()
        self.waveform_widget.setToolTip("音频波形概览。\n使用 Ctrl+鼠标滚轮 进行水平缩放。")
        self.spectrogram_widget = SpectrogramWidget()
        self.spectrogram_widget.setToolTip(
            "音频语谱图（声音的频谱随时间变化的可视化）。\n"
            "Y轴代表频率，X轴代表时间，颜色深浅代表该频率的能量强度。\n"
            "将鼠标悬停在图上可查看具体的时间和频率值。\n"
            "单击可进行单点共振峰分析。"
        )
        self.h_scrollbar = QScrollBar(Qt.Horizontal)
        self.h_scrollbar.setToolTip("在放大的视图中水平导航（平移）。")
        self.h_scrollbar.setEnabled(False)
        
        center_layout.addWidget(self.waveform_widget, 1)
        center_layout.addWidget(self.spectrogram_widget, 2)
        center_layout.addWidget(self.h_scrollbar)

        # --------------------------------------------------------------------
        # 右侧侧边栏 - 信息与播放
        # --------------------------------------------------------------------
        self.right_panel = QWidget()
        self.right_panel.setFixedWidth(300)
        right_layout = QVBoxLayout(self.right_panel)

        self.info_group = QGroupBox("音频信息")
        self.info_group.setToolTip("当前加载的音频文件的基本元数据。")
        info_layout = QFormLayout(self.info_group)
        self.filename_label, self.duration_label, self.samplerate_label, self.channels_label, self.bitdepth_label = [QLabel("N/A") for _ in range(5)]
        self.filename_label.setWordWrap(True)
        info_layout.addRow("文件名:", self.filename_label); info_layout.addRow("时长:", self.duration_label); info_layout.addRow("采样率:", self.samplerate_label); info_layout.addRow("通道数:", self.channels_label); info_layout.addRow("位深度:", self.bitdepth_label)

        self.playback_group = QGroupBox("播放控制")
        self.playback_group.setToolTip("控制当前音频的播放。")
        playback_layout = QVBoxLayout(self.playback_group)
        self.play_pause_btn, self.playback_slider, self.time_label = QPushButton("播放"), QSlider(Qt.Horizontal), QLabel("00:00.00 / 00:00.00")
        self.play_pause_btn.setToolTip("播放或暂停音频（快捷键：空格）")
        self.playback_slider.setToolTip("拖动以快进或后退。")
        self.play_pause_btn.setEnabled(False)
        self.playback_slider.setEnabled(False)
        playback_layout.addWidget(self.play_pause_btn); playback_layout.addWidget(self.playback_slider); playback_layout.addWidget(self.time_label)

        right_layout.addWidget(self.info_group)
        right_layout.addWidget(self.playback_group)
        right_layout.addStretch()

        # --------------------------------------------------------------------
        # 组装主布局
        # --------------------------------------------------------------------
        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(self.center_panel, 1)
        main_layout.addWidget(self.right_panel)

    def _connect_signals(self):
        self.play_pause_btn.clicked.connect(self.toggle_playback); self.player.positionChanged.connect(self.update_position); self.player.durationChanged.connect(self.update_duration); self.player.stateChanged.connect(self.on_player_state_changed); self.playback_slider.sliderMoved.connect(self.player.setPosition)
        self.waveform_widget.view_changed.connect(self.on_view_changed); self.h_scrollbar.valueChanged.connect(self.on_scrollbar_moved); self.density_slider.valueChanged.connect(self._update_density_label)
        self.analyze_button.clicked.connect(self.run_full_analysis); self.analyze_formants_button.clicked.connect(self.run_view_formant_analysis)
        [s.stateChanged.connect(self.update_overlays) for s in [self.show_f0_switch, self.show_intensity_switch, self.show_formants_switch]]
        self.highlight_f1_switch.stateChanged.connect(self.update_overlays)
        all_switches = [self.show_f0_switch, self.show_f0_derived_switch, self.show_intensity_switch, self.show_formants_switch, self.highlight_f1_switch]
        for switch in all_switches:
            switch.stateChanged.connect(self.update_overlays)

    def _update_density_label(self, value): self.density_label.setText(f"{self.DENSITY_LABELS[value]} (帧移: {self.DENSITY_MAP[value]})")
    def _get_hop_length_from_slider(self): return self.DENSITY_MAP[self.density_slider.value()]
    
    def update_overlays(self):
        self.spectrogram_widget.set_overlay_visibility(
            show_f0=self.show_f0_switch.isChecked(),
            show_f0_derived=self.show_f0_derived_switch.isChecked(), # 新增
            show_intensity=self.show_intensity_switch.isChecked(),
            show_formants=self.show_formants_switch.isChecked(),
            highlight_f1=self.highlight_f1_switch.isChecked()
        )
    
    def on_load_finished(self, result):
        if self.progress_dialog: self.progress_dialog.close()
        self.audio_data, self.sr, self.overview_data = result['y_full'], result['sr'], result['y_overview']
        info = sf.info(self.current_filepath); self.filename_label.setText(os.path.basename(self.current_filepath))
        self.known_duration = info.duration * 1000
        self.duration_label.setText(self.format_time(self.known_duration)); self.time_label.setText(f"00:00.00 / {self.format_time(self.known_duration)}")
        self.samplerate_label.setText(f"{info.samplerate} Hz")
        channel_desc = {1: "Mono", 2: "Stereo"}.get(info.channels, f"{info.channels} Channels"); self.channels_label.setText(f"{info.channels} ({channel_desc})")
        bit_depth_str = info.subtype.replace('PCM_', '') + "-bit PCM" if 'PCM' in info.subtype else info.subtype
        self.bitdepth_label.setText(bit_depth_str if bit_depth_str else "N/A")
        self.waveform_widget.set_audio_data(self.audio_data, self.sr, self.overview_data); self.player.setMedia(QMediaContent(QUrl.fromLocalFile(self.current_filepath)))
        self.playback_slider.setRange(0, int(self.known_duration)); self.play_pause_btn.setEnabled(True); self.playback_slider.setEnabled(True); self.analysis_group.setEnabled(True)

    def run_full_analysis(self):
        if self.audio_data is None: return
        self.run_task('analyze', audio_data=self.audio_data, sr=self.sr, hop_length=self._get_hop_length_from_slider(), progress_text="正在进行完整声学分析...")
    
    def run_view_formant_analysis(self):
        if self.audio_data is None: return
        start, end = self.waveform_widget._view_start_sample, self.waveform_widget._view_end_sample
        self.run_task('analyze_formants_view', audio_data=self.audio_data, sr=self.sr, start_sample=start, end_sample=end, hop_length=self._get_hop_length_from_slider(), progress_text="正在分析可见区域共振峰...")

    def on_analysis_finished(self, results):
        if self.progress_dialog: self.progress_dialog.close()
        hop_length = results.get('hop_length', 256)
        self.spectrogram_widget.set_data(results.get('S_db'), self.sr, hop_length)
        # [修改] 传递两组F0数据
        self.spectrogram_widget.set_analysis_data(
            f0_data=results.get('f0_raw'), 
            f0_derived_data=results.get('f0_derived'),
            intensity_data=results.get('intensity')
        )
        QMessageBox.information(self, "分析完成", "F0/强度/语谱图分析已完成。")
        
    def on_formant_view_finished(self, results):
        if self.progress_dialog: self.progress_dialog.close()
        formant_data = results.get('formants_view', [])
        
        # [修改] 调用 set_analysis_data，但只传入 formants_data
        # 新的 set_analysis_data 实现不会因此清除 F0 数据
        self.spectrogram_widget.set_analysis_data(formants_data=formant_data)
        
        QMessageBox.information(self, "分析完成", f"已在可见区域找到并显示了 {len(formant_data)} 个有效音框的共振峰。")
    
    def on_view_changed(self, start_sample, end_sample):
        if self.audio_data is None: self.h_scrollbar.setEnabled(False); return
        total_samples = len(self.audio_data); view_width = end_sample - start_sample
        self.h_scrollbar.setRange(0, total_samples - view_width); self.h_scrollbar.setPageStep(view_width); self.h_scrollbar.setValue(start_sample)
        self.h_scrollbar.setEnabled(total_samples > view_width)
        self.spectrogram_widget.set_view_window(start_sample, end_sample)
    
    def on_scrollbar_moved(self, value):
        if self.audio_data is None: return
        view_width = self.waveform_widget._view_end_sample - self.waveform_widget._view_start_sample
        self.waveform_widget.set_view_window(value, value + view_width)
        self.spectrogram_widget.set_view_window(value, value + view_width)

    def update_position(self, position):
        if not self.playback_slider.isSliderDown(): self.playback_slider.setValue(position)
        self.time_label.setText(f"{self.format_time(position)} / {self.format_time(self.known_duration)}")
        self.spectrogram_widget.update_playback_position(position)
    
    # [修复] 极大简化，只在极少数情况下作为备用，防止覆盖准确值
    def update_duration(self, duration):
        if duration > 0 and self.known_duration == 0: self.known_duration = duration

    def run_task(self, task_type, progress_text="正在处理...", **kwargs):
        if self.task_thread: QMessageBox.warning(self, "操作繁忙", "请等待当前分析任务完成后再试。"); return
        self.progress_dialog = QProgressDialog(progress_text, "取消", 0, 0, self); self.progress_dialog.setWindowModality(Qt.WindowModal); self.progress_dialog.show()
        self.task_thread = QThread(); self.worker = AudioTaskWorker(task_type, **kwargs); self.worker.moveToThread(self.task_thread)
        self.task_thread.started.connect(self.worker.run); self.worker.error.connect(self.on_task_error)
        if task_type == 'load': self.worker.finished.connect(self.on_load_finished)
        elif task_type == 'analyze': self.worker.finished.connect(self.on_analysis_finished)
        elif task_type == 'analyze_formants_view': self.worker.finished.connect(self.on_formant_view_finished)
        self.worker.finished.connect(self.task_thread.quit); self.worker.finished.connect(self.worker.deleteLater)
        self.task_thread.finished.connect(self.task_thread.deleteLater); self.task_thread.finished.connect(self.on_thread_finished)
        if self.progress_dialog: self.progress_dialog.canceled.connect(self.task_thread.requestInterruption)
        self.task_thread.start()
        
    def clear_all(self):
        if hasattr(self, 'progress_dialog') and self.progress_dialog and self.progress_dialog.isVisible(): self.progress_dialog.close()
        self.progress_dialog = None; 
        if self.player.state() != QMediaPlayer.StoppedState: self.player.stop()
        self.waveform_widget.clear(); self.spectrogram_widget.clear()
        for label in [self.filename_label, self.duration_label, self.samplerate_label, self.channels_label, self.bitdepth_label]: label.setText("N/A")
        self.time_label.setText("00:00.00 / 00:00.00"); self.play_pause_btn.setEnabled(False); self.playback_slider.setEnabled(False); self.analysis_group.setEnabled(False); self.density_slider.setValue(3)
        self.known_duration = 0; self.audio_data, self.sr, self.overview_data, self.current_filepath = None, None, None, None

    # Methods below are mostly helpers or event handlers without major changes in this revision
    def load_audio_file(self, filepath): self.clear_all(); self.current_filepath = filepath; self.run_task('load', filepath=filepath, progress_text=f"正在加载音频...")
    def dropEvent(self, event):
        if event.mimeData().hasUrls(): self.load_audio_file(event.mimeData().urls()[0].toLocalFile())
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and event.mimeData().urls()[0].isLocalFile():
            if event.mimeData().urls()[0].toLocalFile().lower().endswith(('.wav', '.mp3', '.flac', '.ogg', '.m4a')): event.acceptProposedAction()
    def on_thread_finished(self): self.task_thread, self.worker = None, None
    def on_task_error(self, error_msg):
        if hasattr(self, 'progress_dialog') and self.progress_dialog: self.progress_dialog.close()
        QMessageBox.critical(self, "任务失败", f"处理过程中发生错误:\n{error_msg}"); self.clear_all()
    def update_icons(self): 
        self.on_player_state_changed(self.player.state()); self.analyze_button.setIcon(self.icon_manager.get_icon("analyze"))
        formant_icon = self.icon_manager.get_icon("analyze_selection"); 
        if formant_icon.isNull(): formant_icon = self.icon_manager.get_icon("analyze")
        self.analyze_formants_button.setIcon(formant_icon)
    def on_player_state_changed(self, state):
        if state == QMediaPlayer.PlayingState: self.play_pause_btn.setIcon(self.icon_manager.get_icon("pause")); self.play_pause_btn.setText("暂停")
        else: self.play_pause_btn.setIcon(self.icon_manager.get_icon("play")); self.play_pause_btn.setText("播放")
    def toggle_playback(self):
        if self.player.state() == QMediaPlayer.PlayingState: self.player.pause()
        else: self.player.play()
    def format_time(self, ms):
        if ms <= 0: return "00:00.00"; 
        td = timedelta(milliseconds=ms); minutes, seconds = divmod(td.seconds, 60); milliseconds = td.microseconds // 10000
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:02d}"