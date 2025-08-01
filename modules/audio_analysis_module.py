from modules.custom_widgets_module import RangeSlider# --- START OF FILE modules/audio_analysis_module.py ---

# --- 模块元数据 ---
# 定义模块的名称和描述，用于在应用程序中显示。
MODULE_NAME = "音频分析"
MODULE_DESCRIPTION = "对单个音频文件进行声学分析，包括波形、语谱图、基频(F0)、强度和共振峰的可视化，并支持对长音频的流畅缩放与导航。"
# ---

import os
import re
import sys
from datetime import timedelta
import math # 新增导入，用于数学计算，如对数和向上取整
from modules.custom_widgets_module import RangeSlider, AnimatedSlider
# PyQt5 GUI 库的核心组件导入
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QMessageBox, QGroupBox, QFormLayout, QSizePolicy, QSlider,
                             QScrollBar, QProgressDialog, QFileDialog, QCheckBox, QLineEdit,
                             QMenu, QAction, QDialog, QDialogButtonBox, QComboBox, QShortcut,QScrollArea, QFrame) # 新增导入 QMenu, QAction, QDialog, QDialogButtonBox, QComboBox, QShortcut
from PyQt5.QtCore import Qt, QUrl, QPointF, QThread, pyqtSignal, QObject, pyqtProperty, QRect, QPoint
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPalette, QImage, QIntValidator, QPixmap, QRegion, QFont, QCursor, QKeySequence

# 模块级别依赖检查
# 尝试导入所有必需的第三方库。如果任何一个缺失，设置标志并捕获错误信息。
try:
    import numpy as np # 用于数值计算，特别是数组操作
    import soundfile as sf # 用于读取和写入音频文件
    import librosa # 用于音频分析，如F0、强度、语谱图和共振峰
    import pandas as pd # 用于数据处理，特别是F0后处理中的插值
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: audio_analysis_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)

# --- 后台工作器 ---
# AudioTaskWorker 类：在独立的线程中执行耗时的音频处理任务，以保持UI响应。
class AudioTaskWorker(QObject):
    # 定义信号，用于向主线程发送任务完成结果或错误信息
    chunk_finished = pyqtSignal(dict)
    finished = pyqtSignal(dict) # 任务成功完成时发送，携带结果字典
    error = pyqtSignal(str)     # 任务执行过程中发生错误时发送，携带错误信息字符串

    def __init__(self, task_type, filepath=None, audio_data=None, sr=None, **kwargs):
        """
        初始化后台工作器。
        Args:
            task_type (str): 要执行的任务类型 ('load', 'analyze', 'analyze_formants_view')。
            filepath (str, optional): 音频文件路径，用于 'load' 任务。
            audio_data (np.ndarray, optional): 音频数据数组，用于 'analyze' 和 'analyze_formants_view' 任务。
            sr (int, optional): 采样率，与 audio_data 配套。
            **kwargs: 其他任务特定的参数。
        """
        super().__init__()
        self.task_type = task_type
        self.filepath = filepath
        self.y = audio_data
        self.sr = sr
        self.kwargs = kwargs

    def run(self):
        """
        工作器的入口点，根据 task_type 调用相应的私有方法。
        所有耗时操作都在这里被封装，确保在独立的QThread中运行。
        """
        try:
            if self.task_type == 'load':
                self._run_load_task()
            elif self.task_type == 'analyze_acoustics':
                self._run_acoustics_task() # 调用新的声学分析方法
            elif self.task_type == 'analyze_spectrogram':
                self._run_spectrogram_task() # 调用新的语谱图分析方法
            elif self.task_type == 'analyze_formants_view':
                self._run_formant_view_task()
        except Exception as e:
            self.error.emit(str(e))

    def _run_load_task(self):
        """
        执行音频加载任务。
        使用 librosa.load 读取音频文件，并生成一个用于波形概览的下采样版本。
        """
        # 使用 librosa 加载音频，sr=None 表示使用原始采样率，mono=True 转换为单声道
        y, sr = librosa.load(self.filepath, sr=None, mono=True)

        # 生成用于概览视图的下采样数据
        overview_points = 4096 # 概览视图的目标点数
        if len(y) > overview_points:
            # 如果音频很长，则进行分块平均以创建概览波形
            chunk_size = len(y) // overview_points
            y_overview = np.array([np.mean(y[i:i+chunk_size]) for i in range(0, len(y), chunk_size)])
        else:
            # 如果音频较短，直接使用完整数据作为概览
            y_overview = y
        
        # 任务完成后，发出 finished 信号，携带加载的音频数据和采样率
        self.finished.emit({ 'y_full': y, 'sr': sr, 'y_overview': y_overview })

    def _run_acoustics_task(self):
        """
        [最终版 v2] 以可配置大小和重叠的块执行声学分析。
        集成了二次分析（提高速度）、强制hop_length（保证对齐）和重叠分块策略。
        """
        # --- 步骤 1: 参数准备 ---
        # 从UI线程传递过来的参数
        pre_emphasis = self.kwargs.get('pre_emphasis', False)
        user_f0_min = self.kwargs.get('f0_min', librosa.note_to_hz('C2'))
        user_f0_max = self.kwargs.get('f0_max', librosa.note_to_hz('C7'))
        forced_hop_length = self.kwargs.get('forced_hop_length')
        chunk_size_ms = self.kwargs.get('chunk_size_ms', 200)
        chunk_overlap_ms = self.kwargs.get('chunk_overlap_ms', 10)
        
        # 准备用于分析的音频数据
        y_analyzed = librosa.effects.preemphasis(self.y) if pre_emphasis else self.y

        # --- 步骤 2: 二次分析策略 - 快速全局粗分析以优化F0范围 ---
        final_f0_min, final_f0_max = user_f0_min, user_f0_max
        try:
            # 在一个极低采样率的音频副本上进行超快速分析
            y_coarse = librosa.resample(self.y, orig_sr=self.sr, target_sr=8000)
            f0_coarse, _, _ = librosa.pyin(
                y_coarse, fmin=30, fmax=1200, sr=8000,
                frame_length=1024, hop_length=512
            )
            valid_f0_coarse = f0_coarse[np.isfinite(f0_coarse)]

            if len(valid_f0_coarse) > 10:
                # 使用百分位数稳健地估计范围，抵抗离群点
                p5, p95 = np.percentile(valid_f0_coarse, [5, 95])
                padding = (p95 - p5) * 0.15 # 增加15%的边距
                
                # 更新F0范围，但确保不超出用户在UI上设定的范围
                final_f0_min = max(user_f0_min, p5 - padding)
                final_f0_max = min(user_f0_max, p95 + padding)
        except Exception:
            # 如果粗分析的任何步骤出错，都安全地回退到用户设定的原始范围
            pass

        # --- 步骤 3: 确定最终的 hop_length 以确保对齐 ---
        if forced_hop_length is not None:
            # 如果UI强制指定了hop_length（因为语谱图已存在），则必须使用它
            hop_length = forced_hop_length
        else:
            # 否则，根据UI上的渲染精細度计算
            render_density = self.kwargs.get('render_density', 4)
            narrow_band_window_s = 0.035
            base_n_fft_for_hop = 1 << (int(self.sr * narrow_band_window_s) - 1).bit_length()
            render_overlap_ratio = 1 - (1 / (2**render_density))
            hop_length = int(base_n_fft_for_hop * (1 - render_overlap_ratio)) or 1
        
        # --- 步骤 4: 定义重叠分块参数 ---
        chunk_size_samples = int((chunk_size_ms / 1000) * self.sr)
        overlap_samples = int((chunk_overlap_ms / 1000) * self.sr)
        
        # 步进大小是块大小减去重叠大小
        step_size_samples = chunk_size_samples - overlap_samples
        if step_size_samples <= 0: # 安全检查，防止无限循环
            step_size_samples = hop_length # 如果配置错误，则回退到hop_length步进
        
        frame_length = 1 << (int(self.sr * 0.040) - 1).bit_length()
        
        # --- 步骤 5: 使用 while 循环实现重叠步进分析 ---
        current_pos_samples = 0
        while current_pos_samples < len(self.y):
            if QThread.currentThread().isInterruptionRequested():
                self.finished.emit({})
                return

            # 提取当前块（包含重叠部分）
            start_sample = current_pos_samples
            end_sample = start_sample + chunk_size_samples
            y_chunk, y_chunk_analyzed = self.y[start_sample:end_sample], y_analyzed[start_sample:end_sample]

            if len(y_chunk) == 0: break

            # 使用优化后的F0范围和正确的hop_length进行精细分析
            f0_raw, voiced_flags, _ = librosa.pyin(
                y_chunk_analyzed, fmin=final_f0_min, fmax=final_f0_max, sr=self.sr,
                frame_length=frame_length, hop_length=hop_length
            )
            
            # F0后处理
            if len(f0_raw) > 0:
                f0_postprocessed = np.full_like(f0_raw, np.nan)
                voiced_ints = voiced_flags.astype(int)
                if len(voiced_ints) > 0:
                    starts, ends = np.where(np.diff(voiced_ints) == 1)[0] + 1, np.where(np.diff(voiced_ints) == -1)[0] + 1
                    if voiced_ints[0] == 1: starts = np.insert(starts, 0, 0)
                    if voiced_ints[-1] == 1: ends = np.append(ends, len(voiced_ints))
                    for start_idx, end_idx in zip(starts, ends):
                        if end_idx - start_idx > 2:
                            segment = f0_raw[start_idx:end_idx]; segment_series = pd.Series(segment)
                            interpolated_segment = segment_series.interpolate(method='linear', limit_direction='both', limit=2).to_numpy()
                            f0_postprocessed[start_idx:end_idx] = interpolated_segment
            else:
                f0_postprocessed = f0_raw
            
            intensity = librosa.feature.rms(y=y_chunk, frame_length=frame_length, hop_length=hop_length)[0]
            
            # 裁剪结果，只发送每个块中“新”的部分，以避免重绘
            num_frames_in_step = math.ceil(step_size_samples / hop_length)
            
            # 计算全局时间戳
            times_in_chunk = librosa.times_like(f0_raw, sr=self.sr, hop_length=hop_length)
            global_times = times_in_chunk + (start_sample / self.sr)
            
            # 发送裁剪后的块结果
            self.chunk_finished.emit({
                'f0_raw': (global_times[:num_frames_in_step], f0_raw[:num_frames_in_step]),
                'f0_derived': (global_times[:num_frames_in_step], f0_postprocessed[:num_frames_in_step]),
                'intensity': intensity[:num_frames_in_step],
            })
            
            # 步进到下一个块的起始位置
            current_pos_samples += step_size_samples

        # 所有块处理完毕，发送最终的完成信号
        self.finished.emit({'hop_length': hop_length})

    def _run_spectrogram_task(self):
        """
        执行语谱图分析任务。
        """
        # --- (这部分代码从原 _run_analyze_task 的后半部分提取) ---
        is_wide_band = self.kwargs.get('is_wide_band', False)
        render_density = self.kwargs.get('render_density', 4)
        pre_emphasis = self.kwargs.get('pre_emphasis', False)
        
        y_analyzed = librosa.effects.preemphasis(self.y) if pre_emphasis else self.y
        
        narrow_band_window_s = 0.035
        base_n_fft_for_hop = 1 << (int(self.sr * narrow_band_window_s) - 1).bit_length()
        render_overlap_ratio = 1 - (1 / (2**render_density))
        render_hop_length = int(base_n_fft_for_hop * (1 - render_overlap_ratio)) or 1

        spectrogram_window_s = 0.005 if is_wide_band else narrow_band_window_s
        n_fft_spectrogram = 1 << (int(self.sr * spectrogram_window_s) - 1).bit_length()
        
        D = librosa.stft(y_analyzed, hop_length=render_hop_length, n_fft=n_fft_spectrogram)
        S_db = librosa.amplitude_to_db(np.abs(D), ref=np.max)

        # [核心修改] 任务完成后，只发送语谱图结果
        self.finished.emit({
            'S_db': S_db,
            'hop_length': render_hop_length
        })

    def _run_formant_view_task(self):
        """
        执行仅分析可见区域共振峰的任务。
        """
        # 获取要分析的音频片段的起始和结束采样点
        start_sample, end_sample = self.kwargs.get('start_sample', 0), self.kwargs.get('end_sample', len(self.y))
        # 获取跳跃长度和是否预加重
        hop_length = self.kwargs.get('hop_length', 128)
        pre_emphasis = self.kwargs.get('pre_emphasis', False)
        
        # 提取当前视图内的音频数据
        y_view_orig = self.y[start_sample:end_sample]
        
        # 直接调用辅助函数进行共振峰分析
        formant_points = self._analyze_formants_helper(y_view_orig, self.sr, hop_length, start_sample, pre_emphasis)

        # 任务完成后，发出 finished 信号，携带共振峰数据
        self.finished.emit({'formants_view': formant_points})

    def _analyze_formants_helper(self, y_data, sr, hop_length, start_offset, pre_emphasis):
        """
        可复用的共振峰分析逻辑。
        Args:
            y_data (np.ndarray): 要分析的音频数据。
            sr (int): 采样率。
            hop_length (int): 帧之间的步长。
            start_offset (int): 当前 y_data 在原始音频中的起始采样点偏移量。
            pre_emphasis (bool): 是否应用预加重。
        Returns:
            list: 共振峰数据点列表，每个点是 (采样点位置, [F1, F2, F3...])。
        """
        # 根据是否预加重处理音频数据
        y_proc = librosa.effects.preemphasis(y_data) if pre_emphasis else y_data
        
        # 共振峰分析的帧长度和LPC阶数
        frame_length = int(sr * 0.025) # 25ms 帧长
        order = 2 + sr // 1000        # LPC 阶数，通常是 2 + 采样率(kHz)
        formant_points = []           # 存储找到的共振峰点

        # 计算RMS能量以进行语音/非语音判断
        rms = librosa.feature.rms(y=y_data, frame_length=frame_length, hop_length=hop_length)[0]
        # 能量阈值，低于此阈值的帧不进行共振峰分析
        energy_threshold = np.max(rms) * 0.05 if np.max(rms) > 0 else 0
        frame_index = 0

        # 遍历音频帧进行共振峰分析
        for i in range(0, len(y_proc) - frame_length, hop_length):
            # 跳过能量过低的帧（通常是静音或噪音）
            if frame_index < len(rms) and rms[frame_index] < energy_threshold:
                frame_index += 1
                continue

            y_frame = y_proc[i : i + frame_length] # 提取当前帧

            # 检查帧是否有效（非零且有限）
            if np.max(np.abs(y_frame)) < 1e-5 or not np.isfinite(y_frame).all():
                frame_index += 1
                continue

            try:
                # 使用线性预测编码 (LPC) 计算滤波器系数
                a = librosa.lpc(y_frame, order=order)
                if not np.isfinite(a).all(): 
                    frame_index += 1
                    continue
                
                # 找到LPC多项式的根，并只保留虚部大于等于0的根
                roots = [r for r in np.roots(a) if np.imag(r) >= 0]
                # 将根的相位角转换为频率 (Hz)，并排序
                freqs = sorted(np.angle(roots) * (sr / (2 * np.pi)))
                
                # 定义共振峰的典型频率范围
                formant_ranges = [(250, 800), (800, 2200), (2200, 3000), (3000, 4000)]
                found_formants = []
                candidate_freqs = list(freqs) # 复制一份，以便移除已找到的共振峰

                # 在预定义的频率范围内查找共振峰
                for f_min, f_max in formant_ranges:
                    band_freqs = [f for f in candidate_freqs if f_min <= f <= f_max]
                    if band_freqs:
                        best_f = band_freqs[0] # 通常取第一个找到的作为该范围的共振峰
                        found_formants.append(best_f)
                        candidate_freqs.remove(best_f) # 从候选列表中移除已找到的频率
                
                # 如果找到了共振峰，则添加到结果列表
                if found_formants:
                    # 记录共振峰的采样点位置 (帧中心) 和频率列表
                    formant_points.append((start_offset + i + frame_length // 2, found_formants))
            except Exception:
                # 捕获LPC或根计算中的异常，跳过当前帧
                frame_index += 1
                continue
            
            frame_index += 1
        
        return formant_points

# ExportDialog 类：用于设置图片导出选项的对话框
class ExportDialog(QDialog):
    """一个让用户选择导出图片分辨率和样式的对话框。"""
    def __init__(self, parent=None):
        """
        初始化导出对话框。
        Args:
            parent (QWidget, optional): 父控件。
        """
        super().__init__(parent)
        self.setWindowTitle("导出图片选项")
        
        layout = QFormLayout(self) # 使用表单布局

        # --- 分辨率部分 ---
        self.presets_combo = QComboBox() # 预设分辨率下拉框
        self.presets = {
            "当前窗口大小": None, # 表示使用当前窗口的尺寸
            "HD (1280x720)": (1280, 720),
            "Full HD (1920x1080)": (1920, 1080),
            "2K (2560x1440)": (2560, 1440),
            "4K (3840x2160)": (3840, 2160)
        }
        self.presets_combo.addItems(self.presets.keys()) # 添加预设选项
        # 连接信号，当预设改变时更新自定义输入框
        self.presets_combo.currentTextChanged.connect(self.on_preset_changed)
        
        custom_layout = QHBoxLayout() # 自定义分辨率输入框的水平布局
        self.width_input = QLineEdit("1920") # 宽度输入框
        self.width_input.setValidator(QIntValidator(100, 8000)) # 设置整数验证器
        self.height_input = QLineEdit("1080") # 高度输入框
        self.height_input.setValidator(QIntValidator(100, 8000)) # 设置整数验证器
        custom_layout.addWidget(QLabel("宽:"))
        custom_layout.addWidget(self.width_input)
        custom_layout.addWidget(QLabel("高:"))
        custom_layout.addWidget(self.height_input)
        custom_layout.addWidget(QLabel("px"))
        
        layout.addRow("分辨率:", self.presets_combo) # 添加分辨率预设行
        layout.addRow("自定义:", custom_layout)      # 添加自定义分辨率行
        
        # --- 新增: 样式选项 ---
        options_group = QGroupBox("样式选项") # 样式选项分组框
        options_layout = QVBoxLayout(options_group) # 样式选项的垂直布局
        
        self.info_label_check = QCheckBox("添加信息标签") # 是否添加信息标签的复选框
        self.info_label_check.setToolTip("在图片的右上角添加包含文件名、时长等基本信息的标签。")
        self.info_label_check.setChecked(True) # 默认选中

        self.time_axis_check = QCheckBox("在底部添加时间轴") # 是否添加时间轴的复选框
        self.time_axis_check.setToolTip("在图片底部渲染一个与视图范围匹配的时间轴。")
        self.time_axis_check.setChecked(True) # 默认选中
        
        options_layout.addWidget(self.info_label_check)
        options_layout.addWidget(self.time_axis_check)
        
        layout.addWidget(options_group) # 将样式选项分组框添加到主布局

        # --- 按钮部分 ---
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel) # 确定/取消按钮
        button_box.accepted.connect(self.accept) # 连接接受信号
        button_box.rejected.connect(self.reject) # 连接拒绝信号
        layout.addWidget(button_box)

        # 初始化状态：根据当前选中的预设更新输入框的启用状态
        self.on_preset_changed(self.presets_combo.currentText())

    def on_preset_changed(self, text):
        """
        当分辨率预设改变时调用，更新自定义宽度和高度输入框的启用状态。
        Args:
            text (str): 当前选中的预设文本。
        """
        resolution = self.presets.get(text)
        if resolution:
            # 如果是预设，设置输入框的值并禁用
            self.width_input.setText(str(resolution[0]))
            self.height_input.setText(str(resolution[1]))
            self.width_input.setEnabled(False)
            self.height_input.setEnabled(False)
        else:
            # 如果是“当前窗口大小”，启用输入框
            self.width_input.setEnabled(True)
            self.height_input.setEnabled(True)

    def get_options(self):
        """
        获取用户选择的所有导出选项。
        Returns:
            dict: 包含 'resolution', 'info_label', 'add_time_axis' 的字典。
        """
        resolution = None
        if self.presets_combo.currentText() != "当前窗口大小":
            try:
                # 尝试将自定义输入框的文本转换为整数分辨率
                resolution = (int(self.width_input.text()), int(self.height_input.text()))
            except ValueError:
                # 如果转换失败，使用默认值
                resolution = (1920, 1080)

        return {
            "resolution": resolution,
            "info_label": self.info_label_check.isChecked(),
            "add_time_axis": self.time_axis_check.isChecked()
        }

# TimeAxisWidget 类：显示动态时间轴的控件
class TimeAxisWidget(QWidget):
    """一个用于在波形和语谱图之间显示动态时间轴的控件。"""
    def __init__(self, parent=None):
        """
        初始化时间轴控件。
        Args:
            parent (QWidget, optional): 父控件。
        """
        super().__init__(parent)
        self.setFixedHeight(25) # 固定高度
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed) # 宽度可扩展，高度固定
        
        # 视图范围和采样率，默认为0和1，防止除以零
        self._view_start_sample = 0
        self._view_end_sample = 1
        self._sr = 1
        
        # 默认颜色，会在 update_view 中根据主题更新
        self.font_color = QColor(Qt.black)
        self.line_color = QColor(Qt.darkGray)

    def update_view(self, start_sample, end_sample, sr):
        """
        更新视图范围和采样率，并触发重绘。
        Args:
            start_sample (int): 当前视图的起始采样点。
            end_sample (int): 当前视图的结束采样点。
            sr (int): 音频采样率。
        """
        self._view_start_sample = start_sample
        self._view_end_sample = end_sample
        self._sr = sr
        
        # 根据当前调色板更新字体和线条颜色，以适应不同的主题
        self.font_color = self.palette().color(QPalette.Text)
        self.line_color = self.palette().color(QPalette.Mid)
        self.update() # 触发 paintEvent 重绘

    def paintEvent(self, event):
        """
        绘制时间轴的内容。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing) # 开启抗锯齿，使线条和文字更平滑
        
        rect = self.rect() # 获取控件的绘制区域
        painter.fillRect(rect, self.palette().color(QPalette.Window)) # 填充背景色

        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0 or self._sr <= 1:
            # 如果视图宽度无效或采样率过低，则不绘制
            return

        view_duration_s = view_width_samples / self._sr # 当前视图的时长（秒）
        start_time_s = self._view_start_sample / self._sr # 当前视图的起始时间（秒）
        
        # --- 智能刻度计算 ---
        # 目标是在屏幕上显示5-10个主刻度
        target_ticks = 10
        raw_interval = view_duration_s / target_ticks # 原始刻度间隔

        # 将原始间隔规整到人类友好的单位 (1, 2, 5的倍数)，例如 0.1s, 0.2s, 0.5s, 1s, 2s, 5s...
        power = 10.0 ** math.floor(math.log10(raw_interval)) # 找到最接近的10的幂
        if raw_interval / power < 1.5:
            interval = 1 * power
        elif raw_interval / power < 3.5:
            interval = 2 * power
        elif raw_interval / power < 7.5:
            interval = 5 * power
        else:
            interval = 10 * power

        # 设置绘图属性
        painter.setPen(QPen(self.line_color, 1)) # 设置线条颜色和粗细
        font = self.font()
        font.setPointSize(8) # 设置字体大小
        painter.setFont(font)
        
        # 确定第一个刻度的起始时间，确保它是 interval 的倍数且在视图范围内
        first_tick_time = math.ceil(start_time_s / interval) * interval

        # 绘制足够多的刻度以覆盖整个视图范围
        for i in range(int(target_ticks * 2)):
            tick_time = first_tick_time + i * interval
            if tick_time > start_time_s + view_duration_s:
                break # 超出视图范围则停止

            # 将时间转换为X坐标
            x_pos = (tick_time - start_time_s) / view_duration_s * rect.width()
            
            # 绘制主刻度线
            painter.drawLine(int(x_pos), rect.height() - 8, int(x_pos), rect.height())
            
            # 绘制时间标签，格式化为两位小数
            label = f"{tick_time:.2f}"
            
            painter.setPen(self.font_color) # 切换到字体颜色
            # 绘制文本，居中对齐，并留出底部空间
            painter.drawText(QRect(int(x_pos) - 30, 0, 60, rect.height() - 10), Qt.AlignCenter, label)
            painter.setPen(self.line_color) # 换回线条颜色


# SpectrogramWidget 类：核心细节视图，显示语谱图和叠加的声学特征
class SpectrogramWidget(QWidget):
    # 定义信号，用于与主页面通信
    selectionChanged = pyqtSignal(object)          # 选区改变时发送，携带 (start, end) 元组或 None
    zoomToSelectionRequested = pyqtSignal(int, int) # 请求缩放到选区时发送，携带起始和结束采样点
    exportViewAsImageRequested = pyqtSignal()      # 请求导出当前视图为图片时发送
    exportAnalysisToCsvRequested = pyqtSignal()    # 请求导出分析数据为CSV时发送
    exportSelectionAsWavRequested = pyqtSignal()   # 请求导出选区音频为WAV时发送
    spectrumSliceRequested = pyqtSignal(int)       # 请求显示频谱切片时发送，携带采样点位置

    def __init__(self, parent, icon_manager):
        """
        初始化语谱图控件。
        Args:
            parent (QWidget): 父控件。
            icon_manager (IconManager): 图标管理器实例，用于获取图标。
        """
        super().__init__(parent)
        self.icon_manager = icon_manager # 保存 icon_manager 实例
        self.setMinimumHeight(150) # 设置最小高度
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding) # 宽度和高度都可扩展
        self.setMouseTracking(True) # 开启鼠标跟踪以实时更新信息（鼠标移动时触发 mouseMoveEvent）
        
        # 选区相关属性
        self._is_selecting = False      # 标记是否正在进行鼠标拖动选择
        self._selection_start_x = 0     # 存储起始点的像素X坐标 (用于拖动绘制)
        self._selection_end_x = 0       # 存储结束点的像素X坐标 (用于拖动绘制)
        self._selection_start_sample = None # 最终确定的起始采样点 (音频数据索引)
        self._selection_end_sample = None   # 最终确定的结束采样点 (音频数据索引)
        
        # 选区颜色属性
        self._selectionColor = QColor(135, 206, 250, 60) # 淡蓝色半透明填充
        self._selectionBorderColor = QColor(255, 0, 0, 200) # 醒目的红色边界

        # --- 其他所有旧属性保持不变 ---
        self.spectrogram_image = None # 存储语谱图的QImage
        self._view_start_sample, self._view_end_sample = 0, 1 # 当前视图窗口的采样点范围
        self.sr, self.hop_length = 1, 256 # 采样率和语谱图跳跃长度
        self._playback_pos_sample = -1 # 播放光标位置 (采样点)
        
        # 分析数据存储
        self._f0_data = None         # 原始F0数据 (times, f0_raw_values)
        self._intensity_data = None  # 强度数据 (numpy array)
        self._formants_data = []     # 共振峰数据 [(sample_pos, [F1, F2, F3...]), ...]
        self._f0_derived_data = None # 派生F0数据 (times, f0_interpolated_values)

        # 叠加层可见性控制标志
        self._show_f0, self._show_f0_points, self._show_f0_derived = False, True, True
        self._show_intensity, self._smooth_intensity = False, False
        self._show_formants, self._highlight_f1, self._highlight_f2, self._show_other_formants = False, True, True, True
        
        self.max_display_freq = 5000 # 语谱图Y轴最大显示频率
        self._cursor_info_text = "" # 鼠标悬停时显示的信息文本
        self.waveform_sibling = None # 引用波形控件，用于滚动同步 (已废弃，但保留兼容性)
        self._f0_display_min, self._f0_display_max = 75, 400 # F0 Y轴显示范围
        self._f0_axis_enabled = False # 是否显示F0右侧轴
        # [新增] F0轴模式管理
        self._f0_axis_is_auto = True # 默认是自动模式
        self._manual_f0_min = 75
        self._manual_f0_max = 400
        self._info_box_position = 'top_left' # 悬浮信息框位置 ('top_left' 或 'bottom_right')

        # QSS可控颜色属性 (确保这些属性在QSS中可以被覆盖，以便通过样式表改变颜色)
        self._backgroundColor = Qt.white
        self._spectrogramMinColor, self._spectrogramMaxColor = Qt.white, Qt.black # 语谱图颜色映射范围
        self._intensityColor = QColor("#4CAF50") # 强度曲线颜色 (绿色)
        self._f0Color = QColor("#FFA726") # 原始F0点颜色 (橙色)
        self._f0DerivedColor = QColor(150, 150, 255, 150) # 派生F0曲线颜色 (半透明蓝色)
        self._f1Color = QColor("#FF6F00") # F1共振峰颜色 (深橙色)
        self._f2Color = QColor("#9C27B0") # F2共振峰颜色 (紫色)
        self._formantColor = QColor("#29B6F6") # 其他共振峰颜色 (亮蓝色)
        self._cursorColor = QColor("red") # 播放/鼠标光标颜色
        self._infoTextColor = Qt.white # 信息框文字颜色
        self._infoBackgroundColor = QColor(0, 0, 0, 150) # 信息框背景颜色 (半透明黑色)
        self._f0AxisColor = QColor(150, 150, 150) # F0轴/网格线颜色 (灰色)

    # --- @pyqtProperty 装饰器和 set_overlay_visibility 方法 ---
    # 这些属性允许通过QSS（Qt Style Sheets）来设置控件的颜色，实现主题化。
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

    @pyqtProperty(QColor) # 新增属性：选区填充颜色
    def selectionColor(self): return self._selectionColor
    @selectionColor.setter
    def selectionColor(self, color): self._selectionColor = color; self.update()

    @pyqtProperty(QColor) # 新增属性：选区边框颜色
    def selectionBorderColor(self): return self._selectionBorderColor
    @selectionBorderColor.setter
    def selectionBorderColor(self, color): self._selectionBorderColor = color; self.update()
    
    def set_overlay_visibility(self, show_f0, show_f0_points, show_f0_derived,
                               show_intensity, smooth_intensity,
                               show_formants, highlight_f1, highlight_f2, show_other_formants):
        """
        设置所有叠加层的可见性。
        Args:
            show_f0 (bool): 是否显示F0总开关。
            show_f0_points (bool): 是否显示原始F0点。
            show_f0_derived (bool): 是否显示派生F0曲线。
            show_intensity (bool): 是否显示强度曲线。
            smooth_intensity (bool): 是否平滑强度曲线。
            show_formants (bool): 是否显示共振峰总开关。
            highlight_f1 (bool): 是否突出显示F1。
            highlight_f2 (bool): 是否突出显示F2。
            show_other_formants (bool): 是否显示F3及以上共振峰。
        """
        self._show_f0, self._show_f0_points, self._show_f0_derived = show_f0, show_f0_points, show_f0_derived
        self._show_intensity, self._smooth_intensity = show_intensity, smooth_intensity
        self._show_formants, self._highlight_f1, self._highlight_f2, self._show_other_formants = show_formants, highlight_f1, highlight_f2, show_other_formants
        self.update() # 触发重绘以应用新的可见性设置

    def set_f0_axis_range(self, lower=None, upper=None):
        """
        [新增] 设置F0轴的显示范围模式。
        如果提供了 lower 和 upper，则进入手动模式；否则，切换到自动模式。
        """
        if lower is not None and upper is not None:
            self._f0_axis_is_auto = False
            self._manual_f0_min = lower
            self._manual_f0_max = upper
            self._f0_display_min = lower
            self._f0_display_max = upper
        else:
            self._f0_axis_is_auto = True
            # 切换到自动模式时，立即用现有的F0数据重新计算范围
            self._calculate_and_apply_auto_f0_range()
        
        self.update()

    def _calculate_and_apply_auto_f0_range(self):
        """
        [新增] 提取出来的、根据当前F0数据计算并应用自动范围的逻辑。
        """
        if self._f0_data:
            times, f0_values = self._f0_data
            valid_f0 = f0_values[np.isfinite(f0_values)]
            
            if len(valid_f0) > 1:
                actual_min, actual_max = np.min(valid_f0), np.max(valid_f0)
                data_range = actual_max - actual_min
                padding = max(10, data_range * 0.1)
                padded_min = actual_min - padding
                padded_max = actual_max + padding
                current_range = padded_max - padded_min
                if current_range < 100:
                    center = (padded_max + padded_min) / 2
                    padded_min = center - 50
                    padded_max = center + 50
                
                self._f0_display_min = max(0, padded_min)
                self._f0_display_max = padded_max
                self._f0_axis_enabled = True
            else: 
                self._f0_display_min, self._f0_display_max = 75, 400
                self._f0_axis_enabled = False
        else:
            self._f0_data = None
            self._f0_axis_enabled = False

    def set_selection(self, selection_tuple):
        """
        公共槽函数，用于从外部设置选区。
        Args:
            selection_tuple (tuple or None): (start_sample, end_sample) 元组表示选区，或 None 表示清除选区。
        """
        if selection_tuple:
            self._selection_start_sample, self._selection_end_sample = selection_tuple
        else:
            self._selection_start_sample = None
            self._selection_end_sample = None
        self.update() # 触发重绘以更新选区显示

    def update_formants_data(self, formants_data, clear_previous=True):
        """
        [新增] 专门用于更新共振峰数据层，而不影响F0或强度等其他分析层。

        Args:
            formants_data (list): 新的共振峰数据点。
            clear_previous (bool): 如果为True，则替换所有现有的共振峰数据。
                                   如果为False，则将新数据追加到现有数据后面。
        """
        if formants_data is not None:
            if clear_previous:
                self._formants_data = formants_data
            else:
                self._formants_data.extend(formants_data)
        elif clear_previous:
            # 如果传入的数据为None，但要求清除，则清空列表
            self._formants_data = []

        # 触发重绘以在UI上显示更改
        self.update()


    def _get_plot_rect(self):
        """
        辅助函数，获取绘图安全区。
        绘图区会留出左右两侧的边距，用于显示频率轴和F0轴。
        Returns:
            QRect: 绘图区域的矩形。
        """
        padding_left, padding_right = 45, 45
        padding_top, padding_bottom = 10, 10
        return self.rect().adjusted(padding_left, padding_top, -padding_right, -padding_bottom)

    def _pixel_to_sample(self, x_pixel):
        """
        辅助函数，将绘图区内的像素X坐标转换为音频采样点索引。
        Args:
            x_pixel (int): 像素X坐标。
        Returns:
            int: 对应的音频采样点索引。
        """
        plot_rect = self._get_plot_rect()
        if not plot_rect.isValid() or plot_rect.width() <= 0:
            return 0 # 无效绘图区，返回0

        # 将输入x限制在绘图区内，防止计算溢出
        x_clamped = max(plot_rect.left(), min(x_pixel, plot_rect.right()))
        
        view_width_samples = self._view_end_sample - self._view_start_sample
        x_ratio = (x_clamped - plot_rect.left()) / plot_rect.width() # 计算像素在绘图区内的比例
        sample_offset = x_ratio * view_width_samples # 计算相对于视图起始采样点的偏移量
        return int(self._view_start_sample + sample_offset) # 返回实际采样点

    def _sample_to_pixel(self, sample_index):
        """
        辅助函数，将音频采样点索引转换为绘图区内的像素X坐标。
        Args:
            sample_index (int): 音频采样点索引。
        Returns:
            int: 对应的像素X坐标。
        """
        plot_rect = self._get_plot_rect()
        if not plot_rect.isValid():
            return 0 # 无效绘图区，返回0
        
        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0: # 避免除以零
            return plot_rect.left()

        sample_offset = sample_index - self._view_start_sample # 计算相对于视图起始采样点的偏移量
        x_ratio = sample_offset / view_width_samples # 计算采样点在视图内的比例
        return int(plot_rect.left() + x_ratio * plot_rect.width()) # 返回实际像素X坐标

    def paintEvent(self, event):
        """
        绘制语谱图及其所有叠加层。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing) # 开启抗锯齿
        painter.fillRect(self.rect(), self._backgroundColor) # 填充背景色

        plot_rect = self._get_plot_rect() # 获取绘图安全区
        
        if not plot_rect.isValid(): return # 如果绘图区无效，则不绘制

        w, h = plot_rect.width(), plot_rect.height() # 绘图区宽度和高度
        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0: return # 如果视图宽度无效，则不绘制

        # --- 绘制语谱图背景 ---
        if self.spectrogram_image:
            # 计算语谱图图像中需要绘制的起始和结束帧
            start_frame = self._view_start_sample // self.hop_length
            end_frame = self._view_end_sample // self.hop_length
            view_width_frames = end_frame - start_frame
            if view_width_frames > 0:
                # 定义语谱图图像中的源矩形（要绘制的部分）
                source_rect = QRect(start_frame, 0, view_width_frames, self.spectrogram_image.height())
                # 将源矩形的内容绘制到控件的绘图区
                painter.drawImage(plot_rect, self.spectrogram_image, source_rect)

        # --- 绘制坐标轴和网格线 ---
        painter.setPen(QPen(self._f0AxisColor, 1, Qt.DotLine)) # 设置网格线颜色和样式
        font = self.font()
        font.setPointSize(8) # 设置字体大小
        painter.setFont(font)
        
        # 左侧频率轴 (Hz)
        # 从0Hz到最大显示频率，每隔1000Hz绘制一个刻度
        for freq in range(0, int(self.max_display_freq) + 1, 1000):
            if freq == 0 and self.max_display_freq > 0: # 避免0Hz刻度文本与底部重叠
                continue
            # 计算频率对应的Y坐标
            y = plot_rect.bottom() - (freq / self.max_display_freq * h)
            painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y)) # 绘制水平网格线
            painter.drawText(QPointF(plot_rect.left() - 35, int(y) + 4), f"{freq}") # 绘制频率标签
        
        # 右侧基频轴 (Hz)
        if self._f0_axis_enabled:
            f0_display_range = self._f0_display_max - self._f0_display_min
            if f0_display_range > 0:
                # 根据F0显示范围动态调整刻度步长
                step = 50 if f0_display_range > 200 else 25 if f0_display_range > 100 else 10
                
                # [核心修改] 获取当前绘图字体的度量信息
                metrics = painter.fontMetrics()
                text_height = metrics.height() # 获取字体的高度
                
                for freq in range(int(self._f0_display_min // step * step), int(self._f0_display_max) + 1, step):
                    if freq < self._f0_display_min: continue
                    
                    y = plot_rect.bottom() - ((freq - self._f0_display_min) / f0_display_range * h)
                    painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y)) # 绘制水平网格线
                    
                    # 绘制F0标签，右侧对齐
                    # [核心修改] 调整绘制区域的Y坐标和高度
                    # Y坐标：int(y) - text_height // 2，使其垂直居中于刻度线
                    # 高度：text_height，确保有足够空间
                    painter.drawText(
                        QRect(plot_rect.right() + 5, int(y) - text_height // 2, 
                              plot_rect.right() - plot_rect.left() - 10, text_height), # 使用动态计算的高度
                        Qt.AlignLeft | Qt.AlignVCenter, 
                        f"{freq}"
                    )

        # --- 在plot_rect内绘制所有叠加层 ---
        # 强度曲线
        if self._show_intensity and self._intensity_data is not None:
            painter.setPen(QPen(self._intensityColor, 2)) # 设置强度曲线颜色和粗细
            intensity_points = []
            data_to_plot = self._intensity_data
            if self._smooth_intensity:
                # 如果启用平滑，则应用滚动平均
                data_to_plot = pd.Series(data_to_plot).rolling(window=5, center=True, min_periods=1).mean().to_numpy()
            
            # 归一化强度数据以便映射到Y轴
            max_intensity = np.max(data_to_plot) if len(data_to_plot) > 0 else 1.0
            if max_intensity == 0: max_intensity = 1.0 # 避免除以零
            
            for i, val in enumerate(data_to_plot):
                sample_pos = i * self.hop_length # 计算采样点位置
                if self._view_start_sample <= sample_pos < self._view_end_sample:
                    # 将采样点位置映射到X坐标
                    x = plot_rect.left() + (sample_pos - self._view_start_sample) * w / view_width_samples
                    # 将强度值映射到Y坐标 (只占用绘图区底部30%的高度)
                    y = plot_rect.bottom() - (val / max_intensity * h * 0.3) 
                    intensity_points.append(QPointF(x, y))
            if len(intensity_points) > 1:
                painter.drawPolyline(*intensity_points) # 绘制强度曲线

        # 基频曲线 (F0)
        if self._show_f0 and self._f0_axis_enabled and f0_display_range > 0:
            if self._show_f0_derived and self._f0_derived_data:
                painter.setPen(QPen(self._f0DerivedColor, 1.5, Qt.DashLine)) # 派生F0曲线样式
                derived_points = []
                derived_times, derived_f0 = self._f0_derived_data
                for i, t in enumerate(derived_times):
                    sample_pos = t * self.sr # 时间转换为采样点
                    if self._view_start_sample <= sample_pos < self._view_end_sample and np.isfinite(derived_f0[i]):
                        # 将采样点和F0值映射到X,Y坐标
                        x = plot_rect.left() + (sample_pos - self._view_start_sample) * w / view_width_samples
                        y = plot_rect.bottom() - ((derived_f0[i] - self._f0_display_min) / f0_display_range * h)
                        derived_points.append(QPointF(x, y))
                if len(derived_points) > 1:
                    painter.drawPolyline(*derived_points) # 绘制派生F0曲线

            if self._show_f0_points and self._f0_data:
                painter.setPen(Qt.NoPen) # 不绘制边框
                painter.setBrush(self._f0Color) # 设置填充颜色
                raw_times, raw_f0 = self._f0_data
                for i, t in enumerate(raw_times):
                    sample_pos = t * self.sr
                    if self._view_start_sample <= sample_pos < self._view_end_sample and np.isfinite(raw_f0[i]):
                        # 将采样点和F0值映射到X,Y坐标
                        x = plot_rect.left() + (sample_pos - self._view_start_sample) * w / view_width_samples
                        y = plot_rect.bottom() - ((raw_f0[i] - self._f0_display_min) / f0_display_range * h)
                        painter.drawEllipse(QPointF(x, y), 2.5, 2.5) # 绘制原始F0点 (小圆点)
        
        # 共振峰点
        if self._show_formants and self._formants_data:
            max_freq_y_axis = self.max_display_freq # Y轴最大频率
            for sample_pos, formants in self._formants_data:
                if self._view_start_sample <= sample_pos < self._view_end_sample:
                    # 将采样点位置映射到X坐标
                    x = plot_rect.left() + (sample_pos - self._view_start_sample) * w / view_width_samples
                    for i, f in enumerate(formants):
                        brush, should_draw, is_highlighted = None, False, False
                        # 根据共振峰索引和设置选择颜色和是否高亮
                        if i == 0 and self._highlight_f1:
                            brush, should_draw, is_highlighted = self._f1Color, True, True
                        elif i == 1 and self._highlight_f2:
                            brush, should_draw, is_highlighted = self._f2Color, True, True
                        elif i > 1 and self._show_other_formants:
                            brush, should_draw, is_highlighted = self._formantColor, True, False
                        
                        if should_draw:
                            # 将共振峰频率映射到Y坐标
                            y = plot_rect.bottom() - (f / max_freq_y_axis * h)
                            if plot_rect.top() <= y <= plot_rect.bottom(): # 确保点在可见范围内
                                if is_highlighted:
                                    painter.setPen(QPen(Qt.red, 1)) # F1/F2高亮描边
                                    painter.setBrush(Qt.NoBrush)
                                    painter.drawEllipse(QPointF(x, y), 3, 3) # 绘制高亮外圈
                                painter.setPen(Qt.NoPen)
                                painter.setBrush(brush)
                                painter.drawEllipse(QPointF(x, y), 2.5, 2.5) # 绘制共振峰点

        # 播放光标
        if self._view_start_sample <= self._playback_pos_sample < self._view_end_sample:
            # 计算播放光标的X坐标
            pos_x = plot_rect.left() + (self._playback_pos_sample - self._view_start_sample) * w / view_width_samples
            painter.setPen(QPen(self._cursorColor, 2)) # 设置光标颜色和粗细
            painter.drawLine(int(pos_x), 0, int(pos_x), self.height()) # 绘制垂直光标线

        # --- 核心修改: 绘制一维区间选区 ---
        start_x_pixel, end_x_pixel = 0, 0
        # 判断是正在拖动中，还是已有一个确定的选区
        if self._is_selecting:
            start_x_pixel = self._selection_start_x
            end_x_pixel = self._selection_end_x
        elif self._selection_start_sample is not None and self._selection_end_sample is not None:
            # 将选区的采样点转换为像素坐标
            start_x_pixel = self._sample_to_pixel(self._selection_start_sample)
            end_x_pixel = self._sample_to_pixel(self._selection_end_sample)

        if start_x_pixel != end_x_pixel: # 只有当选区有宽度时才绘制
            # 保证 x1 < x2，方便绘制矩形
            x1 = min(start_x_pixel, end_x_pixel)
            x2 = max(start_x_pixel, end_x_pixel)
            
            # 1. 绘制半透明的填充矩形 (覆盖整个控件高度)
            selection_fill_rect = QRect(x1, 0, x2 - x1, self.height())
            painter.setPen(Qt.NoPen) # 不绘制边框
            painter.setBrush(self._selectionColor) # 设置填充颜色
            painter.drawRect(selection_fill_rect) # 绘制填充矩形

            # 2. 绘制两侧的红色边界线 (覆盖整个控件高度)
            pen = QPen(self._selectionBorderColor, 1.5) # 粗细1.5像素的红色线
            painter.setPen(pen)
            
            # 左边界线
            painter.drawLine(x1, 0, x1, self.height())
            # 右边界线
            painter.drawLine(x2, 0, x2, self.height())


        # --- 悬浮信息框的绘制 ---
        if self._cursor_info_text:
            font = self.font()
            font.setPointSize(10)
            painter.setFont(font)
            metrics = painter.fontMetrics() # 获取字体度量信息
            
            # 先计算文本矩形的大小
            text_rect = metrics.boundingRect(QRect(0, 0, self.width(), self.height()), Qt.AlignLeft, self._cursor_info_text)
            text_rect.adjust(-5, -5, 5, 5) # 添加内边距

            # 根据信息框位置决定绘制位置
            margin = 10
            if self._info_box_position == 'top_left':
                text_rect.moveTo(margin, margin)
            else: # 'bottom_right'
                text_rect.moveTo(self.width() - text_rect.width() - margin, 
                                 self.height() - text_rect.height() - margin)

            painter.setBrush(self._infoBackgroundColor) # 设置背景填充色
            painter.setPen(Qt.NoPen) # 不绘制边框
            painter.drawRoundedRect(text_rect, 5, 5) # 绘制圆角矩形背景
            
            painter.setPen(self._infoTextColor) # 设置文字颜色
            painter.drawText(text_rect, Qt.AlignCenter, self._cursor_info_text) # 绘制文本

    # --- 核心修改: 鼠标事件处理 ---
    def mousePressEvent(self, event):
        """
        处理鼠标按下事件，开始选区拖动。
        """
        if self.spectrogram_image is None:
            return # 如果没有加载语谱图，则不处理

        # 如果鼠标点击在左右两侧的轴上（绘图区外），则清除选区
        plot_rect = self._get_plot_rect()
        if not plot_rect.contains(event.pos()):
            if event.x() < plot_rect.left() or event.x() > plot_rect.right():
                if self._selection_start_sample is not None:
                    self._selection_start_sample = None
                    self._selection_end_sample = None
                    self.selectionChanged.emit(None) # 通知上层选区已清除
                    self.update()
                return

        if event.button() == Qt.LeftButton:
            self._is_selecting = True # 设置正在选择标志
            # 记录起始和结束的像素X坐标
            self._selection_start_x = event.pos().x()
            self._selection_end_x = event.pos().x()
            
            # 开始新的选择时，清除旧的采样点选区
            if self._selection_start_sample is not None:
                self._selection_start_sample = None
                self._selection_end_sample = None
                self.selectionChanged.emit(None) # 通知上层选区已清除
            self.update() # 触发重绘以显示新的选区状态
        
        super().mousePressEvent(event) # 调用父类的事件处理

    def mouseMoveEvent(self, event):
        """
        处理鼠标移动事件，更新选区或悬浮信息。
        """
        if self._is_selecting:
            self._selection_end_x = event.pos().x() # 更新选区结束的像素X坐标
            self.update() # 触发重绘以实时更新选区显示
        
        # 原有的悬停信息逻辑
        if self.spectrogram_image is None:
            super().mouseMoveEvent(event)
            return
        
        plot_rect = self._get_plot_rect()
        
        # 将鼠标位置的像素坐标转换为数据坐标 (时间、频率)
        x_ratio = (event.x() - plot_rect.left()) / plot_rect.width()
        y_ratio = (plot_rect.bottom() - event.y()) / plot_rect.height()
        
        # 限制在0-1之间，避免鼠标移出绘图区时数据异常
        x_ratio = max(0.0, min(1.0, x_ratio)) 
        y_ratio = max(0.0, min(1.0, y_ratio)) 
        
        view_width_samples = self._view_end_sample - self._view_start_sample
        if view_width_samples <= 0: return # 避免除以零

        current_sample = self._view_start_sample + x_ratio * view_width_samples # 当前鼠标位置的采样点
        current_time_s = current_sample / self.sr # 当前鼠标位置的时间（秒）
        current_freq_hz = y_ratio * self.max_display_freq # 当前鼠标位置的频率（Hz）

        info_parts = [f"Time: {current_time_s:.3f} s", f"Freq: {current_freq_hz:.0f} Hz"]
        
        # F0 信息
        if self._show_f0 and self._f0_data and self._show_f0_points:
            times, f0_values = self._f0_data
            if len(times) > 0:
                # 找到最接近当前时间点的F0值
                time_diffs = np.abs(times - current_time_s)
                closest_idx = np.argmin(time_diffs)
                # 如果时间点足够接近并且F0值有效，则添加到信息
                if time_diffs[closest_idx] < (self.hop_length / self.sr) and np.isfinite(f0_values[closest_idx]):
                    info_parts.append(f"F0: {f0_values[closest_idx]:.1f} Hz")
        
        # 共振峰信息
        if self._show_formants and self._formants_data:
            closest_formant_dist, closest_formants = float('inf'), None
            for sample_pos, formants in self._formants_data:
                dist = abs(sample_pos - current_sample)
                # 如果鼠标距离共振峰点足够近（例如3个hop_length的范围），则显示
                if dist < (self.hop_length * 3): 
                    if dist < closest_formant_dist: # 找最近的点
                        closest_formant_dist, closest_formants = dist, formants
            if closest_formants: # 确保找到了共振峰且距离在阈值内
                 # 格式化共振峰信息
                 info_parts.append(" | ".join([f"F{i+1}: {int(f)}" for i, f in enumerate(closest_formants)]))
        
        self._cursor_info_text = "\n".join(info_parts) # 更新悬浮信息文本
        
        # --- 新增: 动态调整信息框位置的逻辑 ---
        # 避免信息框遮挡鼠标指针
        if self._cursor_info_text:
            metrics = self.fontMetrics()
            # 计算左上角信息框的理论位置和大小
            top_left_text_rect = metrics.boundingRect(QRect(0, 0, self.width(), self.height()), Qt.AlignLeft, self._cursor_info_text).adjusted(-5, -5, 5, 5)
            top_left_text_rect.moveTo(10, 10) # 固定左上角位置

            # 如果鼠标当前在左上角信息框的区域内，则将信息框切换到右下角
            if top_left_text_rect.contains(event.pos()):
                self._info_box_position = 'bottom_right'
            else:
                # 仅当鼠标也不在右下角区域时，才恢复到左上角
                # 计算右下角信息框的理论位置
                bottom_right_text_rect = top_left_text_rect.translated(
                    self.width() - top_left_text_rect.width() - 20, # X轴偏移量
                    self.height() - top_left_text_rect.height() - 20 # Y轴偏移量
                )
                if not bottom_right_text_rect.contains(event.pos()):
                    self._info_box_position = 'top_left'

        self.update() # 触发重绘
        super().mouseMoveEvent(event) # 调用父类的事件处理


    def mouseReleaseEvent(self, event):
        """
        处理鼠标释放事件，确定选区并发送信号。
        """
        if event.button() == Qt.LeftButton and self._is_selecting:
            self._is_selecting = False # 停止选择
            
            # 检查拖动距离，如果很小则视为单击（清除选区）
            if abs(self._selection_end_x - self._selection_start_x) < 5:
                # 单击操作，清除所有选区状态
                self._selection_start_x = 0
                self._selection_end_x = 0
                self._selection_start_sample = None
                self._selection_end_sample = None
                self.selectionChanged.emit(None) # 通知上层选区已清除
            else:
                # 拖动结束，计算并保存最终的采样点选区
                start_sample = self._pixel_to_sample(self._selection_start_x)
                end_sample = self._pixel_to_sample(self._selection_end_x)
                
                # 保证 start < end
                self._selection_start_sample = min(start_sample, end_sample)
                self._selection_end_sample = max(start_sample, end_sample)
                
                # 发射信号，通知控制器选区已确定
                self.selectionChanged.emit((self._selection_start_sample, self._selection_end_sample))
            
            self.update() # 触发重绘以显示最终选区
        super().mouseReleaseEvent(event) # 调用父类的事件处理
    
    def create_context_menu(self):
        """
        [已修复] 创建一个包含所有内置动作和潜在插件动作的右键菜单。
        """
        menu = QMenu(self)
        has_selection = self._selection_start_sample is not None and self._selection_end_sample is not None
        
        # [关键修复] 将整个表达式的结果强制转换为布尔值
        has_analysis = bool(self._f0_data is not None or self._intensity_data is not None or self._formants_data)

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
        
        # 4. "导出" 子菜单
        export_menu = QMenu("导出", self)
        export_menu.setIcon(self.icon_manager.get_icon("export"))
        
        export_image_action = QAction(self.icon_manager.get_icon("image"), "将当前视图保存为图片...", self)
        export_image_action.triggered.connect(self.exportViewAsImageRequested.emit)
        export_menu.addAction(export_image_action)

        csv_icon = self.icon_manager.get_icon("csv")
        if csv_icon.isNull(): csv_icon = self.icon_manager.get_icon("document")
        export_csv_action = QAction(csv_icon, "将选区内分析数据导出为CSV...", self)
        export_csv_action.setEnabled(has_selection and has_analysis) # 现在 has_analysis 保证是布尔值
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
        # 第二部分：插件注入的菜单项
        # ==========================================================
        
        plotter_plugin = getattr(self, 'vowel_plotter_plugin_active', None)
        exporter_plugin = getattr(self, 'praat_exporter_plugin_active', None)
        intonation_plugin = getattr(self, 'intonation_visualizer_plugin_active', None)
        
        if plotter_plugin or exporter_plugin or intonation_plugin:
            menu.addSeparator()
 
        if intonation_plugin:
            action = QAction(self.icon_manager.get_icon("chart2"), "发送到语调可视化器...", self)
            has_f0_data = self._f0_data is not None and len(self._f0_data[0]) > 0
            action.setEnabled(has_selection and has_f0_data)
            if not (has_selection and has_f0_data):
                action.setToolTip("请先在选区内运行F0分析。")
            action.triggered.connect(self._send_data_to_intonation_visualizer)
            menu.addAction(action)

        if exporter_plugin:
            exporter_action = exporter_plugin.create_action_for_menu(self)
            menu.addAction(exporter_action)
        
        if plotter_plugin:
            plotter_action = QAction(self.icon_manager.get_icon("chart"), "发送数据到元音绘制器...", self)
            has_formants_in_selection = False
            if has_selection and self._formants_data:
                start_sample, end_sample = self._selection_start_sample, self._selection_end_sample
                has_formants_in_selection = any(start_sample <= point[0] < end_sample for point in self._formants_data)
            
            plotter_action.setEnabled(has_formants_in_selection)
            if not has_formants_in_selection:
                plotter_action.setToolTip("请先在选区内运行共振峰分析。")
            plotter_action.triggered.connect(self._send_data_to_plotter)
            menu.addAction(plotter_action)
        
        return menu

    def _send_data_to_plotter(self):
        """
        收集选区内的共振峰数据，并通过钩子调用元音绘制器插件的execute方法。
        """
        if not hasattr(self, 'vowel_plotter_plugin_active') or self.vowel_plotter_plugin_active is None:
            QMessageBox.warning(self, "插件未启用", "元音空间图绘制器插件未启用或加载失败。")
            return
        
        if self._selection_start_sample is None or self._selection_end_sample is None:
            QMessageBox.warning(self, "无选区", "请先在语谱图上选择一个区域以提取共振峰数据。")
            return

        start_sample, end_sample = self._selection_start_sample, self._selection_end_sample
        
        data_points = []
        for sample_pos, formants in self._formants_data:
            if start_sample <= sample_pos < end_sample:
                if len(formants) >= 2:
                    timestamp = sample_pos / self.sr
                    data_points.append({'timestamp': timestamp, 'F1': formants[0], 'F2': formants[1]})
        
        if not data_points:
            QMessageBox.warning(self, "无数据", "在选区内未找到有效的 F1/F2 数据点。请确保已运行共振峰分析。")
            return
            
        df = pd.DataFrame(data_points)
        
        # --- [核心修改] ---
        # 1. 获取主页面对象，它持有当前文件路径
        #    SpectrogramWidget 的父级是 center_panel, 再往上才是主页面 AudioAnalysisPage
        parent_page = self.parent().parent()
        
        source_name_for_plugin = '来自音频分析模块' # 默认值
        if hasattr(parent_page, 'current_filepath') and parent_page.current_filepath:
            # 2. 从完整路径中提取不带后缀的文件名
            source_name_for_plugin = os.path.splitext(os.path.basename(parent_page.current_filepath))[0]

        # 3. 在调用 execute 时，传入 source_name
        self.vowel_plotter_plugin_active.execute(dataframe=df, source_name=source_name_for_plugin)

    def _send_data_to_intonation_visualizer(self):
        """
        收集选区内的F0数据，并通过钩子调用语调可视化插件。
        """
        if not hasattr(self, 'intonation_visualizer_plugin_active') or self.intonation_visualizer_plugin_active is None:
            QMessageBox.warning(self, "插件未启用", "语调可视化器插件未启用或加载失败。")
            return
 
        if self._selection_start_sample is None or self._f0_data is None:
            QMessageBox.warning(self, "无数据", "请先在语谱图上选择一个区域，并确保已运行F0分析。")
            return
        
        start_sample = self._selection_start_sample
        end_sample = self._selection_end_sample
 
        selection_start_s = start_sample / self.sr
        selection_end_s = end_sample / self.sr
 
        times, f0_values = self._f0_data
        data_points = []
        for t, f0 in zip(times, f0_values):
            if selection_start_s <= t < selection_end_s:
                data_points.append({'timestamp': t, 'f0_hz': f0})
 
        if not data_points:
            QMessageBox.warning(self, "无数据", "在选区内未找到有效的 F0 数据点。")
            return
            
        df = pd.DataFrame(data_points)
        
        # --- [核心修改] (与上面 plotter 的修改逻辑完全相同) ---
        parent_page = self.parent().parent()
        
        source_name_for_plugin = '来自音频分析模块' # 默认值
        if hasattr(parent_page, 'current_filepath') and parent_page.current_filepath:
            source_name_for_plugin = os.path.splitext(os.path.basename(parent_page.current_filepath))[0]

        self.intonation_visualizer_plugin_active.execute(dataframe=df, source_name=source_name_for_plugin)

    # --- 默认的右键菜单事件处理器 ---
    def contextMenuEvent(self, event):
        """
        默认的右键菜单事件处理器。
        现在它只负责创建并显示菜单。
        """
        menu = self.create_context_menu()
        if not menu.isEmpty(): # 如果菜单不为空，则显示
            menu.exec_(self.mapToGlobal(event.pos())) # 在鼠标位置显示菜单

    # --- 其他方法 ---
    def set_data(self, S_db, sr, hop_length):
        """
        设置语谱图图像数据。
        Args:
            S_db (np.ndarray): 语谱图的分贝矩阵。
            sr (int): 采样率。
            hop_length (int): 语谱图的跳跃长度。
        """
        self.sr, self.hop_length = sr, hop_length
        # 将分贝值归一化到0-1范围，以便映射到颜色
        S_norm = (S_db - S_db.min()) / (S_db.max() - S_db.min() + 1e-6) # 归一化到0-1，加1e-6防止除以零
        h, w = S_norm.shape # 获取语谱图的高度（频率bin数）和宽度（帧数）
        rgba_data = np.zeros((h, w, 4), dtype=np.uint8) # 创建RGBA图像数据数组
        
        # 根据min/max颜色进行插值
        min_color_obj, max_color_obj = QColor(self._spectrogramMinColor), QColor(self._spectrogramMaxColor)
        min_c, max_c = np.array(min_color_obj.getRgb()), np.array(max_color_obj.getRgb())
        
        # 对每个像素进行颜色插值
        interpolated_colors = min_c + (max_c - min_c) * (S_norm[..., np.newaxis])
        rgba_data[..., :3] = interpolated_colors[..., :3].astype(np.uint8) # 复制RGB通道
        rgba_data[..., 3] = 255 # 设置Alpha通道为255（完全不透明）
        
        # 垂直翻转数据，因为QImage的0,0点在左上角，而语谱图的0频率在底部
        image_data = np.flipud(rgba_data)
        
        # 创建QImage
        self.spectrogram_image = QImage(image_data.tobytes(), w, h, QImage.Format_RGBA8888).copy()
        self.update() # 触发重绘

    def set_waveform_sibling(self, widget):
        """
        设置关联的波形控件，用于共享滚动事件。
        Args:
            widget (WaveformWidget): 波形控件实例。
        """
        self.waveform_sibling = widget

    def wheelEvent(self, event):
        """
        将滚轮事件传递给波形控件进行缩放。
        """
        if self.waveform_sibling:
            self.waveform_sibling.wheelEvent(event)
        else:
            super().wheelEvent(event) # 如果没有关联波形控件，则调用父类的事件处理

    def leaveEvent(self, event):
        """
        鼠标离开控件时清除悬浮信息。
        """
        if self._cursor_info_text:
            self._cursor_info_text = ""
            self._info_box_position = 'top_left' # 重置信息框位置
            self.update() # 触发重绘
        super().leaveEvent(event)

    def set_analysis_data(self, f0_data=None, f0_derived_data=None, intensity_data=None, formants_data=None, clear_previous_formants=True):
        """
        [v1.3 - 手动/自动模式]
        设置和更新叠加的分析数据层。
        - F0轴范围：只有在自动模式 (_f0_axis_is_auto=True)下，才会根据新的F0数据更新。
        - 其他数据：根据传入的参数进行更新或清除。

        Args:
            f0_data (tuple, optional): 原始F0数据 (times, f0_values)。如果为 None，则清空原始F0层。
            f0_derived_data (tuple, optional): 派生F0数据 (times, f0_values)。如果为 None，则清空派生F0层。
            intensity_data (np.ndarray, optional): 强度数据。如果为 None，则清空强度层。
            formants_data (list, optional): 共振峰数据。
            clear_previous_formants (bool): 是否在添加新共振峰数据前清除旧数据。
        """
        # --- 处理 F0 数据和坐标轴 ---
        if f0_data is not None:
            self._f0_data = f0_data
            
            # [核心修改] 只有在自动模式下，才根据新数据更新显示范围
            if self._f0_axis_is_auto:
                self._calculate_and_apply_auto_f0_range()
            else:
                # 在手动模式下，我们不改变 _f0_display_min/max 的值，
                # 但需要确保 F0 轴是可见的（如果 F0 数据有效）。
                times, f0_values = f0_data
                valid_f0 = f0_values[np.isfinite(f0_values)]
                self._f0_axis_enabled = len(valid_f0) > 1
        else:
            # 如果 f0_data 明确传入为 None，则清空数据并禁用轴
            self._f0_data = None
            self._f0_axis_enabled = False
        
        # --- 处理派生 F0 数据 ---
        if f0_derived_data is not None:
            self._f0_derived_data = f0_derived_data
        else:
            self._f0_derived_data = None # 清空派生F0数据
            
        # --- 处理强度数据 ---
        if intensity_data is not None:
            self._intensity_data = intensity_data
        else:
            self._intensity_data = None # 清空强度数据
        
        # --- 处理共振峰数据 ---
        if formants_data is not None:
            if clear_previous_formants:
                self._formants_data = formants_data # 覆盖旧数据
            else:
                self._formants_data.extend(formants_data) # 追加新数据
        elif clear_previous_formants:
            # 如果 formants_data 为 None，并且要求清除，则清空
            self._formants_data = []

        # 触发重绘以应用所有更改
        self.update()

    def append_analysis_data(self, f0_chunk=None, f0_derived_chunk=None, intensity_chunk=None):
        """
        将新分析出的数据块追加到现有数据中，并触发重绘。
        这用于实现实时呈现效果。
        """
        # --- 追加 F0 数据 ---
        if f0_chunk:
            new_times, new_f0 = f0_chunk
            if self._f0_data is None:
                self._f0_data = (new_times, new_f0)
            else:
                old_times, old_f0 = self._f0_data
                self._f0_data = (np.concatenate([old_times, new_times]), 
                                 np.concatenate([old_f0, new_f0]))

        # --- 追加派生 F0 数据 ---
        if f0_derived_chunk:
            new_times, new_f0_derived = f0_derived_chunk
            if self._f0_derived_data is None:
                self._f0_derived_data = (new_times, new_f0_derived)
            else:
                old_times, old_f0_derived = self._f0_derived_data
                self._f0_derived_data = (np.concatenate([old_times, new_times]), 
                                         np.concatenate([old_f0_derived, new_f0_derived]))

        # --- 追加强度数据 ---
        if intensity_chunk is not None:
            if self._intensity_data is None:
                self._intensity_data = intensity_chunk
            else:
                self._intensity_data = np.concatenate([self._intensity_data, intensity_chunk])
        
        # 实时更新F0轴的范围
        if self._f0_data:
            _, all_f0_values = self._f0_data
            valid_f0 = all_f0_values[np.isfinite(all_f0_values)]
            if len(valid_f0) > 1:
                # 使用与 set_analysis_data 中相同的逻辑来更新轴范围
                actual_min, actual_max = np.min(valid_f0), np.max(valid_f0)
                data_range = actual_max - actual_min
                padding = max(10, data_range * 0.1)
                padded_min = actual_min - padding
                padded_max = actual_max + padding
                current_range = padded_max - padded_min
                if current_range < 100:
                    center = (padded_max + padded_min) / 2
                    padded_min = center - 50
                    padded_max = center + 50
                self._f0_display_min = max(0, padded_min)
                self._f0_display_max = padded_max
                self._f0_axis_enabled = True

        # 触发重绘以在UI上显示新追加的数据
        self.update()

    def update_playback_position(self, position_ms):
        """
        更新播放光标位置。
        Args:
            position_ms (int): 当前播放位置（毫秒）。
        """
        if self.sr > 1:
            self._playback_pos_sample = int(position_ms / 1000 * self.sr) # 毫秒转换为采样点
            self.update() # 触发重绘

    def set_view_window(self, start_sample, end_sample):
        """
        设置当前显示视图的采样点范围。
        Args:
            start_sample (int): 视图起始采样点。
            end_sample (int): 视图结束采样点。
        """
        self._view_start_sample, self._view_end_sample = start_sample, end_sample
        self.update() # 触发重绘

    def clear(self):
        """
        清除所有数据和选区状态。
        """
        # 重置选区状态
        self._is_selecting = False
        self._selection_start_x = 0
        self._selection_end_x = 0
        self._selection_start_sample = None
        self._selection_end_sample = None
        
        # 清除数据
        self.spectrogram_image = None
        self._f0_data = None
        self._intensity_data = None
        self._formants_data = []
        self._f0_derived_data = None # 确保派生F0也清除
        
        self._playback_pos_sample = -1 # 重置播放光标
        self._cursor_info_text = ""    # 清除悬浮信息
        self._info_box_position = 'top_left' # 重置信息框位置

        self.update() # 触发重绘

    def render_to_pixmap(self):
        """
        将当前控件的内容渲染到一个QPixmap上并返回。
        用于高质量图片导出。
        Returns:
            QPixmap: 渲染后的QPixmap。
        """
        pixmap = QPixmap(self.size()) # 创建与控件大小相同的QPixmap
        pixmap.fill(Qt.transparent) # 使用透明背景，以便保存为PNG
        self.render(pixmap) # 将控件内容渲染到QPixmap
        return pixmap

# WaveformWidget 类：显示音频波形概览和提供导航
class WaveformWidget(QWidget):
    view_changed = pyqtSignal(int, int) # 视图范围改变时发送，携带起始和结束采样点
    
    # QSS可控颜色属性
    @pyqtProperty(QColor)
    def waveformColor(self): return self._waveformColor
    @waveformColor.setter
    def waveformColor(self, color): self._waveformColor = color; self.update()
    
    # 播放光标颜色（只读，因为由 SpectrogramWidget 控制）
    @pyqtProperty(QColor)
    def cursorColor(self): return QColor("red")
    @cursorColor.setter
    def cursorColor(self, color): pass
    
    # 选区颜色（只读，因为由 SpectrogramWidget 控制）
    @pyqtProperty(QColor)
    def selectionColor(self): return QColor(0,0,0,0) # 默认透明，实际由 _selectionColor 控制
    @selectionColor.setter
    def selectionColor(self, color): pass
    
    selectionChanged = pyqtSignal(object) # 选区改变时发送，携带 (start, end) 元组或 None
    zoomToSelectionRequested = pyqtSignal(int, int) # 请求缩放到选区时发送，携带起始和结束采样点

    def __init__(self, parent=None):
        """
        初始化波形控件。
        Args:
            parent (QWidget, optional): 父控件。
        """
        super().__init__(parent)
        self.setMinimumHeight(80) # 设置最小高度
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred) # 宽度可扩展，高度优先
        
        self._y_full, self._y_overview, self._sr = None, None, 1 # 完整音频数据，概览数据，采样率
        self._view_start_sample, self._view_end_sample = 0, 1 # 当前视图窗口的采样点范围
        
        # 默认颜色，会根据调色板更新
        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._backgroundColor = self.palette().color(QPalette.Base)
        
        # 选区相关属性
        self._is_selecting = False      # 标记是否正在进行鼠标拖动选择
        self._selection_start_x = 0     # 存储起始点的像素X坐标
        self._selection_end_x = 0       # 存储结束点的像素X坐标
        self._selection_start_sample = None # 最终确定的起始采样点
        self._selection_end_sample = None   # 最终确定的结束采样点
        self._selectionColor = QColor(135, 206, 250, 60) # 与语谱图使用相同颜色

    def set_audio_data(self, y_full, sr, y_overview):
        """
        设置音频数据。
        Args:
            y_full (np.ndarray): 完整音频数据。
            sr (int): 采样率。
            y_overview (np.ndarray): 概览音频数据。
        """
        self.clear() # 先清除旧数据
        if y_full is not None and sr is not None:
            self._y_full, self._sr, self._y_overview = y_full, sr, y_overview
            self._view_start_sample, self._view_end_sample = 0, len(self._y_full) # 初始视图为整个音频
        self.update() # 触发重绘
        self.view_changed.emit(self._view_start_sample, self._view_end_sample) # 发送视图改变信号

    def set_view_window(self, start_sample, end_sample):
        """
        设置当前显示视图的采样点范围。
        Args:
            start_sample (int): 视图起始采样点。
            end_sample (int): 视图结束采样点。
        """
        if self._y_full is None: return
        # 确保视图范围在音频数据范围内
        self._view_start_sample = max(0, start_sample)
        self._view_end_sample = min(len(self._y_full), end_sample)
        # 确保视图结束点不小于起始点
        if self._view_end_sample <= self._view_start_sample:
            self._view_end_sample = self._view_start_sample + 1
        self.update() # 触发重绘

    def wheelEvent(self, event):
        """
        处理鼠标滚轮事件，实现缩放功能。
        Ctrl+滚轮：水平缩放。
        """
        if event.modifiers() == Qt.ControlModifier and self._y_full is not None:
            anchor_ratio = event.x() / self.width() # 鼠标在控件内的X轴比例（作为缩放锚点）
            view_width = self._view_end_sample - self._view_start_sample # 当前视图宽度（采样点）
            anchor_sample = self._view_start_sample + anchor_ratio * view_width # 鼠标位置对应的采样点

            zoom_factor = 1.25 if event.angleDelta().y() < 0 else 1 / 1.25 # 根据滚轮方向确定缩放因子
            new_width = view_width * zoom_factor # 计算新的视图宽度

            # 限制最小和最大缩放
            if new_width < 50: new_width = 50 # 最小宽度50采样点
            if new_width > len(self._y_full): new_width = len(self._y_full) # 最大宽度为整个音频长度

            # 根据锚点和新宽度计算新的起始和结束采样点
            new_start = anchor_sample - anchor_ratio * new_width
            new_end = new_start + new_width

            # 调整边界，确保视图不超出音频范围
            if new_start < 0: new_start, new_end = 0, new_width
            if new_end > len(self._y_full): new_end = len(self._y_full); new_start = new_end - new_width
            
            self.set_view_window(int(new_start), int(new_end)) # 设置新的视图窗口
            self.view_changed.emit(self._view_start_sample, self._view_end_sample) # 发送视图改变信号
        else:
            super().wheelEvent(event) # 如果没有Ctrl键，则调用父类的滚轮事件处理

    def clear(self):
        """
        清除音频数据和视图状态。
        """
        self._y_full, self._y_overview = None, None
        self.update()
        self.view_changed.emit(0, 1) # 发送视图改变信号，表示视图已重置

    def _pixel_to_sample(self, x_pixel):
        """
        辅助函数，将像素X坐标转换为音频采样点索引。
        Args:
            x_pixel (int): 像素X坐标。
        Returns:
            int: 对应的音频采样点索引。
        """
        if self._y_full is None: return 0
        x_clamped = max(0, min(x_pixel, self.width())) # 将X坐标限制在控件宽度内
        
        view_width_samples = self._view_end_sample - self._view_start_sample
        x_ratio = x_clamped / self.width() if self.width() > 0 else 0 # 计算像素在控件内的比例
        sample_offset = x_ratio * view_width_samples # 计算相对于视图起始采样点的偏移量
        return int(self._view_start_sample + sample_offset) # 返回实际采样点

    def set_selection(self, selection_tuple):
        """
        公共槽函数，用于从外部设置选区。
        Args:
            selection_tuple (tuple or None): (start_sample, end_sample) 元组表示选区，或 None 表示清除选区。
        """
        if selection_tuple:
            start_sample, end_sample = selection_tuple
            # 只有当选区与当前视图有重叠时才显示
            if max(self._view_start_sample, start_sample) < min(self._view_end_sample, end_sample):
                self._selection_start_sample = start_sample
                self._selection_end_sample = end_sample
            else: # 选区在视图外，不显示
                self._selection_start_sample = None
                self._selection_end_sample = None
        else:
            self._selection_start_sample = None
            self._selection_end_sample = None
        self.update() # 触发重绘以更新选区显示

    def mousePressEvent(self, event):
        """
        处理鼠标按下事件，开始选择。
        """
        if event.button() == Qt.LeftButton and self._y_full is not None:
            self._is_selecting = True # 标记正在选择
            self._selection_start_x = event.pos().x() # 记录起始X坐标
            self._selection_end_x = event.pos().x()   # 初始时结束X坐标与起始相同
            self.update() # 触发重绘
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        处理鼠标拖动事件，更新选区。
        """
        if self._is_selecting:
            self._selection_end_x = event.pos().x() # 更新结束X坐标
            self.update() # 触发重绘以实时更新选区
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """
        处理鼠标释放事件，确定选区并发送信号。
        """
        if event.button() == Qt.LeftButton and self._is_selecting:
            self._is_selecting = False # 停止选择
            
            # 如果拖动距离很小（小于5像素），则视为单击，清除选区
            if abs(self._selection_end_x - self._selection_start_x) < 5:
                self._selection_start_sample = None
                self._selection_end_sample = None
                self.selectionChanged.emit(None) # 单击清除选区
            else:
                # 转换像素坐标为采样点
                start_sample = self._pixel_to_sample(self._selection_start_x)
                end_sample = self._pixel_to_sample(self._selection_end_x)
                
                # 确保起始采样点小于结束采样点
                self._selection_start_sample = min(start_sample, end_sample)
                self._selection_end_sample = max(start_sample, end_sample)
                # 发送选区改变信号
                self.selectionChanged.emit((self._selection_start_sample, self._selection_end_sample))
            self.update() # 触发重绘以显示最终选区
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """
        双击选区时，缩放到选区。
        """
        if event.button() == Qt.LeftButton and self._selection_start_sample is not None:
            # 发送缩放到选区请求信号
            self.zoomToSelectionRequested.emit(self._selection_start_sample, self._selection_end_sample)
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        """
        绘制波形图。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing) # 开启抗锯齿
        painter.fillRect(self.rect(), self.palette().color(QPalette.Base)) # 填充背景色

        if self._y_full is None:
            # 如果没有音频数据，则显示提示文本
            painter.setPen(self.palette().color(QPalette.Mid))
            painter.drawText(self.rect(), Qt.AlignCenter, "波形")
            return
        
        # 波形绘制逻辑
        view_width_samples = self._view_end_sample - self._view_start_sample
        w, h, half_h = self.width(), self.height(), self.height() / 2 # 控件宽度、高度、半高
        
        # 根据视图宽度选择绘制完整数据还是概览数据，以提高性能
        y_to_draw = self._y_overview if view_width_samples > w * 4 else self._y_full
        
        # 计算要绘制的数据在 y_to_draw 中的起始和结束索引
        start_idx = int(self._view_start_sample / len(self._y_full) * len(y_to_draw))
        end_idx = int(self._view_end_sample / len(self._y_full) * len(y_to_draw))
        
        view_y = y_to_draw[start_idx:end_idx] # 提取当前视图内的波形数据
        if len(view_y) == 0: return # 如果没有数据，则不绘制

        painter.setPen(QPen(self._waveformColor, 1)) # 设置波形颜色和粗细
        max_val = np.max(np.abs(view_y)) or 1.0 # 归一化波形幅度
        
        # 将波形数据点映射到像素坐标
        points = [QPointF(i * w / len(view_y), half_h - (val / max_val * half_h * 0.95)) for i, val in enumerate(view_y)]
        if points:
            painter.drawPolyline(*points) # 绘制波形曲线

        # --- 绘制选区高亮 ---
        selection_to_draw = None
        if self._is_selecting: # 正在拖动时
            x1 = min(self._selection_start_x, self._selection_end_x)
            x2 = max(self._selection_start_x, self._selection_end_x)
            selection_to_draw = QRect(int(x1), 0, int(x2 - x1), h) # 选区矩形
        elif self._selection_start_sample is not None: # 已有确定选区时
            # 将选区的采样点转换为像素坐标
            start_x = (self._selection_start_sample - self._view_start_sample) / view_width_samples * w
            end_x = (self._selection_end_sample - self._view_start_sample) / view_width_samples * w
            if start_x < w and end_x > 0: # 仅当选区在视图内时绘制
                selection_to_draw = QRect(int(start_x), 0, int(end_x - start_x), h)
        
        if selection_to_draw:
            painter.setPen(Qt.NoPen) # 不绘制边框
            painter.setBrush(self._selectionColor) # 设置填充颜色
            painter.drawRect(selection_to_draw) # 绘制选区矩形


# create_page 函数：模块的工厂函数，用于创建和返回主页面实例
def create_page(parent_window, icon_manager, ToggleSwitchClass):
    """
    创建并返回音频分析模块的主页面实例。
    Args:
        parent_window (QWidget): 主应用程序窗口。
        icon_manager (IconManager): 图标管理器实例。
        ToggleSwitchClass (class): 自定义的开关控件类。
    Returns:
        QWidget: 音频分析模块的主页面实例，或一个错误提示页面。
    """
    if DEPENDENCIES_MISSING:
        # 如果缺少依赖，则返回一个显示错误信息的页面
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"音频分析模块加载失败...\n请运行: pip install numpy soundfile librosa pandas\n错误: {MISSING_ERROR_MESSAGE}")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return error_page
    # 否则，返回 AudioAnalysisPage 实例
    return AudioAnalysisPage(parent_window, icon_manager, ToggleSwitchClass)

# AudioAnalysisPage 类：模块的主控制器和UI容器
class AudioAnalysisPage(QWidget):
    # 定义渲染精细度标签的映射
    DENSITY_LABELS = {
            1: "最低", 2: "很低", 3: "较低", 4: "标准", 5: "较高",
            6: "精细", 7: "很高", 8: "极高", 9: "最高"
        }
    # 定义需要重新分析的提示文本
    REQUIRES_ANALYSIS_HINT = '<b><font color="#e57373">注意：更改此项需要重新运行分析才能生效。</font></b>'

    def __init__(self, parent_window, icon_manager, ToggleSwitchClass):
        """
        初始化音频分析主页面。
        Args:
            parent_window (QWidget): 主应用程序窗口。
            icon_manager (IconManager): 图标管理器实例。
            ToggleSwitchClass (class): 自定义的开关控件类。
        """
        super().__init__()
        self.parent_window = parent_window
        self.icon_manager = icon_manager
        self.ToggleSwitch = ToggleSwitchClass # 保存自定义开关控件类
        self.setAcceptDrops(True) # 允许拖放文件
        
        # 音频数据和状态变量
        self.audio_data, self.sr, self.overview_data, self.current_filepath = None, None, None, None
        
        # --- 新增 ---
        self.current_selection = None # 当前选区 (start_sample, end_sample) 或 None
        self.is_playing_selection = False # 标记是否正在播放选区
        self.is_player_ready = False # 标志，用于检查播放器是否已预热
        self._pending_csv_path = None # 用于在加载音频后应用CSV数据
        
        self.player = QMediaPlayer() # 媒体播放器实例
        self.player.setNotifyInterval(10) # 设置播放进度更新间隔为10毫秒
        self.known_duration = 0 # 已知音频时长
        
        self.task_thread, self.worker = None, None # 后台任务线程和工作器
        self.is_task_running = False # 标记是否有任务正在运行

        self._init_ui() # 初始化UI
        self._connect_signals() # 连接信号和槽
        self.update_icons() # 更新图标
        self._update_dependent_widgets() # 更新依赖控件的状态
        self._load_persistent_settings() # 加载持久化设置

    def _init_ui(self):
        """
        初始化用户界面布局和控件。
        """
        main_layout = QHBoxLayout(self) # 主水平布局

        # --- 左侧面板：信息与动作 ---
        self.info_panel = QWidget()
        self.info_panel.setFixedWidth(300)
        info_layout = QVBoxLayout(self.info_panel)
        
        self.open_file_btn = QPushButton(" 从文件加载音频")
        self.open_file_btn.setToolTip("打开文件浏览器选择一个音频文件进行分析。")
        
        self.info_group = QGroupBox("音频信息")
        info_layout_form = QFormLayout(self.info_group)
        self.filename_label, self.duration_label, self.samplerate_label, self.channels_label, self.bitdepth_label = [QLabel("N/A") for _ in range(5)]
        self.filename_label.setWordWrap(True)
        info_layout_form.addRow("文件名:", self.filename_label)
        info_layout_form.addRow("时长:", self.duration_label)
        info_layout_form.addRow("采样率:", self.samplerate_label)
        info_layout_form.addRow("通道数:", self.channels_label)
        info_layout_form.addRow("位深度:", self.bitdepth_label)
        
        self.playback_group = QGroupBox("播放控制")
        playback_layout = QVBoxLayout(self.playback_group)
        self.play_pause_btn = QPushButton("播放")
        self.playback_slider = AnimatedSlider(Qt.Horizontal)
        self.playback_slider.setObjectName("PlaybackSliderAnalysis") # 设置一个独立的 objectName 以便QSS定制
        self.time_label = QLabel("00:00.00 / 00:00.00")
        self.play_pause_btn.setEnabled(False)
        self.playback_slider.setEnabled(False)
        playback_layout.addWidget(self.play_pause_btn)
        playback_layout.addWidget(self.playback_slider)
        playback_layout.addWidget(self.time_label)

        self.analysis_actions_group = QGroupBox("分析动作")
        actions_layout = QVBoxLayout(self.analysis_actions_group)
        
        self.analyze_spectrogram_button = QPushButton(" 分析语谱图")
        self.analyze_spectrogram_button.setToolTip("运行语谱图背景分析。\n这将生成用于叠加F0曲线的背景。")
        
        self.analyze_acoustics_button = QPushButton(" 分析 F0 & 强度")
        self.analyze_acoustics_button.setToolTip("请先运行“分析语谱图”以启用此功能。")
        self.analyze_acoustics_button.setEnabled(False)
        
        self.analyze_formants_button = QPushButton(" 分析共振峰")
        self.analyze_formants_button.setToolTip("仅对屏幕上可见区域进行共振峰分析，速度更快。")
        
        # [顺序调整 1] “分析语谱图”按钮现在被添加到最上面
        actions_layout.addWidget(self.analyze_spectrogram_button)
        actions_layout.addWidget(self.analyze_acoustics_button)
        actions_layout.addWidget(self.analyze_formants_button)
        
        self.analysis_actions_group.setEnabled(False)

        info_layout.addWidget(self.open_file_btn)
        info_layout.addWidget(self.info_group)
        info_layout.addWidget(self.playback_group)
        info_layout.addWidget(self.analysis_actions_group)
        info_layout.addStretch()

        # 中心可视化区域
        self.center_panel = QWidget()
        center_layout = QVBoxLayout(self.center_panel) # 垂直布局
        center_layout.setSpacing(0) # 控件之间无间距
        center_layout.setContentsMargins(0, 0, 0, 0) # 无边距

        self.waveform_widget = WaveformWidget() # 波形图控件
        self.waveform_widget.setToolTip("音频波形概览。\n使用 Ctrl+鼠标滚轮 进行水平缩放。")

        self.time_axis_widget = TimeAxisWidget() # 时间轴控件
        self.time_axis_widget.hide() # 默认隐藏

        self.spectrogram_widget = SpectrogramWidget(self, self.icon_manager) # 语谱图控件
        self.spectrogram_widget.setToolTip("音频语谱图。\n悬停查看信息，滚动缩放，左键拖动选择区域。")
        
        self.spectrogram_widget.set_waveform_sibling(self.waveform_widget) # 将波形控件设置为语谱图的兄弟控件
        self.h_scrollbar = QScrollBar(Qt.Horizontal) # 水平滚动条
        self.h_scrollbar.setToolTip("在放大的视图中水平导航（平移）。")
        self.h_scrollbar.setEnabled(False) # 默认禁用滚动条
        
        center_layout.addWidget(self.waveform_widget, 1) # 波形图占据1份空间
        center_layout.addWidget(self.time_axis_widget) # 时间轴
        center_layout.addWidget(self.spectrogram_widget, 2) # 语谱图占据2份空间
        center_layout.addWidget(self.h_scrollbar)

        # --- [核心修改] 右侧面板：现在使用 QScrollArea ---
        
        # 1. 创建 QScrollArea 作为最外层容器
        self.settings_panel_scroll_area = QScrollArea()
        self.settings_panel_scroll_area.setFixedWidth(320) # 稍微加宽一点以容纳滚动条
        self.settings_panel_scroll_area.setWidgetResizable(True) # 关键：让内部控件自动填充宽度
        self.settings_panel_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # 禁用横向滚动条
        
        # [新增] 为 QScrollArea 设置一个唯一的对象名，以便样式表能精确匹配
        self.settings_panel_scroll_area.setObjectName("SettingsScrollArea")
        
        # [修改] 使用新的样式表，不仅移除边框，还隐藏了垂直滚动条
        self.settings_panel_scroll_area.setStyleSheet("""
            QScrollArea#SettingsScrollArea { 
                border: none; 
            }
            QScrollArea#SettingsScrollArea QScrollBar:vertical {
                width: 0px;
            }
        """)

        # 3. 创建一个新的内部容器QWidget，用于放置所有设置组
        self.settings_panel_content = QWidget()
        self.settings_panel_scroll_area.setWidget(self.settings_panel_content)
        
        # 4. 现在的 settings_layout 属于这个新的内部容器
        settings_layout = QVBoxLayout(self.settings_panel_content)
        
        # --- (所有 GroupBox 的创建逻辑保持不变，只是它们的父布局是 settings_layout) ---
        self.visualization_group = QGroupBox("可视化选项") 
        vis_layout = QFormLayout(self.visualization_group)
        self.visualization_group.setToolTip("控制在语谱图上叠加显示哪些声学特征。\n这些选项的更改会<b>立即生效</b>，无需重新分析。")
        
        self.show_f0_toggle = self.ToggleSwitch() 
        self.show_f0_toggle.setToolTip("总开关：是否显示任何与<b>基频（F0）</b>相关的信息。<br>基频是声带振动的频率，人耳感知为音高。")
        self.show_f0_points_checkbox = QCheckBox("显示原始点") 
        self.show_f0_points_checkbox.setToolTip("显示算法直接计算出的离散基频点（橙色点）。")
        self.show_f0_derived_checkbox = QCheckBox("显示派生曲线") 
        self.show_f0_derived_checkbox.setToolTip("显示通过对原始点进行线性插值后得到的连续基频曲线（蓝色虚线）。")
        f0_sub_layout = QVBoxLayout() 
        f0_sub_layout.setSpacing(2)
        f0_sub_layout.setContentsMargins(15, 0, 0, 0)
        f0_sub_layout.addWidget(self.show_f0_points_checkbox)
        f0_sub_layout.addWidget(self.show_f0_derived_checkbox)
        vis_layout.addRow("显示基频 (F0)", self.show_f0_toggle)
        vis_layout.addRow(f0_sub_layout)
        
        self.show_intensity_toggle = self.ToggleSwitch()
        self.show_intensity_toggle.setToolTip("总开关：是否显示音频的<b>强度</b>曲线。<br>强度是声波的振幅，人耳感知为响度。")
        self.smooth_intensity_checkbox = QCheckBox("平滑处理")
        self.smooth_intensity_checkbox.setToolTip("对强度曲线进行移动平均平滑（窗口=5），以观察其总体趋势，滤除微小波动。")
        intensity_sub_layout = QVBoxLayout() 
        intensity_sub_layout.setSpacing(2)
        intensity_sub_layout.setContentsMargins(15, 0, 0, 0)
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
        formant_sub_layout = QVBoxLayout() 
        formant_sub_layout.setSpacing(2)
        formant_sub_layout.setContentsMargins(15, 0, 0, 0)
        formant_sub_layout.addWidget(self.highlight_f1_checkbox)
        formant_sub_layout.addWidget(self.highlight_f2_checkbox)
        formant_sub_layout.addWidget(self.show_other_formants_checkbox)
        vis_layout.addRow("显示共振峰", self.show_formants_toggle)
        vis_layout.addRow(formant_sub_layout)

        # [核心修复] 将标签和滑块布局分开添加，以实现换行
        
        # 1. 创建标签并添加到表单布局的第一行
        f0_axis_label = QLabel("F0 轴范围 (Hz):")
        vis_layout.addRow(f0_axis_label)

        # 2. 创建包含滑块和数值的垂直布局
        f0_axis_range_layout = QVBoxLayout()
        f0_axis_range_layout.setContentsMargins(0, 0, 0, 0) # 移除不必要的边距
        f0_axis_range_layout.setSpacing(2) # 紧凑的间距

        self.f0_axis_range_slider = RangeSlider(Qt.Horizontal)
        self.f0_axis_range_slider.setRange(0, 1000)
        self.f0_axis_range_slider.setToolTip(
            "手动调整右侧F0轴的显示范围。\n"
            "将两个滑块都拖到最两端可恢复为自动范围模式。"
        )
        f0_axis_range_layout.addWidget(self.f0_axis_range_slider)
        
        f0_axis_value_layout = QHBoxLayout()
        self.f0_axis_min_label = QLabel("Auto")
        self.f0_axis_max_label = QLabel("Auto")
        f0_axis_value_layout.addWidget(self.f0_axis_min_label)
        f0_axis_value_layout.addStretch()
        f0_axis_value_layout.addWidget(self.f0_axis_max_label)
        f0_axis_range_layout.addLayout(f0_axis_value_layout)
        
        # 3. 将滑块布局添加到表单布局的第二行，并让它跨越两列
        vis_layout.addRow(f0_axis_range_layout)

        self.advanced_params_group = QGroupBox("高级分析参数")
        # [修改] 使用 QVBoxLayout 替换 QFormLayout
        adv_layout = QVBoxLayout(self.advanced_params_group)
        self.advanced_params_group.setToolTip(f"调整声学分析算法的核心参数，会直接影响计算结果的准确性。<br>{self.REQUIRES_ANALYSIS_HINT}")
        
        self.pre_emphasis_checkbox = QCheckBox("应用预加重")
        self.pre_emphasis_checkbox.setToolTip(f"在分析前通过一个高通滤波器提升高频部分的能量。<br>这对于在高频区域寻找共振峰（尤其是女声和童声）非常有帮助。<br>{self.REQUIRES_ANALYSIS_HINT}")
        adv_layout.addWidget(self.pre_emphasis_checkbox)
        
        f0_label = QLabel("F0 范围:")
        adv_layout.addWidget(f0_label)

        self.f0_range_slider = RangeSlider(Qt.Horizontal)
        self.f0_range_slider.setRange(10, 1000) # 范围保持不变
        # [修改] 设置新的默认值
        self.f0_range_slider.setLowerValue(10)
        self.f0_range_slider.setUpperValue(700)
        # [修改] 更新 ToolTip
        self.f0_range_slider.setToolTip(
            "拖动滑块设置基频（F0）搜索的频率范围（单位：Hz）。<br><br>"
            "<b>默认值 (10-700 Hz)</b> 已足够宽，适合大多数人声。<br>"
            "如果F0提取出现跳跃或中断，请先尝试根据说话人类型<b>缩小范围</b>：<br>"
            "<li>典型男声: 75-300 Hz</li>"
            "<li>典型女声: 100-500 Hz</li>"
            "<li>典型童声: 150-600 Hz</li><br>"
            "如果F0完全无法提取，可以尝试<b>进一步扩大范围</b>。<br><br>"
            f"{self.REQUIRES_ANALYSIS_HINT}"
        )
        adv_layout.addWidget(self.f0_range_slider)
        
        f0_value_layout = QHBoxLayout()
        # [修改] 更新标签的初始文本
        self.f0_min_label = QLabel("10")
        self.f0_max_label = QLabel("700")
        f0_value_layout.addWidget(self.f0_min_label)
        f0_value_layout.addStretch()
        f0_value_layout.addWidget(self.f0_max_label)
        adv_layout.addLayout(f0_value_layout)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        adv_layout.addWidget(separator)
        
        # [新增] 分块大小滑块
        chunk_size_label = QLabel("分块大小 (实时分析):")
        adv_layout.addWidget(chunk_size_label)
        
        self.chunk_size_slider = QSlider(Qt.Horizontal)
        self.chunk_size_slider.setRange(50, 1000) # 范围: 50ms 到 1000ms
        self.chunk_size_slider.setValue(200)      # 默认值: 200ms
        self.chunk_size_slider.setToolTip(
            "调整实时分析时每个数据块的大小（单位：毫秒）。\n"
            "较小的值 (如100ms): 响应更快，曲线“生长”得更迅速，但总分析时间可能稍长。"
            "较大的值 (如500ms): 每次计算的块更长，曲线“跳跃”得更远，总分析时间可能稍短。"
        )
        chunk_size_widget = QWidget()
        chunk_size_layout = QHBoxLayout(chunk_size_widget)
        chunk_size_layout.setContentsMargins(0,0,0,0)
        chunk_size_layout.addWidget(self.chunk_size_slider)
        self.chunk_size_value_label = QLabel(f"{self.chunk_size_slider.value()} ms")
        chunk_size_layout.addWidget(self.chunk_size_value_label)
        adv_layout.addWidget(chunk_size_widget)

        # [新增] 分块重叠滑块
        chunk_overlap_label = QLabel("分块重叠:")
        adv_layout.addWidget(chunk_overlap_label)

        self.chunk_overlap_slider = QSlider(Qt.Horizontal)
        self.chunk_overlap_slider.setRange(0, 100) # 范围: 0ms 到 100ms (最大值会动态调整)
        self.chunk_overlap_slider.setValue(10)     # 默认值: 10ms
        self.chunk_overlap_slider.setToolTip(
            "设置相邻分析块之间的重叠量（单位：毫秒）。\n"
            "重叠可以平滑块与块之间的过渡，尤其有助于改善F0曲线在拼接处的连续性。\n"
            "推荐值为5-20ms。重叠值不能大于块大小。"
        )
        chunk_overlap_widget = QWidget()
        chunk_overlap_layout = QHBoxLayout(chunk_overlap_widget)
        chunk_overlap_layout.setContentsMargins(0,0,0,0)
        chunk_overlap_layout.addWidget(self.chunk_overlap_slider)
        self.chunk_overlap_value_label = QLabel(f"{self.chunk_overlap_slider.value()} ms")
        chunk_overlap_layout.addWidget(self.chunk_overlap_value_label)
        adv_layout.addWidget(chunk_overlap_widget)
        
        self.spectrogram_settings_group = QGroupBox("分析与渲染设置")
        # [核心] 将布局改回 QFormLayout
        spec_settings_layout = QFormLayout(self.spectrogram_settings_group)
        self.spectrogram_settings_group.setToolTip(f"调整声学分析算法的核心参数，会直接影响计算结果的准确性。<br>{self.REQUIRES_ANALYSIS_HINT}")

        # --- [核心] 渲染精细度布局 ---
        self.render_density_slider = QSlider(Qt.Horizontal)
        self.render_density_slider.setRange(1, 5)
        self.render_density_slider.setValue(4)
        self.render_density_slider.setToolTip(
            "调整语谱图背景、F0、强度曲线的渲染精细度。\n"
            "值越高，图像越平滑，但计算稍慢。"
        )
        self.render_density_label = QLabel()
        
        # 将滑块和标签放入一个水平布局
        render_density_widget = QWidget()
        render_density_layout = QHBoxLayout(render_density_widget)
        render_density_layout.setContentsMargins(0, 0, 0, 0)
        render_density_layout.addWidget(self.render_density_slider)
        render_density_layout.addWidget(self.render_density_label)
        render_density_layout.setStretch(0, 1) # 让滑块占据伸缩空间

        spec_settings_layout.addRow("渲染精细度:", render_density_widget)
        
        # --- [核心] 共振峰精细度布局 ---
        self.formant_density_slider = QSlider(Qt.Horizontal)
        self.formant_density_slider.setRange(1, 9)
        self.formant_density_slider.setValue(5)
        self.formant_density_slider.setToolTip(
            "调整共振峰分析的精细度。\n"
            "值越高，找到的共振峰点越密集，但计算速度会显著变慢。"
        )
        self.formant_density_label = QLabel()

        # 将滑块和标签放入一个水平布局
        formant_density_widget = QWidget()
        formant_density_layout = QHBoxLayout(formant_density_widget)
        formant_density_layout.setContentsMargins(0, 0, 0, 0)
        formant_density_layout.addWidget(self.formant_density_slider)
        formant_density_layout.addWidget(self.formant_density_label)
        formant_density_layout.setStretch(0, 1) # 让滑块占据伸缩空间
        
        spec_settings_layout.addRow("共振峰精细度:", formant_density_widget)
        
        # --- [核心] 宽带模式复选框 ---
        self.spectrogram_type_checkbox = QCheckBox("宽带模式")
        self.spectrogram_type_checkbox.setToolTip(f"切换语谱图的分析窗长，决定了时间和频率分辨率的取舍。<br><li><b>宽带 (勾选)</b>: 短窗，时间分辨率高，能清晰看到声门的每一次振动（垂直线），但频率分辨率低。</li><li><b>窄带 (不勾选)</b>: 长窗，频率分辨率高，能清晰看到基频的各次谐波（水平线），但时间分辨率低。</li><br>{self.REQUIRES_ANALYSIS_HINT}")
        spec_settings_layout.addRow(self.spectrogram_type_checkbox) # QFormLayout 可以直接添加单行控件

        self._update_render_density_label(self.render_density_slider.value())
        self._update_formant_density_label(self.formant_density_slider.value())
        
        # 5. [修改] 将所有 GroupBox 添加到 settings_layout (内部容器的布局)
        settings_layout.addWidget(self.visualization_group)
        settings_layout.addWidget(self.spectrogram_settings_group)
        settings_layout.addWidget(self.advanced_params_group)

        settings_layout.addStretch() 

        # 6. [修改] 将新的 scroll_area 添加到主布局中
        main_layout.addWidget(self.info_panel)
        main_layout.addWidget(self.center_panel, 1)
        main_layout.addWidget(self.settings_panel_scroll_area) # 替换掉原来的 self.settings_panel
    def _on_f0_range_changed(self, lower, upper):
        """当F0范围滑块改变时更新标签和持久化设置。"""
        self.f0_min_label.setText(str(lower))
        self.f0_max_label.setText(str(upper))
        # 分别保存最小值和最大值
        self._on_persistent_setting_changed('f0_min', lower)
        self._on_persistent_setting_changed('f0_max', upper)

    def _on_f0_axis_range_changed(self, lower, upper):
        """当手动调整F0轴范围的滑块改变时调用。"""
        # 检查是否处于“自动”模式的边界条件
        is_auto = (lower == self.f0_axis_range_slider.minimum()) and \
                  (upper == self.f0_axis_range_slider.maximum())

        if is_auto:
            self.f0_axis_min_label.setText("Auto")
            self.f0_axis_max_label.setText("Auto")
            self.spectrogram_widget.set_f0_axis_range(None, None)
            # 保存一个特殊值表示自动模式
            self._on_persistent_setting_changed('f0_axis_manual_range', None)
        else:
            self.f0_axis_min_label.setText(str(lower))
            self.f0_axis_max_label.setText(str(upper))
            self.spectrogram_widget.set_f0_axis_range(lower, upper)
            # 保存手动设定的范围
            self._on_persistent_setting_changed('f0_axis_manual_range', [lower, upper])

    # [新增] 用于处理每个分析好的数据块
    def on_acoustics_chunk_finished(self, chunk_result):
        """
        当一个声学数据块分析完成时调用，并更新进度条。
        """
        self.spectrogram_widget.append_analysis_data(
            f0_chunk=chunk_result.get('f0_raw'),
            f0_derived_chunk=chunk_result.get('f0_derived'),
            intensity_chunk=chunk_result.get('intensity')
        )
        # 更新进度条
        if self.progress_dialog and self.progress_dialog.isVisible():
            # 计算当前进度百分比
            f0_times = chunk_result.get('f0_raw')[0] if chunk_result.get('f0_raw') else []
            if len(f0_times) > 0 and self.known_duration > 0:
                current_progress_ms = f0_times[-1] * 1000
                progress_percent = (current_progress_ms / self.known_duration) * 100
                self.progress_dialog.setValue(int(progress_percent))


    # [新增] 用于在所有块都处理完毕后进行清理
    def on_acoustics_analysis_done(self, final_result):
        """
        [已修复] 当所有声学分析块都处理完毕后调用。
        """
        if self.progress_dialog:
            self.progress_dialog.close()
        
        # [关键修复逻辑]
        # 只有当这是第一次分析（即还没有语谱图背景时），
        # 我们才将这次分析的hop_length设置为“黄金标准”。
        if self.spectrogram_widget.spectrogram_image is None:
            if 'hop_length' in final_result:
                self.spectrogram_widget.hop_length = final_result['hop_length']

    def _connect_signals(self):
        """
        [已修复] 连接所有UI控件的信号到相应的槽函数。
        """
        # --- 文件与播放控制 ---
        self.open_file_btn.clicked.connect(self.open_file_dialog)
        self.play_pause_btn.clicked.connect(self.toggle_playback)
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.player.stateChanged.connect(self.on_player_state_changed)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.playback_slider.sliderMoved.connect(self.player.setPosition)

        # --- 视图与导航 ---
        self.waveform_widget.view_changed.connect(self.on_view_changed)
        self.h_scrollbar.valueChanged.connect(self.on_scrollbar_moved)
        
        # [关键修复] 添加缺失的滑块信号连接
        self.render_density_slider.valueChanged.connect(self._update_render_density_label)
        self.formant_density_slider.valueChanged.connect(self._update_formant_density_label)

        # --- 分析动作 ---
        self.analyze_acoustics_button.clicked.connect(self.run_acoustics_analysis)
        self.analyze_spectrogram_button.clicked.connect(self.run_spectrogram_analysis)
        self.analyze_formants_button.clicked.connect(self.run_view_formant_analysis)

        # --- 选区同步与快捷键 ---
        self.spectrogram_widget.selectionChanged.connect(self.waveform_widget.set_selection)
        self.waveform_widget.selectionChanged.connect(self.spectrogram_widget.set_selection)
        self.spectrogram_widget.selectionChanged.connect(self.on_selection_changed)
        self.waveform_widget.selectionChanged.connect(self.on_selection_changed)
        self.spectrogram_widget.zoomToSelectionRequested.connect(self.zoom_to_selection)
        self.waveform_widget.zoomToSelectionRequested.connect(self.zoom_to_selection)
        self.select_all_shortcut = QShortcut(QKeySequence.SelectAll, self)
        self.select_all_shortcut.activated.connect(self._select_all)
        
        # --- 可视化选项 ---
        all_toggles = [self.show_f0_toggle, self.show_intensity_toggle, self.show_formants_toggle]
        for toggle in all_toggles:
            toggle.stateChanged.connect(self._update_dependent_widgets)
            toggle.stateChanged.connect(self.update_overlays)
        all_checkboxes = [self.show_f0_points_checkbox, self.show_f0_derived_checkbox, self.smooth_intensity_checkbox, self.highlight_f1_checkbox, self.highlight_f2_checkbox, self.show_other_formants_checkbox]
        for cb in all_checkboxes:
            cb.stateChanged.connect(self.update_overlays)

        # --- 持久化设置 ---
        self.show_f0_toggle.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_f0', bool(s)))
        self.show_f0_points_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_f0_points', bool(s)))
        self.show_f0_derived_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_f0_derived', bool(s)))
        self.show_intensity_toggle.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_intensity', bool(s)))
        self.smooth_intensity_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('smooth_intensity', bool(s)))
        self.show_formants_toggle.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_formants', bool(s)))
        self.highlight_f1_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('highlight_f1', bool(s)))
        self.highlight_f2_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('highlight_f2', bool(s)))
        self.show_other_formants_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('show_other_formants', bool(s)))
        self.f0_axis_range_slider.rangeChanged.connect(self._on_f0_axis_range_changed)
        self.pre_emphasis_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('pre_emphasis', bool(s)))
        self.f0_range_slider.rangeChanged.connect(self._on_f0_range_changed)
        self.render_density_slider.valueChanged.connect(lambda v: self._on_persistent_setting_changed('render_density', v))
        self.formant_density_slider.valueChanged.connect(lambda v: self._on_persistent_setting_changed('formant_density', v))
        self.spectrogram_type_checkbox.stateChanged.connect(lambda s: self._on_persistent_setting_changed('is_wide_band', bool(s)))
        self.chunk_size_slider.valueChanged.connect(self._on_chunk_settings_changed)
        self.chunk_overlap_slider.valueChanged.connect(self._on_chunk_settings_changed)

        # --- 导出 ---
        self.spectrogram_widget.exportViewAsImageRequested.connect(self.handle_export_image)
        self.spectrogram_widget.exportAnalysisToCsvRequested.connect(self.handle_export_csv)
        self.spectrogram_widget.exportSelectionAsWavRequested.connect(self.handle_export_wav)
        self.spectrogram_widget.spectrumSliceRequested.connect(self.handle_spectrum_slice_request)

    def _select_all(self):
        """
        响应 Ctrl+A 快捷键，选中整个音频文件。
        """
        # 1. 安全检查：确保音频已加载
        if self.audio_data is None or len(self.audio_data) == 0:
            return

        # 2. 定义全选范围 (从样本0到最后一个样本)
        selection_tuple = (0, len(self.audio_data))
        
        # 3. 更新主页面的选区状态
        self.on_selection_changed(selection_tuple)
        
        # 4. 将选区状态同步到两个视图控件
        self.waveform_widget.set_selection(selection_tuple)
        self.spectrogram_widget.set_selection(selection_tuple)

    def handle_spectrum_slice_request(self, sample_pos):
        """
        处理频谱切片请求，计算FFT并显示对话框。
        Args:
            sample_pos (int): 请求进行频谱切片的采样点位置。
        """
        if self.audio_data is None:
            QMessageBox.warning(self, "无音频", "请先加载音频文件。")
            return

        try:
            # 1. 定义FFT参数
            n_fft = 2048 # FFT点数
            
            # 2. 获取以sample_pos为中心的音频帧
            start = max(0, sample_pos - n_fft // 2)
            end = min(len(self.audio_data), start + n_fft)
            frame = self.audio_data[start:end]
            
            # 如果帧太短，则补零以达到FFT长度
            if len(frame) < n_fft:
                frame = np.pad(frame, (0, n_fft - len(frame)), 'constant')

            # 3. 应用汉明窗，减少频谱泄露
            window = np.hanning(n_fft)
            windowed_frame = frame * window

            # 4. 计算FFT和频率轴
            mags = np.abs(np.fft.rfft(windowed_frame)) # 实时傅里叶变换的幅度
            freqs = np.fft.rfftfreq(n_fft, d=1.0/self.sr) # 对应的频率轴

            # 5. 转换为dB
            mags_db = 20 * np.log10(mags + 1e-9) # 转换为分贝，加1e-9防止log(0)

            # 6. 显示对话框
            time_s = sample_pos / self.sr # 采样点转换为时间（秒）
            dialog = SpectrumSliceDialog(freqs, mags_db, time_s, self.sr, self)
            dialog.exec_() # 模态显示对话框
            
        except Exception as e:
            import traceback
            traceback.print_exc() # 打印详细错误信息到控制台
            QMessageBox.critical(self, "频谱分析失败", f"计算频谱切片时发生错误: {e}")

    def _update_dependent_widgets(self):
        """
        根据主开关的状态，启用或禁用其下属的复选框。
        """
        is_f0_on = self.show_f0_toggle.isChecked()
        self.show_f0_points_checkbox.setEnabled(is_f0_on)
        self.show_f0_derived_checkbox.setEnabled(is_f0_on)
        # if not is_f0_on: # [核心] 注释掉或删除这两行
        #     self.show_f0_points_checkbox.setChecked(False) # [核心] 注释掉或删除这两行
        #     self.show_f0_derived_checkbox.setChecked(False) # [核心] 注释掉或删除这两行

        is_intensity_on = self.show_intensity_toggle.isChecked()
        self.smooth_intensity_checkbox.setEnabled(is_intensity_on)
        # if not is_intensity_on: # [核心] 注释掉或删除这一行
        #     self.smooth_intensity_checkbox.setChecked(False) # [核心] 注释掉或删除这一行

        is_formants_on = self.show_formants_toggle.isChecked()
        self.highlight_f1_checkbox.setEnabled(is_formants_on)
        self.highlight_f2_checkbox.setEnabled(is_formants_on)
        self.show_other_formants_checkbox.setEnabled(is_formants_on)
        # if not is_formants_on: # [核心] 注释掉或删除这三行
        #     self.highlight_f1_checkbox.setChecked(False) # [核心] 注释掉或删除这三行
        #     self.highlight_f2_checkbox.setChecked(False) # [核心] 注释掉或删除这三行
        #     self.show_other_formants_checkbox.setChecked(False) # [核心] 注释掉或删除这三行

    def update_overlays(self):
        """
        根据UI设置更新语谱图上叠加层的可见性。
        """
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
    
    def on_selection_changed(self, selection):
        """
        当语谱图或波形图上的选区改变时被调用。
        Args:
            selection (tuple or None): (start_sample, end_sample) 元组或 None。
        """
        self.current_selection = selection # 更新当前选区状态
        if self.is_playing_selection and selection is None:
            # 如果正在播放选区时选区被清除了，则停止播放
            self.player.stop()
            self.is_playing_selection = False
            self.is_player_ready = False # 重置预热标志

    def zoom_to_selection(self, start_sample, end_sample):
        """
        将视图缩放到给定的采样点范围。
        Args:
            start_sample (int): 目标视图的起始采样点。
            end_sample (int): 目标视图的结束采样点。
        """
        if self.audio_data is None:
            return
        # 确保范围有效，如果结束点不大于起始点，则至少设为起始点+1
        if end_sample <= start_sample:
            end_sample = start_sample + 1
            
        self.waveform_widget.set_view_window(start_sample, end_sample) # 更新波形图视图
        self.on_view_changed(start_sample, end_sample) # 触发视图改变事件，同步其他控件

    def on_view_changed(self, start_sample, end_sample):
        """
        当视图范围改变时（由波形图发出信号）被调用，用于同步滚动条和语谱图。
        Args:
            start_sample (int): 当前视图的起始采样点。
            end_sample (int): 当前视图的结束采样点。
        """
        if self.audio_data is None:
            self.h_scrollbar.setEnabled(False)
            self.time_axis_widget.hide() # 确保隐藏时间轴
            return

        total_samples = len(self.audio_data)
        view_width = end_sample - start_sample

        # 更新滚动条的范围和值
        self.h_scrollbar.setRange(0, total_samples - view_width) # 滚动条范围
        self.h_scrollbar.setPageStep(view_width) # 页面步长（点击滚动条空白处移动的距离）
        self.h_scrollbar.setValue(start_sample) # 滚动条当前值
        self.h_scrollbar.setEnabled(total_samples > view_width) # 只有当总长大于视图宽度时才启用滚动条
        
        # 同步语谱图视图
        self.spectrogram_widget.set_view_window(start_sample, end_sample)
        
        # 控制和更新时间轴的显示
        # 如果视图宽度和总宽度几乎一样（允许1个采样点的误差），则认为是全览，隐藏时间轴
        if abs(view_width - total_samples) < 2:
            self.time_axis_widget.hide()
        else:
            self.time_axis_widget.update_view(start_sample, end_sample, self.sr) # 更新时间轴视图
            self.time_axis_widget.show() # 显示时间轴

    def update_position(self, position):
        """
        更新播放进度和光标位置。
        Args:
            position (int): 当前播放位置（毫秒）。
        """
        # 检查是否超出选区播放范围
        if self.is_playing_selection and self.current_selection:
            selection_end_ms = (self.current_selection[1] / self.sr) * 1000 # 选区结束时间（毫秒）
            if position >= selection_end_ms:
                self.player.stop() # 停止播放
                # 停止后将滑块和光标设回选区起点
                selection_start_ms = (self.current_selection[0] / self.sr) * 1000
                self.player.setPosition(int(selection_start_ms))
                self.playback_slider.setValue(int(selection_start_ms))
                self.spectrogram_widget.update_playback_position(selection_start_ms)
                return # 提前返回，避免下面的常规更新

        if not self.playback_slider.isSliderDown(): # 如果用户没有拖动滑块
            self.playback_slider.setValue(position) # 更新滑块位置
        
        self.time_label.setText(f"{self.format_time(position)} / {self.format_time(self.known_duration)}") # 更新时间标签
        self.spectrogram_widget.update_playback_position(position) # 更新语谱图的播放光标

    def toggle_playback(self):
        """
        切换播放/暂停状态。
        """
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause() # 如果正在播放，则暂停
        else:
            # 检查是否有选区，并且不是从暂停状态恢复（如果是恢复，则从当前位置继续）
            if self.current_selection and self.player.state() != QMediaPlayer.PausedState:
                start_sample, end_sample = self.current_selection
                start_ms = (start_sample / self.sr) * 1000 # 选区起始时间（毫秒）
                
                self.is_playing_selection = True # 标记正在播放选区
                self.player.setPosition(int(start_ms)) # 设置播放位置到选区起点
                self.player.play() # 播放
            else:
                # 原有逻辑：从当前位置播放或恢复播放
                self.is_playing_selection = False # 标记不是在播放选区
                self.player.play() # 播放

    def on_media_status_changed(self, status):
        """
        当播放器媒体状态改变时调用，用于处理可靠的预热。
        """
        # 1. 检查状态是否为“已加载媒体”
        if status == QMediaPlayer.LoadedMedia:
            # 2. 获取并记录总时长
            duration = self.player.duration()
            if duration > 0:
                self.known_duration = duration
                # 3. 更新所有与时长相关的UI
                self.playback_slider.setRange(0, int(self.known_duration))
                self.time_label.setText(f"00:00.00 / {self.format_time(self.known_duration)}")
                self.duration_label.setText(self.format_time(self.known_duration)) # 同时更新左侧信息面板
                # 4. 启用播放控件
                self.play_pause_btn.setEnabled(True)
                self.playback_slider.setEnabled(True)
                # 5. 设置预热完成标志
                self.is_player_ready = True

        # 可以在此处理其他状态，例如媒体加载失败
        elif status == QMediaPlayer.InvalidMedia:
            QMessageBox.warning(self, "媒体无效", f"无法播放文件: {self.current_filepath}\n文件可能已损坏或格式不受支持。")
            # 禁用播放控件，防止用户点击
            self.play_pause_btn.setEnabled(False)
            self.playback_slider.setEnabled(False)

    def on_player_state_changed(self, state):
        """
        当播放器状态改变时（播放、暂停、停止）被调用，更新播放按钮的图标和文本。
        Args:
            state (QMediaPlayer.State): 播放器当前状态。
        """
        if state == QMediaPlayer.PlayingState:
            self.play_pause_btn.setIcon(self.icon_manager.get_icon("pause")) # 设置为暂停图标
            self.play_pause_btn.setText("暂停")
        else:
            self.play_pause_btn.setIcon(self.icon_manager.get_icon("play")) # 设置为播放图标
            self.play_pause_btn.setText("播放")
            self.is_playing_selection = False # 播放结束后清除标记

    def clear_all(self):
        """
        清除所有音频数据、分析结果和UI状态，恢复到初始状态。
        """
        # 关闭进度对话框（如果存在）
        if hasattr(self, 'progress_dialog') and self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.close()
        self.progress_dialog = None # 清除引用

        if self.player.state() != QMediaPlayer.StoppedState:
            self.player.stop() # 停止播放器

        self.waveform_widget.clear() # 清除波形图数据
        self.spectrogram_widget.clear() # 清除语谱图数据（包括选区）

        # 重置信息标签
        for label in [self.filename_label, self.duration_label, self.samplerate_label, self.channels_label, self.bitdepth_label]:
            label.setText("N/A")
        
        self.time_label.setText("00:00.00 / 00:00.00")
        self.play_pause_btn.setEnabled(False)
        self.playback_slider.setEnabled(False)
        self.analysis_actions_group.setEnabled(False)
        
        # 重置两个新的滑块到它们的默认值
        self.render_density_slider.setValue(4)
        self.formant_density_slider.setValue(5)

        self.known_duration = 0
        self.audio_data, self.sr, self.overview_data, self.current_filepath = None, None, None, None
        
        # 确保重置选区状态
        self.current_selection = None
        self.is_playing_selection = False
        self.time_axis_widget.hide() # 确保时间轴隐藏

    def _update_render_density_label(self, value):
        """
        更新渲染精细度滑块旁边的文本标签。
        Args:
            value (int): 滑块的当前值。
        """
        self.render_density_label.setText(f"{self.DENSITY_LABELS.get(value, '未知')}")

    def _update_formant_density_label(self, value):
        """
        更新共振峰精细度滑块旁边的文本标签。
        Args:
            value (int): 滑块的当前值。
        """
        self.formant_density_label.setText(f"{self.DENSITY_LABELS.get(value, '未知')}")

    def on_load_finished(self, result):
        """
        [修改后] 音频加载任务完成时的槽函数。
        """
        if self.progress_dialog: self.progress_dialog.close()
        
        self.audio_data, self.sr, self.overview_data = result['y_full'], result['sr'], result['y_overview']
        info = sf.info(self.current_filepath)
        self.filename_label.setText(os.path.basename(self.current_filepath))
        # --- [核心修改] 不再在这里设置 known_duration 和启用播放控件 ---
        # self.known_duration = info.duration * 1000 # <-- 移除
        # self.duration_label.setText(self.format_time(self.known_duration)) # <-- 移除
        self.time_label.setText("加载中...") # 可以给一个提示
        self.samplerate_label.setText(f"{info.samplerate} Hz")
        channel_desc = {1: "Mono", 2: "Stereo"}.get(info.channels, f"{info.channels} Channels")
        self.channels_label.setText(f"{info.channels} ({channel_desc})")
        bit_depth_str = info.subtype.replace('PCM_', '') + "-bit PCM" if 'PCM' in info.subtype else info.subtype
        self.bitdepth_label.setText(bit_depth_str if bit_depth_str else "N/A")
        
        self.waveform_widget.set_audio_data(self.audio_data, self.sr, self.overview_data)
        
        # --- [核心修改] 重置预热标志并设置媒体 ---
        self.is_player_ready = False # 每次加载新文件时重置
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(self.current_filepath)))
        
        # --- [核心修改] 不再在这里启用播放控件 ---
        # self.play_pause_btn.setEnabled(True) # <-- 移除
        # self.playback_slider.setEnabled(True) # <-- 移除
        self.analysis_actions_group.setEnabled(True)
        self.analyze_acoustics_button.setEnabled(False)
        self.analyze_acoustics_button.setToolTip("请先运行“分析语谱图”以启用此功能。")


        if self._pending_csv_path:
            self._apply_csv_data(self._pending_csv_path)
            self._pending_csv_path = None

    def run_acoustics_analysis(self):
        """
        [已简化] 启动分块声学分析。
        此时语谱图已存在，直接使用其hop_length。
        """
        if self.audio_data is None:
            QMessageBox.warning(self, "无音频", "请先加载音频文件。")
            return
        
        # 安全检查，确保语谱图已生成
        if self.spectrogram_widget.spectrogram_image is None:
             QMessageBox.warning(self, "需要语谱图", "请先运行“分析语谱图”。")
             return

        # 清除旧的F0/强度数据
        self.spectrogram_widget.set_analysis_data(
            f0_data=None, f0_derived_data=None, intensity_data=None, 
            clear_previous_formants=False
        )
        
        f0_min = self.f0_range_slider.lowerValue()
        f0_max = self.f0_range_slider.upperValue()
        
        if f0_min >= f0_max:
            QMessageBox.warning(self, "参数错误", "F0范围的最小值必须小于最大值。")
            return

        # [核心修改] 直接使用语谱图的hop_length，不再需要复杂的检查
        forced_hop_length = self.spectrogram_widget.hop_length

        self.run_task('analyze_acoustics', 
                      audio_data=self.audio_data,
                      sr=self.sr, 
                      forced_hop_length=forced_hop_length,
                      pre_emphasis=self.pre_emphasis_checkbox.isChecked(), 
                      f0_min=f0_min, 
                      f0_max=f0_max,
                      chunk_size_ms=self.chunk_size_slider.value(),
                      chunk_overlap_ms=self.chunk_overlap_slider.value(),
                      progress_text="正在实时分析 F0 和强度...")

    # [新增] 用于语谱图分析的新方法
    def run_spectrogram_analysis(self):
        """
        [已修复] 运行语谱图背景分析。
        这会建立一个新的“黄金标准”分辨率，因此必须清除所有旧的叠加数据。
        """
        if self.audio_data is None:
            QMessageBox.warning(self, "无音频", "请先加载音频文件。")
            return

        # [关键修复逻辑]
        # 因为要生成新的背景，所以必须清除所有旧的、可能不匹配的叠加数据。
        self.spectrogram_widget.set_analysis_data(
            f0_data=None, f0_derived_data=None, intensity_data=None, 
            formants_data=None, clear_previous_formants=True
        )

        self.run_task('analyze_spectrogram',
                      audio_data=self.audio_data,
                      sr=self.sr,
                      is_wide_band=self.spectrogram_type_checkbox.isChecked(),
                      render_density=self.render_density_slider.value(),
                      pre_emphasis=self.pre_emphasis_checkbox.isChecked(),
                      progress_text="正在分析语谱图背景...")

    def run_view_formant_analysis(self):
        """
        运行可见区域的共振峰分析。
        """
        if self.audio_data is None:
            QMessageBox.warning(self, "无音频", "请先加载音频文件。")
            return
        
        # 获取当前视图的起始和结束采样点
        start, end = self.waveform_widget._view_start_sample, self.waveform_widget._view_end_sample
        
        # 从新的 formant_density_slider 计算 hop_length
        narrow_band_window_s = 0.035
        base_n_fft_for_hop = 1 << (int(self.sr * narrow_band_window_s) - 1).bit_length()
        overlap_ratio = 1 - (1 / (2**self.formant_density_slider.value())) # 根据共振峰精细度计算重叠比例
        hop_length = int(base_n_fft_for_hop * (1 - overlap_ratio)) or 1 # 计算跳跃长度，确保至少为1
        
        self.run_task('analyze_formants_view', 
                      audio_data=self.audio_data, 
                      sr=self.sr, 
                      start_sample=start, 
                      end_sample=end, 
                      hop_length=hop_length, 
                      pre_emphasis=self.pre_emphasis_checkbox.isChecked(), 
                      progress_text="正在分析可见区域共振峰...")

    # [新增] 处理声学分析结果的回调
    def on_acoustics_finished(self, results):
        """
        声学分析（F0、强度）任务完成时的槽函数。
        """
        if self.progress_dialog: self.progress_dialog.close()

        # 清除旧的F0和强度数据，但保留共振峰和语谱图背景
        self.spectrogram_widget.set_analysis_data(
            f0_data=results.get('f0_raw'),
            f0_derived_data=results.get('f0_derived'),
            intensity_data=results.get('intensity'),
            formants_data=self.spectrogram_widget._formants_data, # 保留现有的共振峰
            clear_previous_formants=False
        )

    # [新增] 处理语谱图分析结果的回调
    def on_spectrogram_finished(self, results):
        """
        语谱图分析任务完成时的槽函数。
        """
        if self.progress_dialog: self.progress_dialog.close()

        # 检查后台任务是否真的返回了语谱图数据
        if 'S_db' in results and 'hop_length' in results:
            hop_length = results.get('hop_length', 256)
            self.spectrogram_widget.set_data(results.get('S_db'), self.sr, hop_length)

            # [核心修改] 启用F0分析按钮并更新提示
            self.analyze_acoustics_button.setEnabled(True)
            self.analyze_acoustics_button.setToolTip("快速运行基频（F0）和强度分析。\n结果将叠加在当前语谱图上。")
        else:
            # 如果后台任务因某些原因（如被取消）未返回有效数据，则不启用按钮
            pass

    def on_formant_view_finished(self, results):
        """
        [已修复] 当仅分析视图内共振峰的任务完成时调用。
        """
        if self.progress_dialog:
            self.progress_dialog.close()
    
        formant_data = results.get('formants_view', [])
    
        # [关键修复] 调用新的、专门的方法来只更新共振峰数据，
        # 这样就不会再清除已经存在的F0和强度数据了。
        self.spectrogram_widget.update_formants_data(
            formants_data=formant_data, 
            clear_previous=True  # 替换旧的共振峰数据，而不是追加
        )
    
        QMessageBox.information(
            self, 
            "分析完成", 
            f"已在可见区域找到并显示了 {len(formant_data)} 个有效音框的共振峰。"
        )

    def on_scrollbar_moved(self, value):
        """
        当水平滚动条移动时被调用，用于更新视图窗口。
        Args:
            value (int): 滚动条的当前值（代表起始采样点）。
        """
        if self.audio_data is None: return
        
        view_width = self.waveform_widget._view_end_sample - self.waveform_widget._view_start_sample # 当前视图宽度
    
        start_sample = value
        end_sample = value + view_width

        # 更新波形和语谱图的视图窗口
        self.waveform_widget.set_view_window(start_sample, end_sample)
        self.spectrogram_widget.set_view_window(start_sample, end_sample)

        # 同步更新时间轴
        self.time_axis_widget.update_view(start_sample, end_sample, self.sr)

    def update_duration(self, duration):
        """
        当播放器获取到时长时被调用。
        主要用于在某些特殊情况下（如流媒体）更新时长。
        大部分初始化工作已移至 on_media_status_changed。
        """
        # 只有在媒体已经准备好之后，才更新时长，防止在加载过程中出现跳动
        if duration > 0 and self.is_player_ready:
            self.known_duration = duration
            self.playback_slider.setRange(0, int(self.known_duration))
            # 可以在这里也更新一下时间标签，以防万一
            self.time_label.setText(f"{self.format_time(self.player.position())} / {self.format_time(self.known_duration)}")

    def run_task(self, task_type, progress_text="正在处理...", **kwargs):
        """
        [最终版] 启动一个后台任务。
        根据任务类型，智能选择显示“确切进度”或“滚动中”的进度条。
        """
        if self.is_task_running:
            QMessageBox.warning(self, "操作繁忙", "请等待当前分析任务完成后再试。")
            return
        
        self.is_task_running = True
        
        # [核心修改] 根据任务类型决定进度条的样式
        if task_type == 'analyze_acoustics':
            # F0分析是分块的，可以计算确切进度，所以使用范围(0, 100)
            min_val, max_val = 0, 100
        else:
            # 其他任务（加载、语谱图、共振峰）是整体完成的，
            # 设置min和max都为0，使其显示为“滚动中”的繁忙样式。
            min_val, max_val = 0, 0
        
        # 使用上面决定的值来创建进度对话框
        self.progress_dialog = QProgressDialog(progress_text, "取消", min_val, max_val, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setValue(0) # 初始值设为0
        self.progress_dialog.show()
        
        self.task_thread = QThread()
        self.worker = AudioTaskWorker(task_type, **kwargs)
        self.worker.moveToThread(self.task_thread)

        # --- 连接信号（这部分逻辑保持不变）---
        self.task_thread.started.connect(self.worker.run)
        self.worker.error.connect(self.on_task_error)
        
        self.worker.finished.connect(self.task_thread.quit)
        self.worker.error.connect(self.task_thread.quit)

        if task_type == 'load':
            self.worker.finished.connect(self.on_load_finished)
        elif task_type == 'analyze_acoustics':
            self.worker.chunk_finished.connect(self.on_acoustics_chunk_finished)
            self.worker.finished.connect(self.on_acoustics_analysis_done)
        elif task_type == 'analyze_spectrogram':
            self.worker.finished.connect(self.on_spectrogram_finished)
        elif task_type == 'analyze_formants_view':
            self.worker.finished.connect(self.on_formant_view_finished)
        
        self.task_thread.finished.connect(self.on_thread_finished)
        self.worker.deleteLater()
        self.task_thread.finished.connect(self.task_thread.deleteLater)

        if self.progress_dialog:
            self.progress_dialog.canceled.connect(self.task_thread.requestInterruption)
        
        self.task_thread.start()

    def load_audio_file(self, filepath):
        """
        加载音频文件。
        Args:
            filepath (str): 音频文件路径。
        """
        self.clear_all() # 清除所有旧状态
        self.current_filepath = filepath # 记录当前文件路径
        self.run_task('load', filepath=filepath, progress_text=f"正在加载音频...") # 运行加载任务

    def open_file_dialog(self):
        """
        打开文件对话框，让用户选择音频文件。
        """
        filepath, _ = QFileDialog.getOpenFileName(self, "选择音频文件", "", "音频文件 (*.wav *.mp3 *.flac *.ogg *.m4a);;所有文件 (*.*)")
        if filepath:
            self.load_audio_file(filepath)

    def dragEnterEvent(self, event):
        """
        处理拖放进入事件。
        如果拖入的是本地文件URL，并且是支持的音频或CSV格式，则接受拖放。
        """
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile():
                filepath = url.toLocalFile().lower()
                # 接受音频文件或CSV文件
                if filepath.endswith(('.wav', '.mp3', '.flac', 'ogg', '.m4a', '.csv')):
                    event.acceptProposedAction()

    def dropEvent(self, event):
        """
        处理拖放事件。
        根据拖入的文件类型（音频或CSV）分派不同的处理任务。
        """
        if event.mimeData().hasUrls():
            filepath = event.mimeData().urls()[0].toLocalFile()
            if filepath.lower().endswith('.csv'):
                self.load_from_csv(filepath) # 如果是CSV文件，加载CSV数据
            else:
                self.load_audio_file(filepath) # 如果是音频文件，加载音频

    def on_thread_finished(self):
        """
        [已修复] 后台任务线程结束时的最终清理槽函数。
        无论任务是正常完成、被取消还是出错，此方法都必须被调用。
        """
        # 确保进度对话框被关闭
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        # 安全地清理线程和工作器引用
        self.task_thread = None
        self.worker = None
        
        # [关键修复] 在这里重置任务运行标志
        self.is_task_running = False

    def on_task_error(self, error_msg):
        """
        [已修复] 后台任务发生错误时的槽函数。
        现在它只负责显示错误信息，所有清理工作由 on_thread_finished 完成。
        """
        # 注意：不再在这里关闭进度条或重置 is_task_running，
        # 因为 on_thread_finished 会统一处理。
        import traceback
        traceback.print_exc() # 打印详细的堆栈信息到控制台，便于调试
        QMessageBox.critical(self, "任务失败", f"处理过程中发生错误:\n{error_msg}")
        # 可选：可以清除部分UI状态，但保留已加载的音频
        self.spectrogram_widget.set_analysis_data(None, None, None, None)

    def update_icons(self):
        """
        更新UI中所有按钮的图标。
        """
        self.open_file_btn.setIcon(self.icon_manager.get_icon("open_file"))
        self.on_player_state_changed(self.player.state()) # 根据播放器状态更新播放/暂停按钮图标

        self.analyze_acoustics_button.setIcon(self.icon_manager.get_icon("chart2"))
        self.analyze_spectrogram_button.setIcon(self.icon_manager.get_icon("wav"))
        formant_icon = self.icon_manager.get_icon("analyze_dark")
        if formant_icon.isNull(): formant_icon = self.icon_manager.get_icon("analyze") # 如果特定图标不存在，使用通用图标
        self.analyze_formants_button.setIcon(formant_icon)

    def format_time(self, ms):
        """
        将毫秒数格式化为 "MM:SS.ms" 字符串。
        Args:
            ms (int): 毫秒数。
        Returns:
            str: 格式化后的时间字符串。
        """
        if ms <= 0: return "00:00.00"
        td = timedelta(milliseconds=ms)
        minutes, seconds = divmod(td.seconds, 60)
        milliseconds = td.microseconds // 10000 # 取百分之一秒
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:02d}"

    def handle_export_image(self):
        """
        处理将当前视图以高质量渲染并导出为图片的请求。
        """
        if self.current_filepath is None:
            QMessageBox.warning(self, "无音频", "请先加载音频文件。")
            return

        # 1. 弹出对话框让用户选择导出选项
        dialog = ExportDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return # 用户取消

        options = dialog.get_options() # 获取用户选择的选项

        # 2. 获取保存路径
        base_name = os.path.splitext(os.path.basename(self.current_filepath))[0]
        default_path = os.path.join(os.path.dirname(self.current_filepath), f"{base_name}_view.png")
        save_path, _ = QFileDialog.getSaveFileName(self, "保存视图为图片", default_path, "PNG 图片 (*.png);;JPEG 图片 (*.jpg)")
        
        if not save_path: return # 用户取消保存

        # 3. 执行高质量渲染并保存
        try:
            pixmap = self.render_high_quality_image(options) # 渲染图片
            if not pixmap.save(save_path): # 保存图片
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
        Args:
            options (dict): 导出选项，包含分辨率、是否添加信息标签和时间轴。
        Returns:
            QPixmap: 渲染后的高质量图片。
        """
        source_widget = self.spectrogram_widget # 源语谱图控件
        resolution = options["resolution"]
        
        # --- 定义固定的UI元素尺寸 ---
        INFO_FONT_PIXEL_SIZE = 14
        TIME_AXIS_FONT_PIXEL_SIZE = 12
        SPECTROGRAM_AXIS_FONT_PIXEL_SIZE = 12
        TIME_AXIS_HEIGHT = 35 # 固定像素高度

        if resolution is None:
            # 如果分辨率为None，表示使用当前控件的尺寸
            target_width, target_height = source_widget.width(), source_widget.height()
        else:
            target_width, target_height = resolution
        
        # --- 布局计算 (使用固定高度) ---
        axis_height = TIME_AXIS_HEIGHT if options["add_time_axis"] else 0 # 时间轴高度
        spectrogram_height = target_height - axis_height # 语谱图绘制区域高度

        # --- 创建渲染目标 ---
        pixmap = QPixmap(target_width, target_height) # 创建目标QPixmap
        pixmap.fill(source_widget.backgroundColor) # 填充背景色

        # --- 渲染语谱图部分 ---
        if spectrogram_height > 0:
            # 创建一个临时的 SpectrogramWidget 用于渲染，不显示在屏幕上
            temp_widget = SpectrogramWidget(None, self.icon_manager)
            temp_widget.setAttribute(Qt.WA_DontShowOnScreen) # 不显示在屏幕上
            temp_widget.show() # 需要show才能正确渲染

            # **核心修改**: 为临时控件设置固定的字体大小，确保轴标签大小一致
            fixed_font = QFont()
            fixed_font.setPixelSize(SPECTROGRAM_AXIS_FONT_PIXEL_SIZE)
            temp_widget.setFont(fixed_font)
            
            # 复制源控件的所有可写属性到临时控件
            meta_obj = temp_widget.metaObject()
            for i in range(meta_obj.propertyOffset(), meta_obj.propertyCount()):
                prop = meta_obj.property(i)
                if prop.isWritable():
                    temp_widget.setProperty(prop.name(), source_widget.property(prop.name()))
            
            # 复制数据和视图状态
            temp_widget.spectrogram_image = source_widget.spectrogram_image
            temp_widget.sr = source_widget.sr
            temp_widget.hop_length = source_widget.hop_length
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

            temp_widget.resize(target_width, spectrogram_height) # 设置临时控件的大小
            
            # 将临时控件的内容渲染到QPixmap的指定区域
            temp_widget.render(pixmap, QPoint(0, 0), QRegion(0, 0, target_width, spectrogram_height))

            temp_widget.hide() # 隐藏临时控件
            temp_widget.deleteLater() # 延迟删除，确保事件循环处理完毕

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # --- 渲染时间轴部分 ---
        if options["add_time_axis"] and axis_height > 0:
            axis_rect = QRect(0, spectrogram_height, target_width, axis_height) # 时间轴绘制区域
            
            view_start_sample = source_widget._view_start_sample
            view_end_sample = source_widget._view_end_sample
            sr = source_widget.sr
            view_duration_s = (view_end_sample - view_start_sample) / sr if sr > 0 else 0
            start_time_s = view_start_sample / sr if sr > 0 else 0

            # 智能计算时间轴刻度
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
                painter.setPen(source_widget.palette().color(QPalette.Text)) # 使用文本颜色

                first_tick_time = math.ceil(start_time_s / interval) * interval
                
                for i in range(int(target_ticks * 2)):
                    tick_time = first_tick_time + i * interval
                    if tick_time > start_time_s + view_duration_s: break

                    x_pos = (tick_time - start_time_s) / view_duration_s * target_width if view_duration_s > 0 else 0
                    
                    painter.drawLine(int(x_pos), axis_rect.top(), int(x_pos), axis_rect.top() + 5) # 绘制刻度线
                    
                    # 根据间隔调整时间标签的精度
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
            painter.setPen(QColor(Qt.darkGray)) # 设置信息标签颜色
            
            info_text = f"File: {os.path.basename(self.current_filepath)}\n" \
                        f"Duration: {self.format_time(self.known_duration)}\n" \
                        f"Sample Rate: {self.sr} Hz"
            
            margin = 15 # 固定边距
            text_rect = QRect(0, 0, target_width - margin, target_height - margin) # 文本绘制区域
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignTop, info_text) # 右上角对齐绘制文本
        
        painter.end() # 结束绘制
        return pixmap

    def handle_export_csv(self):
        """
        处理将选区内的分析数据导出为CSV的请求。
        """
        if self.current_selection is None or self.sr is None:
            QMessageBox.warning(self, "无选区", "请先选择一个区域以导出分析数据。")
            return

        start_s = self.current_selection[0] / self.sr # 选区起始时间（秒）
        end_s = self.current_selection[1] / self.sr   # 选区结束时间（秒）
        
        base_name = os.path.splitext(os.path.basename(self.current_filepath))[0]
        default_path = os.path.join(os.path.dirname(self.current_filepath), f"{base_name}_analysis_{start_s:.2f}-{end_s:.2f}s.csv")
        
        save_path, _ = QFileDialog.getSaveFileName(self, "导出分析数据为CSV", default_path, "CSV 文件 (*.csv)")

        if not save_path: return # 用户取消保存

        try:
            # 准备数据
            all_data = []

            # F0 数据
            if self.spectrogram_widget._f0_data:
                times, f0_vals = self.spectrogram_widget._f0_data
                for t, f0 in zip(times, f0_vals):
                    if start_s <= t < end_s: # 筛选选区内的数据
                        all_data.append({'timestamp': t, 'f0_hz': f0})

            # 强度数据
            if self.spectrogram_widget._intensity_data is not None:
                hop_length = self.spectrogram_widget.hop_length
                # 计算强度数据对应的时间戳
                intensity_times = librosa.frames_to_time(np.arange(len(self.spectrogram_widget._intensity_data)), sr=self.sr, hop_length=hop_length)
                for t, intensity in zip(intensity_times, self.spectrogram_widget._intensity_data):
                     if start_s <= t < end_s: # 筛选选区内的数据
                        all_data.append({'timestamp': t, 'intensity': intensity})
            
            # 共振峰数据
            if self.spectrogram_widget._formants_data:
                for sample_pos, formants in self.spectrogram_widget._formants_data:
                    t = sample_pos / self.sr # 采样点转换为时间
                    if start_s <= t < end_s: # 筛选选区内的数据
                        formant_dict = {'timestamp': t}
                        for i, f in enumerate(formants):
                            formant_dict[f'f{i+1}_hz'] = f # 格式化共振峰列名
                        all_data.append(formant_dict)
            
            if not all_data:
                QMessageBox.warning(self, "无数据", "在选定区域内没有可导出的分析数据。")
                return

            # 合并数据：按时间戳分组并取第一个值，然后排序
            df = pd.DataFrame(all_data)
            df = df.groupby('timestamp').first().reset_index() # 合并同一时间戳的数据
            df = df.sort_values(by='timestamp').round(4) # 排序并四舍五入到4位小数
            
            df.to_csv(save_path, index=False, encoding='utf-8-sig') # 保存为CSV文件，不包含索引，使用UTF-8 BOM编码
            QMessageBox.information(self, "导出成功", f"分析数据已成功导出到CSV文件:\n{save_path}")

        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出CSV时发生错误: {e}")

    def handle_export_wav(self):
        """
        处理将选区音频导出为WAV的请求。
        """
        if self.current_selection is None or self.audio_data is None:
            QMessageBox.warning(self, "无选区", "请先选择一个区域以导出音频。")
            return

        start_sample, end_sample = self.current_selection # 获取选区采样点范围
        
        start_s = start_sample / self.sr # 选区起始时间（秒）
        end_s = end_sample / self.sr   # 选区结束时间（秒）

        base_name = os.path.splitext(os.path.basename(self.current_filepath))[0]
        default_path = os.path.join(os.path.dirname(self.current_filepath), f"{base_name}_slice_{start_s:.2f}-{end_s:.2f}s.wav")
        
        save_path, _ = QFileDialog.getSaveFileName(self, "导出音频切片为WAV", default_path, "WAV 音频 (*.wav)")
        
        if save_path:
            try:
                audio_slice = self.audio_data[start_sample:end_sample] # 提取音频切片
                sf.write(save_path, audio_slice, self.sr) # 保存为WAV文件
                QMessageBox.information(self, "导出成功", f"音频切片已成功保存到:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"保存音频切片时发生错误: {e}")

    def load_from_csv(self, csv_path):
        """
        处理拖入的CSV文件，查找关联音频并加载。
        Args:
            csv_path (str): 拖入的CSV文件路径。
        """
        try:
            # 1. 解析文件名以找到原始音频文件的基本名称
            filename = os.path.basename(csv_path)
            match = re.match(r'(.+)_analysis_.*\.csv', filename)
            if not match:
                QMessageBox.warning(self, "文件名格式不匹配", "无法从此CSV文件名中识别出原始音频文件。\n\n文件名应为 '[原始文件名]_analysis_...' 格式。")
                return
            
            base_name = match.group(1) # 提取原始文件名部分
            csv_dir = os.path.dirname(csv_path) # CSV文件所在目录

            # 2. 搜索关联的音频文件（支持多种格式）
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
            self._pending_csv_path = csv_path # 标记有待处理的CSV数据
            self.load_audio_file(audio_path) # 加载关联的音频文件

        except Exception as e:
            QMessageBox.critical(self, "处理CSV失败", f"处理拖入的CSV文件时发生错误: {e}")

    def _apply_csv_data(self, csv_path):
        """
        读取CSV文件并将其中的分析数据应用到语谱图上。
        Args:
            csv_path (str): CSV文件路径。
        """
        try:
            df = pd.read_csv(csv_path)
            if 'timestamp' not in df.columns:
                QMessageBox.warning(self, "CSV格式错误", "CSV文件中缺少必需的 'timestamp' 列。")
                return

            # 清除旧的分析数据，但不清除语谱图背景本身
            self.spectrogram_widget.set_analysis_data(f0_data=None, intensity_data=None, formants_data=None, clear_previous_formants=True)

            # 准备新的数据容器
            f0_data, intensity_data, formants_data = None, None, []
            
            # --- 提取F0数据 ---
            if 'f0_hz' in df.columns:
                f0_df = df[['timestamp', 'f0_hz']].dropna() # 提取时间戳和F0，并去除NaN
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
            formant_cols = [col for col in df.columns if col.startswith('f') and col.endswith('_hz')] # 查找所有共振峰列
            if formant_cols:
                formant_df = df[['timestamp'] + formant_cols].dropna(subset=formant_cols, how='all') # 提取共振峰数据，去除全NaN行
                for _, row in formant_df.iterrows():
                    sample_pos = int(row['timestamp'] * self.sr) # 时间转换为采样点
                    formants = [row[col] for col in formant_cols if pd.notna(row[col])] # 提取有效的共振峰值
                    if formants:
                        formants_data.append((sample_pos, formants)) # 添加到共振峰数据列表
            
            # 应用提取的数据到语谱图控件
            self.spectrogram_widget.set_analysis_data(
                f0_data=f0_data,
                intensity_data=intensity_data,
                formants_data=formants_data,
                clear_previous_formants=True
            )
            QMessageBox.information(self, "加载成功", "已从CSV加载分析数据。\n\n请注意，语谱图背景需要手动点击“运行完整分析”来生成。")

        except Exception as e:
            QMessageBox.critical(self, "应用CSV数据失败", f"读取并应用CSV数据时发生错误: {e}")

    def _on_persistent_setting_changed(self, key, value):
        """
        当用户更改任何可记忆的设置时，调用此方法以保存状态。
        Args:
            key (str): 设置的键名。
            value (any): 设置的新值。
        """
        # 调用父窗口的方法来更新并保存模块状态
        self.parent_window.update_and_save_module_state('audio_analysis', key, value)

    def _on_chunk_settings_changed(self):
        """
        当分块大小或重叠滑块的值改变时调用。
        """
        chunk_size = self.chunk_size_slider.value()
        chunk_overlap = self.chunk_overlap_slider.value()

        # 更新标签显示
        self.chunk_size_value_label.setText(f"{chunk_size} ms")
        self.chunk_overlap_value_label.setText(f"{chunk_overlap} ms")

        # 动态调整重叠滑块的最大值，确保重叠量小于块大小
        # 至少留出10ms的步进空间
        max_overlap = max(0, chunk_size - 10)
        self.chunk_overlap_slider.setMaximum(max_overlap)

        # 如果当前重叠值超过了新的最大值，则自动修正
        if chunk_overlap > max_overlap:
            self.chunk_overlap_slider.setValue(max_overlap)
        
        # 保存设置
        self._on_persistent_setting_changed('chunk_size_ms', chunk_size)
        self._on_persistent_setting_changed('chunk_overlap_ms', self.chunk_overlap_slider.value())

    def _load_persistent_settings(self):
        """
        [最终版] 加载并应用所有持久化的用户设置。
        此方法现在包含对新的分块大小、重叠滑块和F0轴手动范围的加载逻辑。
        """
        # 从全局配置中安全地获取本模块的状态字典，如果不存在则返回空字典
        module_states = self.parent_window.config.get("module_states", {}).get("audio_analysis", {})
        
        # 定义所有需要加载的常规控件及其属性、键名和默认值
        controls_to_load = [
            # 可视化选项 (Toggles & Checkboxes)
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
            
            # 语谱图与渲染设置
            (self.render_density_slider, 'setValue', 'render_density', 4),
            (self.formant_density_slider, 'setValue', 'formant_density', 5),
            (self.spectrogram_type_checkbox, 'setChecked', 'is_wide_band', False),
        ]

        # 批量加载常规设置
        for control, setter_method_name, key, default_value in controls_to_load:
            # 暂时阻塞信号，避免在加载设置时触发不必要的保存操作
            control.blockSignals(True)
            value_to_set = module_states.get(key, default_value)
            getattr(control, setter_method_name)(value_to_set)
            control.blockSignals(False)

        # --- 单独加载 F0 搜索范围滑块的值 ---
        self.f0_range_slider.blockSignals(True)
        lower_val = module_states.get('f0_min', 10)
        upper_val = module_states.get('f0_max', 700)
        self.f0_range_slider.setLowerValue(int(lower_val))
        self.f0_range_slider.setUpperValue(int(upper_val))
        self.f0_range_slider.blockSignals(False)
        self.f0_min_label.setText(str(self.f0_range_slider.lowerValue()))
        self.f0_max_label.setText(str(self.f0_range_slider.upperValue()))

        # --- 单独加载分块大小和重叠滑块的值 ---
        self.chunk_size_slider.blockSignals(True)
        self.chunk_overlap_slider.blockSignals(True)
        chunk_size = module_states.get('chunk_size_ms', 200)
        self.chunk_size_slider.setValue(chunk_size)
        max_overlap = max(0, chunk_size - 10)
        self.chunk_overlap_slider.setMaximum(max_overlap)
        chunk_overlap = module_states.get('chunk_overlap_ms', 10)
        self.chunk_overlap_slider.setValue(min(chunk_overlap, max_overlap))
        self.chunk_size_slider.blockSignals(False)
        self.chunk_overlap_slider.blockSignals(False)

        # --- [新增] 单独加载F0轴手动范围 ---
        self.f0_axis_range_slider.blockSignals(True)
        manual_range = module_states.get('f0_axis_manual_range', None)
        
        if manual_range and isinstance(manual_range, list) and len(manual_range) == 2:
            # 如果保存了手动范围，则应用它
            self.f0_axis_range_slider.setLowerValue(manual_range[0])
            self.f0_axis_range_slider.setUpperValue(manual_range[1])
            self.spectrogram_widget.set_f0_axis_range(manual_range[0], manual_range[1])
            self.f0_axis_min_label.setText(str(manual_range[0]))
            self.f0_axis_max_label.setText(str(manual_range[1]))
        else:
            # 否则，恢复到自动模式（滑块在两端）
            self.f0_axis_range_slider.setLowerValue(self.f0_axis_range_slider.minimum())
            self.f0_axis_range_slider.setUpperValue(self.f0_axis_range_slider.maximum())
            self.spectrogram_widget.set_f0_axis_range(None, None)
            self.f0_axis_min_label.setText("Auto")
            self.f0_axis_max_label.setText("Auto")
            
        self.f0_axis_range_slider.blockSignals(False)

        # --- 最后，手动触发一次所有依赖UI的更新 ---
        self._update_dependent_widgets()
        self.update_overlays()
        self._update_render_density_label(self.render_density_slider.value())
        self._update_formant_density_label(self.formant_density_slider.value())
        self._on_chunk_settings_changed()


# SpectrumSliceDialog 类：显示频谱切片的对话框
class SpectrumSliceDialog(QDialog):
    """一个显示频谱切片的对话框。"""
    def __init__(self, freqs, mags_db, time_s, sr, parent=None):
        """
        初始化频谱切片对话框。
        Args:
            freqs (np.ndarray): 频率数组。
            mags_db (np.ndarray): 幅度（分贝）数组。
            time_s (float): 频谱切片对应的时间（秒）。
            sr (int): 采样率。
            parent (QWidget, optional): 父控件。
        """
        super().__init__(parent)
        self.freqs = freqs
        self.mags_db = mags_db
        self.time_s = time_s
        self.sr = sr
        
        self.setWindowTitle(f"频谱切片 @ {self.time_s:.3f} s") # 设置窗口标题
        self.setMinimumSize(600, 400) # 设置最小尺寸
        
        layout = QVBoxLayout(self) # 垂直布局
        self.plot_widget = QWidget() # 绘图区域控件
        self.plot_widget.paintEvent = self.paint_plot # 重写 paintEvent 方法
        self.plot_widget.setMouseTracking(True) # 开启鼠标跟踪
        self.plot_widget.mouseMoveEvent = self.plot_mouse_move # 重写 mouseMoveEvent 方法
        layout.addWidget(self.plot_widget)

        self.info_label = QLabel(" ") # 显示鼠标悬停信息的标签
        self.info_label.setAlignment(Qt.AlignCenter) # 居中对齐
        layout.addWidget(self.info_label)
        
        self.max_freq = self.sr / 2 # 最大显示频率为奈奎斯特频率
        self.min_db = np.max(self.mags_db) - 80 # 显示80dB的动态范围
        self.max_db = np.max(self.mags_db) # 最大分贝值

    def paint_plot(self, event):
        """
        绘制频谱图。
        """
        painter = QPainter(self.plot_widget)
        painter.setRenderHint(QPainter.Antialiasing) # 开启抗锯齿
        
        # 调整绘图区域，留出边距用于坐标轴标签
        rect = self.plot_widget.rect().adjusted(40, 10, -10, -30)
        painter.fillRect(self.plot_widget.rect(), self.palette().color(QPalette.Window)) # 填充背景色

        if not rect.isValid(): return # 如果绘图区域无效，则不绘制
        
        # 绘制坐标轴边框
        painter.setPen(self.palette().color(QPalette.Mid))
        painter.drawRect(rect)
        
        # X轴 (频率)
        for i in range(6): # 绘制6个主刻度（0到5k，每1k一个）
            freq = i * self.max_freq / 5 # 计算频率值
            x = rect.left() + i * rect.width() / 5 # 计算X坐标
            painter.drawLine(int(x), rect.bottom(), int(x), rect.bottom() + 5) # 绘制刻度线
            painter.drawText(QPoint(int(x) - 20, rect.bottom() + 20), f"{freq/1000:.1f}k") # 绘制频率标签（kHz）
        painter.drawText(rect.center().x() - 20, rect.bottom() + 25, "频率 (Hz)") # 绘制X轴标签

        # Y轴 (幅度 dB)
        for i in range(5): # 绘制5个主刻度
            db = self.min_db + i * (self.max_db - self.min_db) / 4 # 计算分贝值
            y = rect.bottom() - i * rect.height() / 4 # 计算Y坐标
            painter.drawLine(rect.left(), int(y), rect.left() - 5, int(y)) # 绘制刻度线
            painter.drawText(QRect(0, int(y) - 10, rect.left() - 10, 20), Qt.AlignRight, f"{db:.0f}") # 绘制分贝标签
        
        # 绘制频谱曲线
        painter.setPen(QPen(self.palette().color(QPalette.Highlight), 2)) # 设置曲线颜色和粗细
        points = []
        for f, m_db in zip(self.freqs, self.mags_db):
            if f > self.max_freq: break # 超出最大显示频率则停止
            x = rect.left() + (f / self.max_freq) * rect.width() # 频率映射到X坐标
            # 幅度映射到Y坐标，并限制在0-1范围内
            y_ratio = (m_db - self.min_db) / (self.max_db - self.min_db) if (self.max_db - self.min_db) > 0 else 0
            y = rect.bottom() - max(0, min(1, y_ratio)) * rect.height()
            points.append(QPointF(x, y)) # 添加点到列表
        
        if points:
            painter.drawPolyline(*points) # 绘制频谱曲线
            
    def plot_mouse_move(self, event):
        """
        处理绘图区域内的鼠标移动事件，显示实时频率和幅度信息。
        """
        rect = self.plot_widget.rect().adjusted(40, 10, -10, -30) # 获取绘图区域
        if rect.contains(event.pos()): # 如果鼠标在绘图区域内
            x_ratio = (event.x() - rect.left()) / rect.width() # 计算X轴比例
            y_ratio = (rect.bottom() - event.y()) / rect.height() # 计算Y轴比例
            
            freq = x_ratio * self.max_freq # 像素X坐标转换为频率
            db = self.min_db + y_ratio * (self.max_db - self.min_db) # 像素Y坐标转换为分贝
            
            self.info_label.setText(f"频率: {freq:.1f} Hz  |  幅度: {db:.1f} dB") # 更新信息标签
        else:
            self.info_label.setText(" ") # 鼠标移出绘图区则清空信息
