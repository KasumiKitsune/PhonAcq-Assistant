# --- START OF FILE modules/audio_analysis_batch_panel.py ---
# --- 模块元数据 ---
MODULE_NAME = "音频批量分析组件"
MODULE_DESCRIPTION = "为音频分析模块提供批量处理功能，不直接作为独立标签页。"
import os
import sys
import time
import pandas as pd
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                             QFileDialog, QMessageBox, QMenu, QProgressDialog, QDialog,
                             QCheckBox, QDialogButtonBox, QFormLayout, QApplication, QRadioButton, QLineEdit, QGroupBox, QComboBox, QShortcut, QSizePolicy)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QUrl, QTimer
from PyQt5.QtGui import QCursor, QIntValidator, QKeySequence, QPixmap
from PyQt5.QtMultimedia import QMediaContent

# 动态导入核心依赖，如果失败则优雅地处理
# 这允许模块在某些功能受限的情况下仍然可以加载
try:
    import numpy as np
    import soundfile as sf
    import librosa
    DEPENDENCIES_MISSING = False
except ImportError:
    DEPENDENCIES_MISSING = True
# ==============================================================================
# [新增] 高级图片保存对话框 (AdvancedImageSaveDialog)
# ==============================================================================
class AdvancedImageSaveDialog(QDialog):
    """一个让用户选择导出图片分辨率和样式的对话框。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量保存图片选项")
        layout = QFormLayout(self)

        # --- 分辨率部分 ---
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
        
        layout.addRow("分辨率预设:", self.presets_combo)
        layout.addRow("自定义大小:", custom_layout)
        
        # --- 样式选项 ---
        options_group = QGroupBox("样式与信息")
        options_layout = QVBoxLayout(options_group)
        self.info_label_check = QCheckBox("在图片上添加信息标签 (文件名, 时长等)")
        self.info_label_check.setChecked(True)
        self.time_axis_check = QCheckBox("在图片底部添加时间轴")
        self.time_axis_check.setChecked(True)
        options_layout.addWidget(self.info_label_check)
        options_layout.addWidget(self.time_axis_check)
        layout.addWidget(options_group)

        # --- 按钮 ---
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.on_preset_changed(self.presets_combo.currentText())

    def on_preset_changed(self, text):
        resolution = self.presets.get(text)
        is_custom = (resolution is None)
        self.width_input.setEnabled(is_custom)
        self.height_input.setEnabled(is_custom)
        if not is_custom:
            self.width_input.setText(str(resolution[0]))
            self.height_input.setText(str(resolution[1]))

    def get_options(self):
        resolution = None
        try:
            resolution = (int(self.width_input.text()), int(self.height_input.text()))
        except ValueError:
            resolution = (1920, 1080) # 安全回退

        return {
            "resolution": resolution,
            "info_label": self.info_label_check.isChecked(),
            "add_time_axis": self.time_axis_check.isChecked()
        }

# ==============================================================================
# [新增] 高级CSV保存对话框 (AdvancedCsvSaveDialog)
# ==============================================================================
class AdvancedCsvSaveDialog(QDialog):
    """一个让用户选择CSV保存模式的对话框。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量保存CSV选项")
        layout = QVBoxLayout(self)

        group = QGroupBox("保存模式")
        group_layout = QVBoxLayout(group)
        
        self.separate_files_radio = QRadioButton("为每个音频单独保存为一个 .csv 文件 (推荐)")
        self.separate_files_radio.setToolTip("将为每个音频文件（如 audio1.wav）创建一个对应的分析文件（如 audio1_analysis.csv）。")
        self.separate_files_radio.setChecked(True)
        
        self.merge_file_radio = QRadioButton("将所有结果合并到一个 .csv 文件中")
        self.merge_file_radio.setToolTip("所有音频的分析数据将合并到一个CSV文件中，并增加一列'source_file'来区分来源。")
        
        group_layout.addWidget(self.separate_files_radio)
        group_layout.addWidget(self.merge_file_radio)
        
        layout.addWidget(group)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_options(self):
        return {
            "merge": self.merge_file_radio.isChecked()
        }
# ==============================================================================
# [新增] 后台批量加载工作器 (BatchLoadWorker)
# ==============================================================================
class BatchLoadWorker(QObject):
    """一个专门用于在后台线程加载单个音频文件的简单工作器。"""
    # 信号定义：成功时发送包含 y, sr, filepath 的字典，失败时发送错误字符串
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        """工作器的入口点，执行加载操作。"""
        try:
            y, sr = librosa.load(self.filepath, sr=None, mono=True)
            self.finished.emit({"y": y, "sr": sr, "filepath": self.filepath})
        except Exception as e:
            self.error.emit(str(e))
# ==============================================================================
# 后台批量分析工作器 (BatchAnalysisWorker)
# ==============================================================================
class BatchAnalysisWorker(QObject):
    """
    在独立线程中执行耗时的批量音频分析任务。
    设计核心是内存效率：逐个加载、分析并释放每个音频文件，以处理大量数据。
    [v2.1] 版本引入了分块分析机制，以支持平滑的进度条更新。
    """
    # --- 信号定义 ---
    finished = pyqtSignal(dict, dict)           # 所有任务完成时发送，携带完整的分析结果缓存
    progress = pyqtSignal(int, int, str)  # (当前文件索引, 文件总数, 文件名)，用于更新进度条标签
    error = pyqtSignal(str)               # 发生错误时发送
    # [新增] 用于报告单个文件内部进度的信号 (当前块的结束时间秒数, 文件总时长秒数)
    chunk_progress = pyqtSignal(float, float)
    single_file_completed = pyqtSignal(str, bool, str)

    def __init__(self, filepaths, analysis_params):
        """
        构造函数。
        :param filepaths: 要分析的音频文件路径列表。
        :param analysis_params: 一个包含所有分析参数的字典，从主UI获取。
        """
        super().__init__()
        self.filepaths = filepaths
        self.params = analysis_params
        self.analysis_cache = {}  # 用于存储分析结果的字典
        self.failed_files = {} # 改为字典 {filepath: error_string}

    def run(self):
        """
        [v2.2 - 容错版] 工作器的入口点。
        此版本将错误处理移入循环内部，允许在处理单个文件失败时继续运行，
        并最终报告所有成功和失败的文件。
        """
        total_files = len(self.filepaths)
        for i, filepath in enumerate(self.filepaths):
            try:
                # --- 1. 检查中断请求 ---
                # 响应用户在UI上点击“取消”按钮
                if QThread.currentThread().isInterruptionRequested():
                    # 用户取消不是一个程序错误，直接返回即可。
                    # finished 信号不会被发射，UI会保持在取消状态。
                    return

                # --- 2. 报告文件级进度 ---
                # 发送信号以更新进度对话框的标签文本
                self.progress.emit(i, total_files, os.path.basename(filepath))

                # --- 3. [核心] 单文件处理逻辑 ---
                # a. 加载音频 (这是最容易出错的步骤之一)
                y, sr = librosa.load(filepath, sr=None, mono=True)
                
                # b. 调用辅助函数执行所有分析计算
                results_for_file = self._analyze_file_logic(y, sr)
                
                # c. 将成功的结果存入缓存
                self.analysis_cache[filepath] = results_for_file
                
                # d. 立即释放大数组内存，为下一个文件做准备
                del y, sr, results_for_file
                self.single_file_completed.emit(filepath, True, "")

            except Exception as e:
                # --- 4. [核心] 错误隔离与记录 ---
                # 如果在处理单个文件的任何步骤中发生异常：
                import traceback
                error_str = str(e)
                traceback.print_exc() # 在控制台打印详细错误，方便开发者调试
                print(f"ERROR: Failed to process file '{filepath}': {error_str}")
                
                # a. 记录失败的文件路径和具体的错误信息
                self.failed_files[filepath] = error_str
                self.single_file_completed.emit(filepath, False, error_str)
                # b. 使用 continue 关键字，跳过当前循环的剩余部分，直接开始处理下一个文件
                continue
        
        # --- 5. 任务最终完成 ---
        # 当 for 循环正常结束（所有文件都被尝试处理过）后，
        # 发射 finished 信号，同时传递包含成功结果的缓存和包含失败信息的字典。
        self.finished.emit(self.analysis_cache, self.failed_files)

    def _analyze_file_logic(self, y, sr):
        """
        [v2.3 - 移植修复版] 封装了对单个已加载音频(y, sr)的所有分析计算。
        此版本将单文件工作器中经过验证的、更健壮的兼容模式逻辑移植了过来，
        并保留了普通模式下的优化，同时对两种模式都增加了对极短音频的保护。
        """
        results_for_file = {}
        analysis_mode = self.params.get('analysis_mode', 'normal')

        # --- [核心保护] 对极短音频的保护性检查，对两种模式都生效 ---
        # pyin 算法需要至少约4096个采样点才能稳定工作
        MIN_SAMPLES_FOR_PYIN = 4096
        if len(y) < MIN_SAMPLES_FOR_PYIN:
            raise ValueError(f"音频过短 ({len(y)}采样点)，无法进行可靠的F0分析。至少需要{MIN_SAMPLES_FOR_PYIN}个采样点。")
        
        # 步骤 1: F0 & Intensity 分析 (根据模式选择)
        if self.params.get('analyze_f0_intensity'):
            if analysis_mode == 'compatibility':
                # --- [核心移植] 使用与 AudioTaskWorker 完全相同的兼容模式逻辑 ---
                y_analyzed = librosa.effects.preemphasis(y) if self.params['pre_emphasis'] else y
                
                f0_min = self.params.get('f0_min', 75)
                f0_max = self.params.get('f0_max', 500)

                f0_raw, voiced_flags, _ = librosa.pyin(y_analyzed, fmin=f0_min, fmax=f0_max, sr=sr)
                intensity = librosa.feature.rms(y=y)[0]
                
                # F0后处理
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
                
                # 准备时间轴并对齐数据
                times = librosa.times_like(f0_raw, sr=sr)
                if len(intensity) > len(times): intensity = intensity[:len(times)]
                elif len(intensity) < len(times): intensity = np.pad(intensity, (0, len(times) - len(intensity)), 'constant', constant_values=0)

                results_for_file['f0_data'] = (times, f0_raw)
                results_for_file['f0_derived_data'] = (times, f0_postprocessed)
                results_for_file['intensity_data'] = intensity
                
                try:
                    hop_length = librosa.time_to_samples(times[1] - times[0], sr=sr) if len(times) > 1 else 512
                except:
                    hop_length = 512
                results_for_file['hop_length'] = hop_length
                
                # 在兼容模式下，进度条直接跳到当前文件完成
                self.chunk_progress.emit(len(y)/sr, len(y)/sr)

            else: # --- 普通模式逻辑 (保留F0范围预分析优化) ---
                y_analyzed = librosa.effects.preemphasis(y) if self.params['pre_emphasis'] else y
                
                user_f0_min = self.params.get('f0_min', 75)
                user_f0_max = self.params.get('f0_max', 500)
                final_f0_min, final_f0_max = user_f0_min, user_f0_max
                
                # 对预分析步骤进行保护
                try:
                    y_coarse = librosa.resample(y, orig_sr=sr, target_sr=8000)
                    if len(y_coarse) > 2048: # 仅当重采样后仍然足够长时才进行预分析
                        f0_coarse, _, _ = librosa.pyin(
                            y_coarse, fmin=30, fmax=1200, sr=8000,
                            frame_length=1024, hop_length=512
                        )
                        valid_f0_coarse = f0_coarse[np.isfinite(f0_coarse)]
                        if len(valid_f0_coarse) > 10:
                            p5, p95 = np.percentile(valid_f0_coarse, [5, 95])
                            padding = (p95 - p5) * 0.15
                            final_f0_min = max(user_f0_min, p5 - padding)
                            final_f0_max = min(user_f0_max, p95 + padding)
                except Exception:
                    pass # 预分析失败是可接受的，将使用用户设定的范围

                narrow_band_window_s = 0.035
                base_n_fft_for_hop = 1 << (int(sr * narrow_band_window_s) - 1).bit_length()
                render_overlap_ratio = 1 - (1 / (2**self.params['render_density']))
                hop_length = int(base_n_fft_for_hop * (1 - render_overlap_ratio)) or 1
                frame_length = 1 << (int(sr * 0.040) - 1).bit_length()

                # ... (此处是普通模式的分块分析逻辑，无需修改) ...
                chunk_size_ms = 200
                chunk_overlap_ms = 10
                chunk_size_samples = int((chunk_size_ms / 1000) * sr)
                overlap_samples = int((chunk_overlap_ms / 1000) * sr)
                step_size_samples = chunk_size_samples - overlap_samples
                if step_size_samples <= 0: step_size_samples = hop_length
                all_f0_raw, all_f0_derived, all_intensity, all_times = [], [], [], []
                current_pos_samples = 0
                total_duration_s = len(y) / sr
                while current_pos_samples < len(y):
                    if QThread.currentThread().isInterruptionRequested():
                        raise InterruptedError("用户取消了操作")
                    start_sample = current_pos_samples
                    end_sample = start_sample + chunk_size_samples
                    y_chunk, y_chunk_analyzed = y[start_sample:end_sample], y_analyzed[start_sample:end_sample]
                    if len(y_chunk) == 0: break
                    f0_raw_chunk, voiced_flags, _ = librosa.pyin(
                        y_chunk_analyzed, fmin=final_f0_min, fmax=final_f0_max, sr=sr,
                        frame_length=frame_length, hop_length=hop_length
                    )
                    f0_postprocessed_chunk = np.full_like(f0_raw_chunk, np.nan)
                    if len(f0_raw_chunk) > 0:
                        voiced_ints = voiced_flags.astype(int)
                        if len(voiced_ints) > 0:
                            starts, ends = np.where(np.diff(voiced_ints) == 1)[0] + 1, np.where(np.diff(voiced_ints) == -1)[0] + 1
                            if voiced_ints[0] == 1: starts = np.insert(starts, 0, 0)
                            if voiced_ints[-1] == 1: ends = np.append(ends, len(voiced_ints))
                            for start_idx, end_idx in zip(starts, ends):
                                if end_idx - start_idx > 2:
                                    segment = f0_raw_chunk[start_idx:end_idx]; segment_series = pd.Series(segment)
                                    interpolated_segment = segment_series.interpolate(method='linear', limit_direction='both', limit=2).to_numpy()
                                    f0_postprocessed_chunk[start_idx:end_idx] = interpolated_segment
                    intensity_chunk = librosa.feature.rms(y=y_chunk, frame_length=frame_length, hop_length=hop_length)[0]
                    num_frames_in_step = round(step_size_samples / hop_length)
                    times_in_chunk = librosa.times_like(f0_raw_chunk, sr=sr, hop_length=hop_length)
                    global_times = times_in_chunk + (start_sample / sr)
                    all_times.append(global_times[:num_frames_in_step])
                    all_f0_raw.append(f0_raw_chunk[:num_frames_in_step])
                    all_f0_derived.append(f0_postprocessed_chunk[:num_frames_in_step])
                    all_intensity.append(intensity_chunk[:num_frames_in_step])
                    last_time_in_chunk = global_times[-1] if len(global_times) > 0 else (end_sample / sr)
                    self.chunk_progress.emit(last_time_in_chunk, total_duration_s)
                    current_pos_samples += step_size_samples
                results_for_file['f0_data'] = (np.concatenate(all_times), np.concatenate(all_f0_raw))
                results_for_file['f0_derived_data'] = (np.concatenate(all_times), np.concatenate(all_f0_derived))
                results_for_file['intensity_data'] = np.concatenate(all_intensity)
                results_for_file['hop_length'] = hop_length

        # 步骤 2. 语谱图和共振峰分析 (此部分逻辑无需修改，保持原样)
        y_analyzed_spec = librosa.effects.preemphasis(y) if self.params['pre_emphasis'] else y
        
        narrow_band_window_s = 0.035
        base_n_fft_for_hop = 1 << (int(sr * narrow_band_window_s) - 1).bit_length()
        
        render_hop_length = results_for_file.get('hop_length')
        if render_hop_length is None:
            render_overlap_ratio = 1 - (1 / (2**self.params['render_density']))
            render_hop_length = int(base_n_fft_for_hop * (1 - render_overlap_ratio)) or 1
            results_for_file['hop_length'] = render_hop_length
        
        spectrogram_window_s = 0.005 if self.params['is_wide_band'] else 0.035
        n_fft_spectrogram = 1 << (int(sr * spectrogram_window_s) - 1).bit_length()
        D = librosa.stft(y_analyzed_spec, hop_length=render_hop_length, n_fft=n_fft_spectrogram)
        S_db = librosa.amplitude_to_db(np.abs(D), ref=np.max)
        results_for_file['S_db'] = S_db

        if self.params.get('analyze_formants'):
            overlap_ratio_formant = 1 - (1 / (2**self.params['formant_density']))
            hop_length_formant = int(base_n_fft_for_hop * (1 - overlap_ratio_formant)) or 1
            formant_points = self._analyze_formants_helper(y, sr, hop_length_formant)
            results_for_file['formants_data'] = formant_points
            
        results_for_file['sr'] = sr
        results_for_file['duration_ms'] = (len(y) / sr) * 1000

        return results_for_file

    def _analyze_formants_helper(self, y_data, sr, hop_length, start_offset=0, pre_emphasis=None):
        """
        改进版（用于 BatchAnalysisWorker）：窗口化 + 去均值 + LPC 阶数约束 +
        计算极点频率与带宽，并在每个 formant band 中选择带宽最小的候选。
        :param pre_emphasis: 若传入 None，则从 self.params 中读取 (默认启用或禁用由 ui 决定)。
        :return: list of (sample_center, [F1, F2, ...])
        """
        # 决定是否做预加重（优先使用显式参数，否则从 worker 的 params 读）
        if pre_emphasis is None:
            pre_emphasis = bool(self.params.get('pre_emphasis', True))

        # 预加重（如果启用）
        y_proc = librosa.effects.preemphasis(y_data) if pre_emphasis else y_data

        # 帧设置：25 ms 常用值（Praat 常用窗长 20-25ms）
        frame_length = int(sr * 0.025)
        if frame_length < 16:
            frame_length = max(16, len(y_proc))

        # LPC 阶数：基于采样率的启发式值，但做上下界约束，且不能超过 frame_length-2
        order = int(2 + sr // 1000)
        order = max(6, min(order, max(6, frame_length - 2)))

        formant_points = []

        # 能量判定，过滤静音帧
        rms = librosa.feature.rms(y=y_data, frame_length=frame_length, hop_length=hop_length)[0]
        energy_threshold = np.max(rms) * 0.05 if np.max(rms) > 0 else 0
        frame_index = 0

        nyq = sr / 2.0
        # formant bands（上限受 Nyquist 限制）
        formant_ranges = [
            (250, min(800, nyq)),
            (800, min(2200, nyq)),
            (2200, min(3000, nyq)),
            (3000, min(4000, nyq)),
        ]

        for i in range(0, len(y_proc) - frame_length, hop_length):
            # 能量阈值过滤
            if frame_index < len(rms) and rms[frame_index] < energy_threshold:
                frame_index += 1
                continue

            y_frame = y_proc[i: i + frame_length]
            if len(y_frame) < frame_length:
                frame_index += 1
                continue

            # 去均值 + 窗函数
            y_frame = y_frame - np.mean(y_frame)
            win = np.hamming(len(y_frame))
            y_frame = y_frame * win

            # 跳过低能量或数值异常帧
            if np.max(np.abs(y_frame)) < 1e-6 or not np.isfinite(y_frame).all():
                frame_index += 1
                continue

            try:
                if len(y_frame) <= order:
                    frame_index += 1
                    continue

                a = librosa.lpc(y_frame, order=order)
                if not np.isfinite(a).all():
                    frame_index += 1
                    continue

                roots_all = np.roots(a)
                # 只保留上半平面的极点并剔除幅度异常的极点
                roots = [r for r in roots_all if np.imag(r) >= 0 and 0.001 < np.abs(r) < 0.9999]

                candidates = []
                for r in roots:
                    ang = np.angle(r)
                    freq = ang * (sr / (2 * np.pi))
                    if freq <= 0 or freq >= nyq:
                        continue
                    # 带宽映射：bw = - (sr / pi) * ln(|r|)
                    bw = - (sr / np.pi) * np.log(np.abs(r))
                    # 丢弃过宽或负值带宽（噪声）
                    if bw <= 0 or bw > 1000:
                        continue
                    candidates.append((freq, bw))

                # 以频率排序，便于在bands中选择
                candidates.sort(key=lambda x: x[0])

                found_formants = []
                # 对每个预设 band，选择带宽最小的候选（更尖锐、可靠）
                for f_min, f_max in formant_ranges:
                    band_cands = [(f, bw) for (f, bw) in candidates if f_min <= f <= f_max]
                    if not band_cands:
                        continue
                    best = min(band_cands, key=lambda x: x[1])
                    found_formants.append(best[0])

                if found_formants:
                    sample_center = start_offset + i + frame_length // 2
                    formant_points.append((sample_center, found_formants))

            except Exception:
                # 数值问题就忽略该帧
                frame_index += 1
                continue

            frame_index += 1

        return formant_points



# ==============================================================================
# 批量保存选项对话框 (BatchSaveDialog)
# ==============================================================================
class BatchSaveDialog(QDialog):
    """一个让用户选择要批量保存哪些分析结果的对话框。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量保存选项")
        layout = QFormLayout(self)
        self.save_csv_check = QCheckBox("保存分析数据为 .csv 文件")
        self.save_csv_check.setChecked(True)
        self.save_image_check = QCheckBox("保存视图为 .png 图片")
        self.save_image_check.setChecked(True)
        layout.addRow(self.save_csv_check)
        layout.addRow(self.save_image_check)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_options(self):
        return {
            "save_csv": self.save_csv_check.isChecked(),
            "save_image": self.save_image_check.isChecked()
        }


# ==============================================================================
# 批量处理面板主类 (AudioAnalysisBatchPanel)
# ==============================================================================
class AudioAnalysisBatchPanel(QWidget):
    """
    音频分析模块的“批量分析”标签页的UI和逻辑控制器。
    负责管理文件列表、触发批量分析、缓存结果以及与主模块的中心显示区域进行交互。
    """
    def __init__(self, main_page, parent=None):
        """
        构造函数。
        :param main_page: 对主 AudioAnalysisPage 实例的引用，用于访问共享的UI和方法。
        """
        super().__init__(parent)
        self.main_page = main_page
        self.icon_manager = main_page.icon_manager

        # --- 数据与状态管理 ---
        self.file_list = []  # 存储 (filepath, status) 元组的列表
        self.analysis_cache = {} # 格式: {filepath: {analysis_data_dict}}
        self.current_audio_data = None # 当前选中文件的 (y, sr) 数据，用于播放
        self.batch_thread = None
        self.batch_worker = None
        # [修改] 移除 single_load_... 属性，替换为更通用的 load_...
        self.load_thread = None
        self.load_worker = None
        self.single_analysis_thread = None
        self.single_analysis_worker = None
        # [新增] 状态变量，用于计算平滑的进度
        self.current_file_index = 0
        self.total_files = 0
        # [新增] 创建一个用于延迟加载的QTimer
        self.selection_timer = QTimer(self)
        self.selection_timer.setSingleShot(True) # 确保它只触发一次
        self.selection_timer.setInterval(200) # 设置延迟时间为 200 毫秒
        
        self._init_ui()
        self.setAcceptDrops(True)
        self.file_table.setFocusPolicy(Qt.StrongFocus)
        self._connect_signals()

    def _init_ui(self):
        """
        [v2.1 - UI微调版]
        构建此面板的用户界面。
        此版本将“全部分析”按钮移至底部，并与“保存”按钮一起拉伸以占据全部宽度，
        形成清晰的“内容区”和“操作区”分离，提升了视觉层次感和操作便捷性。
        """
        # 1. 创建主垂直布局，它将整个面板分为上下两个部分
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 5, 0, 5) # 上下保留一点边距
        main_layout.setSpacing(10) # 增加内容区和操作区之间的垂直间距

        # --- 2. 创建内容区 ---
        # 内容区包含“导入文件”按钮和文件列表表格
        content_layout = QVBoxLayout()
        content_layout.setSpacing(5) # 按钮和表格之间的间距
        
        # 2.1. “导入文件”按钮
        self.import_btn = QPushButton(" 导入文件")
        self.import_btn.setIcon(self.icon_manager.get_icon("add_row"))
        self.import_btn.setToolTip("从您的计算机选择一个或多个音频文件添加到此列表中。")
        
        # 2.2. 文件列表表格
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(2)
        self.file_table.setHorizontalHeaderLabels(["文件名", "状态"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_table.setToolTip("文件列表。\n- 单击/多选: 查看文件波形\n- 回车: 播放选中项\n- 右键: 更多操作")

        # 将导入按钮和文件列表添加到内容区布局
        content_layout.addWidget(self.import_btn)
        content_layout.addWidget(self.file_table)

        # --- 3. 创建底部操作区 ---
        # 操作区包含所有主要的操作按钮
        bottom_actions_layout = QVBoxLayout()
        bottom_actions_layout.setSpacing(5) # 按钮之间的垂直间距

        # 3.1. “全部分析”按钮
        self.run_all_btn = QPushButton(" 全部分析")
        self.run_all_btn.setIcon(self.icon_manager.get_icon("analyze"))
        self.run_all_btn.setEnabled(False)
        self.run_all_btn.setToolTip("对列表中所有“待处理”的文件执行完整的声学分析。")
        # [核心] 设置尺寸策略，使其可以在水平方向上无限伸展，垂直方向固定
        self.run_all_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 3.2. “保存全部结果”按钮
        self.save_all_btn = QPushButton(" 保存全部结果...")
        self.save_all_btn.setIcon(self.icon_manager.get_icon("save_all"))
        self.save_all_btn.setEnabled(False)
        self.save_all_btn.setToolTip("将所有已分析文件的结果批量保存为图片或CSV。")
        # [核心] 同样设置尺寸策略，确保两个按钮宽度一致
        self.save_all_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 将操作按钮添加到操作区布局
        bottom_actions_layout.addWidget(self.run_all_btn)
        bottom_actions_layout.addWidget(self.save_all_btn)

        # --- 4. 组装主布局 ---
        # 将内容区和操作区添加到主布局中
        # 参数 1 表示内容区将占据所有可用的垂直伸缩空间
        main_layout.addLayout(content_layout, 1) 
        main_layout.addLayout(bottom_actions_layout)

    def _connect_signals(self):
        """连接所有UI控件的信号到相应的槽函数。"""
        self.import_btn.clicked.connect(self.import_files)
        # [核心修改] itemSelectionChanged 现在只负责启动或重置计时器
        self.file_table.itemSelectionChanged.connect(self._on_selection_changed_debounced)
    
        # [新增] 计时器超时后，才执行真正的加载逻辑
        self.selection_timer.timeout.connect(self._perform_delayed_load)
        self.file_table.customContextMenuRequested.connect(self._open_context_menu)
        self.run_all_btn.clicked.connect(self.run_all_analysis)
        self.save_all_btn.clicked.connect(self.save_all_results)
        # [新增] 添加回车键快捷方式
        self.play_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self.file_table)
        self.play_shortcut_enter = QShortcut(QKeySequence(Qt.Key_Enter), self.file_table)
    
        self.play_shortcut.activated.connect(self._play_selected_from_shortcut)
        self.play_shortcut_enter.activated.connect(self._play_selected_from_shortcut)

    def dragEnterEvent(self, event):
        """
        [新增] 当鼠标拖着内容进入此面板时触发。
        """
        mime_data = event.mimeData()
        # 1. 检查拖入的内容是否是文件路径 (URLs)
        if mime_data.hasUrls():
            # 2. 检查至少有一个文件的扩展名是我们支持的音频格式
            supported_exts = ('.wav', '.mp3', '.flac', '.ogg', '.m4a')
            if any(url.toLocalFile().lower().endswith(supported_exts) for url in mime_data.urls()):
                # 3. 如果是，则接受拖拽事件，鼠标光标会变为“+”号
                event.acceptProposedAction()

    def dragMoveEvent(self, event):
        """
        [新增] 当鼠标在面板内移动时触发。
        我们简单地接受事件，以保持光标样式不变。
        """
        event.acceptProposedAction()

    def dropEvent(self, event):
        """
        [新增] 当用户在面板上释放文件时触发。
        """
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            # 1. 提取所有被拖入文件的本地路径
            supported_exts = ('.wav', '.mp3', '.flac', '.ogg', '.m4a')
            filepaths = [
                url.toLocalFile() for url in mime_data.urls()
                if url.isLocalFile() and url.toLocalFile().lower().endswith(supported_exts)
            ]

            # 2. 如果成功提取到了有效的音频文件路径
            if filepaths:
                # 3. [核心] 调用我们现有的逻辑来添加文件
                self._add_files_to_list(filepaths)
                # 阻止事件进一步传播
                event.acceptProposedAction()

    def _on_selection_changed_debounced(self):
        """
        这是一个“去抖动”的槽函数。
        当选择变化时，它不直接加载文件，而是启动（或重置）一个短暂的计时器。
        """
        self.selection_timer.start()

    def _perform_delayed_load(self):
        """
        [v2.1 - 优化版]
        根据文件是否已有分析缓存，决定是执行快速的“缓存优先”显示，
        还是执行完整的异步加载。
        """
        selected_rows = self.file_table.selectionModel().selectedRows()
    
        if not selected_rows:
            self.main_page.clear_all_central_widgets()
            return
    
        current_row = selected_rows[-1].row()
        filepath = self.file_table.item(current_row, 0).data(Qt.UserRole)
    
        # --- 核心优化逻辑 ---
        # 检查点击的文件是否已有分析缓存
        if filepath in self.analysis_cache:
            # 如果有，走新的、快速的“缓存优先”路径
            self._display_from_cache_and_load_audio_async(filepath)
        else:
            # 如果没有，走原来的、完整的加载路径
            self._display_file_async(filepath)

    def _display_from_cache_and_load_audio_async(self, filepath):
        """
        [新增] 优化核心：立即显示缓存数据，并异步加载音频。
        """
        # 1. 立即清理并显示缓存的分析结果
        self.main_page.clear_all_central_widgets()
        self.main_page.current_filepath = filepath
        
        cached_data = self.analysis_cache[filepath]

        # --- 立即渲染语谱图和叠加层 ---
        if 'S_db' in cached_data and 'hop_length' in cached_data:
            # 注意：这里需要一个临时的sr值，我们可以从上次分析中缓存它
            # (这需要在BatchAnalysisWorker中添加sr到缓存结果里)
            # 假设我们已经在缓存中保存了sr
            sr = cached_data.get('sr', 44100) # 从缓存获取sr，或使用一个回退值
            self.main_page.spectrogram_widget.set_data(
                cached_data['S_db'], sr, cached_data['hop_length']
            )
        self.main_page.spectrogram_widget.set_analysis_data(
            f0_data=cached_data.get('f0_data'),
            f0_derived_data=cached_data.get('f0_derived_data'),
            intensity_data=cached_data.get('intensity_data'),
            formants_data=cached_data.get('formants_data'),
            clear_previous_formants=True
        )

        # 在波形图区域显示“加载中...”的提示
        self.main_page.waveform_widget.clear() # 清空旧波形
        # (可以进一步优化，让WaveformWidget能显示一个加载文本)
        
        # 禁用播放按钮，直到音频加载完成
        self.main_page.play_pause_btn.setEnabled(False)

        # 2. 启动一个非阻塞的后台线程来加载音频
        self.load_thread = QThread()
        self.load_worker = BatchLoadWorker(filepath) # 复用现有的加载器
        self.load_worker.moveToThread(self.load_thread)

        self.load_worker.finished.connect(self._on_background_audio_loaded)
        # 可以选择性地处理错误
        self.load_worker.error.connect(lambda err: print(f"Background audio load failed: {err}"))
        self.load_thread.started.connect(self.load_worker.run)
        
        # 线程结束后自动清理
        def cleanup():
            if self.load_worker: self.load_worker.deleteLater()
            if self.load_thread: self.load_thread.deleteLater()
        self.load_thread.finished.connect(cleanup)
        
        self.load_thread.start()

    def _on_background_audio_loaded(self, result):
        """
        [新增] 当后台音频加载完成后，填充剩余的UI部分。
        """
        y, sr, filepath = result['y'], result['sr'], result['filepath']

        # --- 安全检查 ---
        # 检查加载完成的音频是否仍然是当前选中的项，防止用户快速切换导致错乱
        current_row = self.file_table.currentRow()
        if current_row == -1 or self.file_table.item(current_row, 0).data(Qt.UserRole) != filepath:
            self.load_thread.quit()
            return

        # 3. 填充波形图和播放器
        self.main_page.audio_data = y
        self.main_page.sr = sr
        # 为了简化，我们直接用完整数据作为概览数据
        self.main_page.waveform_widget.set_audio_data(y, sr, y)
        self.main_page.player.setMedia(QMediaContent(QUrl.fromLocalFile(filepath)))
        self.main_page.play_pause_btn.setEnabled(True)
        self.current_audio_data = (y, sr)
        
        self.load_thread.quit()

    def _display_file_async(self, filepath):
        """
        [v2.3 - 核心加载逻辑]
        异步加载并显示单个文件，期间显示一个“加载中”的进度条。
        """
        # 1. 显示加载进度条
        progress_dialog = QProgressDialog(f"正在加载音频: {os.path.basename(filepath)}...", "取消", 0, 0, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setStyleSheet(self.main_page.parent_window.styleSheet())
        progress_dialog.setWindowIcon(self.main_page.parent_window.windowIcon())
        progress_dialog.show()
    
        # 2. 创建专用的加载线程和工作器
        self.load_thread = QThread()
        self.load_worker = BatchLoadWorker(filepath)
        self.load_worker.moveToThread(self.load_thread)

        # 3. 定义完成和错误处理逻辑
        def on_load_finished(result):
            progress_dialog.close()
        
            # 检查加载的文件是否仍然是当前选中的文件
            current_row_now = self.file_table.currentRow()
            if current_row_now == -1 or self.file_table.item(current_row_now, 0).data(Qt.UserRole) != result['filepath']:
                self.load_thread.quit()
                return

            # 调用同步方法更新UI
            self._display_file_sync(result['y'], result['sr'], result['filepath'])
            self.load_thread.quit()

        def on_load_error(err_msg):
            progress_dialog.close()
            QMessageBox.critical(self, "加载失败", f"加载文件 {os.path.basename(filepath)} 时出错:\n{err_msg}")
            self.load_thread.quit()

        # 4. 连接信号并启动
        self.load_worker.finished.connect(on_load_finished)
        self.load_worker.error.connect(on_load_error)
    
        def cleanup():
            if self.load_worker:
                self.load_worker.deleteLater()
                self.load_worker = None
            if self.load_thread:
                self.load_thread.deleteLater()
                self.load_thread = None

        self.load_thread.started.connect(self.load_worker.run)
        self.load_thread.finished.connect(cleanup)
    
        progress_dialog.canceled.connect(self.load_thread.requestInterruption)
        progress_dialog.canceled.connect(self.load_thread.quit)

        self.load_thread.start()

    def _display_file_sync(self, y, sr, filepath):
        """
        [v2.3 - 核心UI更新逻辑]
        使用已加载的音频数据(y, sr)来同步更新中心视图。
        此方法不执行任何耗时操作，只负责UI渲染。
        """
        try:
            self.current_audio_data = (y, sr)
        
            # 1. 更新主页面的核心UI组件
            self.main_page.clear_all_central_widgets() # 清理旧的显示
        
            # 填充新数据
            self.main_page.audio_data = y
            self.main_page.sr = sr
            self.main_page.current_filepath = filepath
            # 概览波形图，为简化直接使用完整数据
            self.main_page.waveform_widget.set_audio_data(y, sr, y)
            # 准备播放器
            self.main_page.player.setMedia(QMediaContent(QUrl.fromLocalFile(filepath)))
            self.main_page.play_pause_btn.setEnabled(True)

            # 2. 从缓存加载并显示分析结果（如果存在）
            if filepath in self.analysis_cache:
                cached_data = self.analysis_cache[filepath]
                # 显示语谱图
                if 'S_db' in cached_data and 'hop_length' in cached_data:
                    self.main_page.spectrogram_widget.set_data(
                        cached_data['S_db'], sr, cached_data['hop_length']
                    )
                # 显示叠加层（F0, 强度, 共振峰）
                self.main_page.spectrogram_widget.set_analysis_data(
                    f0_data=cached_data.get('f0_data'),
                    f0_derived_data=cached_data.get('f0_derived_data'),
                    intensity_data=cached_data.get('intensity_data'),
                    formants_data=cached_data.get('formants_data'),
                    clear_previous_formants=True
                )
        except Exception as e:
            QMessageBox.critical(self, "显示错误", f"更新UI时出错:\n{e}")

    def _play_selected_from_shortcut(self):
        """响应回车快捷键，播放当前在表格中选中的项。"""
        # 确保表格有焦点，避免在其他地方按回车也触发播放
        if self.file_table.hasFocus():
            current_row = self.file_table.currentRow()
            if current_row != -1:
                # 调用主模块的播放按钮点击事件，这样可以复用所有播放逻辑
                # 包括即将实现的“选区优先播放”逻辑
                self.main_page.toggle_playback()
    
    def on_panel_selected(self):
        """当用户切换到此面板时，由主页面调用。"""
        # 这个方法可以用于在面板可见时执行一些刷新或初始化操作。
        pass
        

    def import_files(self):
        """
        [重构] 打开文件对话框以导入多个音频文件。
        现在它只负责获取文件路径，然后将路径传递给核心处理函数。
        """
        filepaths, _ = QFileDialog.getOpenFileNames(
            self, "选择要批量分析的音频文件", "", 
            "音频文件 (*.wav *.mp3 *.flac *.ogg *.m4a)"
        )
        if filepaths:
            self._add_files_to_list(filepaths)

    def _add_files_to_list(self, filepaths):
        """
        [新增] 核心辅助函数，负责将一个文件路径列表添加到UI和数据模型中。
        可被“导入按钮”和“拖拽事件”共同调用。
        """
        added_count = 0
        for fp in filepaths:
            # 检查文件是否已在列表中，防止重复添加
            if not any(f[0] == fp for f in self.file_list):
                self.file_list.append((fp, "待处理"))
                added_count += 1
    
        # 只有在确实添加了新文件时，才更新UI和状态
        if added_count > 0:
            self._update_table()
            self.run_all_btn.setEnabled(True)
            # 可以在状态栏给出反馈
            self.main_page.parent_window.statusBar().showMessage(f"已成功添加 {added_count} 个新文件。", 3000)

    def _update_table(self):
        """
        [v2.3 - 持久化Widget版]
        根据 self.file_list 的内容刷新UI表格。
        此版本在创建行时，就为状态单元格设置一个持久的QWidget和QLabel，
        后续的更新只修改QLabel的内容，不再替换整个widget。
        """
        self.file_table.blockSignals(True)
        self.file_table.setRowCount(0)
        self.file_table.setRowCount(len(self.file_list))

        for i, (filepath, status) in enumerate(self.file_list):
            # --- 文件名列 (保持不变) ---
            name_item = QTableWidgetItem(os.path.basename(filepath))
            name_item.setData(Qt.UserRole, filepath)
            self.file_table.setItem(i, 0, name_item)
        
            # --- [核心修改] 创建并设置持久化的状态单元格 ---
            # 1. 创建容器和居中布局
            cell_widget = QWidget()
            layout = QHBoxLayout(cell_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignCenter)

            # 2. 创建 QLabel 用于显示图标
            icon_label = QLabel()
            layout.addWidget(icon_label)

            # 3. 将这个包含 QLabel 的容器 widget 设置到单元格中
            self.file_table.setCellWidget(i, 1, cell_widget)
        
            # 4. 调用状态更新函数，为这个新创建的 QLabel 设置初始图标和提示
            self._update_table_row_status(i, status)

        self.file_table.blockSignals(False)

    def _start_batch_analysis(self, filepaths_to_process, dialog_title):
        """
        一个通用的辅助方法，用于启动批量分析任务。
        :param filepaths_to_process: 要分析的文件路径列表。
        :param dialog_title: 进度对话框的标题。
        """
        self.run_all_btn.setEnabled(False)
        self.import_btn.setEnabled(False)
        
        if self.batch_thread and self.batch_thread.isRunning():
            QMessageBox.warning(self, "操作繁忙", "另一个批量分析任务正在进行中，请稍后再试。")
            return

        if not filepaths_to_process:
            QMessageBox.information(self, "无需分析", "没有需要分析的文件。")
            return

        # 获取分析模式设置
        module_states = self.main_page.parent_window.config.get("module_states", {}).get("audio_analysis", {})
        analysis_mode = module_states.get("analysis_mode", "normal")

        # 准备传递给工作器的参数字典
        params = {
            'analyze_f0_intensity': True, 
            'analyze_formants': True,
            'pre_emphasis': self.main_page.pre_emphasis_checkbox.isChecked(),
            'f0_min': self.main_page.f0_range_slider.lowerValue(),
            'f0_max': self.main_page.f0_range_slider.upperValue(),
            'render_density': self.main_page.render_density_slider.value(),
            'formant_density': self.main_page.formant_density_slider.value(),
            'is_wide_band': self.main_page.spectrogram_type_checkbox.isChecked(),
            'analysis_mode': analysis_mode,  # 新增：传递分析模式
        }

        # 设置状态变量和进度对话框
        self.file_list_for_run = filepaths_to_process
        self.total_files = len(self.file_list_for_run)
        self.current_file_index = 0

        self.progress_dialog = QProgressDialog(dialog_title, "取消", 0, self.total_files * 100, self)
        self.progress_dialog.setStyleSheet(self.main_page.parent_window.styleSheet())
        self.progress_dialog.setWindowIcon(self.main_page.parent_window.windowIcon())
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.show()

        # 创建并设置线程和工作器
        self.batch_worker = BatchAnalysisWorker(self.file_list_for_run, params)
        self.batch_thread = QThread()
        self.batch_worker.moveToThread(self.batch_thread)

        # 连接信号
        self.batch_worker.progress.connect(self._on_batch_progress)
        self.batch_worker.chunk_progress.connect(self._on_chunk_progress)
        self.batch_worker.single_file_completed.connect(self._on_single_file_completed)
        self.batch_worker.finished.connect(self._on_batch_finished)
        self.batch_worker.error.connect(self._on_batch_error)
        self.progress_dialog.canceled.connect(self.batch_thread.requestInterruption)

        self.batch_thread.started.connect(self.batch_worker.run)
        self.batch_thread.finished.connect(self._cleanup_batch_thread)
    
        # 启动
        self.batch_thread.start()


    def run_all_analysis(self):
        """启动对所有待处理文件的批量分析。"""
        files_to_run = [fp for fp, status in self.file_list if status != "已分析"]
        self._start_batch_analysis(files_to_run, "正在准备批量分析...")

    def _run_analysis_on_selected(self, filepaths):
        """对所有选中的文件启动一个独立的后台分析任务。"""
        dialog_title = f"正在分析 {len(filepaths)} 个选中文件..."
        self._start_batch_analysis(filepaths, dialog_title)

    def _cleanup_batch_thread(self):
        """线程结束后进行安全的清理。"""
        if self.batch_worker:
            self.batch_worker.deleteLater()
            self.batch_worker = None
        if self.batch_thread:
            self.batch_thread.deleteLater()
            self.batch_thread = None

    def _on_batch_progress(self, current, total, filename):
        """
        [v2.2 - 职责分离版]
        当后台工作器开始处理一个新的文件时，此槽函数被调用。
        它的职责是：
        1. 更新进度对话框的标签文本，告诉用户当前正在处理哪个文件。
        2. 更新总进度条的基础值（例如，处理第3个文件时，基础进度为200%）。
        3. 将UI表格中对应行的状态更新为“分析中...”。
        """
        # 更新当前正在处理的文件索引，供 _on_chunk_progress 计算细节进度
        self.current_file_index = current
        
        # 更新进度对话框的标签，格式为 "正在分析: audio.wav (1/5)"
        self.progress_dialog.setLabelText(f"正在分析: {filename} ({current + 1}/{total})")
        
        # 设置进度条的基础值。每个文件占100个单位。
        base_progress = current * 100
        self.progress_dialog.setValue(int(base_progress))
        
        # 找到即将被分析的文件在UI表格中的行，并更新其状态
        # self.file_list_for_run 是在 run_all_analysis 中创建的待处理文件列表
        if current < len(self.file_list_for_run):
            filepath_to_update = self.file_list_for_run[current]
            for i, (fp, status) in enumerate(self.file_list):
                if fp == filepath_to_update:
                    # 更新数据模型
                    self.file_list[i] = (fp, "分析中...")
                    # 调用辅助函数更新UI
                    self._update_table_row_status(i, "分析中...")
                    break

    # [新增] 新的槽函数，用于实时更新单个文件的完成状态
    def _on_single_file_completed(self, filepath, success, error_message):
        """当后台报告单个文件处理完成时，立即更新该行的UI。"""
        # 遍历表格，找到对应文件的那一行
        for i in range(len(self.file_list)):
            fp, _ = self.file_list[i]
            if fp == filepath:
                new_status = "已分析" if success else "失败"
                # 更新数据模型
                self.file_list[i] = (fp, new_status)
                # 更新UI
                self._update_table_row_status(i, new_status, error_message)
                break
    def _update_table_row_status(self, row, status_text, error_message=None):
        """
        [v2.2 - 内容更新版]
        一个只更新特定行状态图标和提示的轻量级函数。
        此版本不再创建或替换widget，而是查找已存在的QLabel并更新其内容。
        """
        # 1. [核心] 通过 cellWidget() 获取我们在 _update_table 中设置的容器 QWidget
        cell_widget = self.file_table.cellWidget(row, 1)
        if not cell_widget:
            # 安全检查：如果cell widget不存在，则不执行任何操作
            return

        # 2. [核心] 从容器 widget 中找到那个唯一的 QLabel 子控件
        #    findChild() 是查找子控件的可靠方法
        icon_label = cell_widget.findChild(QLabel)
        if not icon_label:
            return

        # --- 3. 后续的逻辑只与更新 icon_label 的内容有关 ---
        status_icon_map = {
            "待处理": "waiting", "分析中...": "processing",
            "已分析": "success", "失败": "error"
        }
    
        icon_name = status_icon_map.get(status_text, "question")
        icon = self.icon_manager.get_icon(icon_name)
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(24, 24))
        else:
            # 如果图标加载失败，清空 pixmap
            icon_label.setPixmap(QPixmap())

        if status_text == "失败" and error_message:
            icon_label.setToolTip(f"状态: {status_text}\n错误: {error_message}")
        else:
            icon_label.setToolTip(f"状态: {status_text}")

    # [新增] 新的槽函数，处理块进度
    def _on_chunk_progress(self, chunk_time_s, total_duration_s):
        """根据单个文件内部的分析进度，平滑地更新总进度条。"""
        if self.total_files == 0: return

        # 计算单个文件内的进度百分比 (0-100)
        chunk_percent = (chunk_time_s / total_duration_s) * 100 if total_duration_s > 0 else 100
        
        # 计算总进度:
        # 基础进度 = 已完成文件数 * 100
        base_progress = self.current_file_index * 100
        # 当前文件的细节进度 (确保单个文件进度不超过99.9，防止提前达到最大值)
        detail_progress = min(99.9, chunk_percent)
        
        # 总进度 = 基础进度 + 细节进度
        total_progress = base_progress + detail_progress

        # 将总进度应用到进度条（其最大值为 total_files * 100）
        self.progress_dialog.setValue(int(total_progress))

    def _on_batch_finished(self, success_cache, failure_info):
        """
        [v2.2 - 总结报告版]
        当整个批量分析任务（所有文件）全部处理完毕后，此槽函数被调用。
        它的职责是：
        1. 关闭进度对话框。
        2. 更新核心数据缓存。
        3. 向用户展示一个最终的、包含成功与失败统计的总结报告。
        4. 根据是否有成功的结果，启用“保存全部”按钮。
        5. 请求后台线程安全退出。
        """
        self.run_all_btn.setEnabled(True)
        self.import_btn.setEnabled(True)
        # 1. 确保进度条达到最大值并关闭，提供一个完成的视觉反馈
        if self.progress_dialog:
            self.progress_dialog.setValue(self.progress_dialog.maximum())
            self.progress_dialog.close()
        
        # 2. 将后台线程成功分析的结果，更新到主UI线程的分析缓存中
        self.analysis_cache.update(success_cache)
        
        # 注意：此处不再需要循环更新每一行的UI状态，因为这个工作
        # 已经由 _on_single_file_completed 槽函数在处理过程中实时完成了。
        
        # 3. 创建并显示总结报告
        num_success = len(success_cache)
        num_failed = len(failure_info)
        total_processed = num_success + num_failed

        # 只有在确实处理了文件的情况下才显示总结信息
        if total_processed > 0:
            if num_failed == 0:
                # 如果全部成功
                QMessageBox.information(self, "分析完成", f"所有 {total_processed} 个文件的批量分析已成功完成。")
            else:
                # 如果部分失败，显示一个带有详细信息的警告框
                error_details = "\n".join([f"- {os.path.basename(fp)}: {err}" for fp, err in failure_info.items()])
                
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Warning)
                msg_box.setWindowTitle("分析部分完成")
                msg_box.setText(f"批量分析完成，共处理 {total_processed} 个文件：\n"
                              f"  - 成功: {num_success} 个\n"
                              f"  - 失败: {num_failed} 个")
                msg_box.setInformativeText("失败的文件已被跳过。将鼠标悬停在状态图标上可查看具体错误。")
                msg_box.setDetailedText(error_details)
                msg_box.exec_()
        
        # 4. 如果有任何成功分析的文件，则启用保存按钮
        if num_success > 0:
            self.save_all_btn.setEnabled(True)
            
        # 5. 请求后台线程安全退出
        if self.batch_thread:
            self.batch_thread.quit()

    def _on_batch_error(self, error_msg):
        """批量分析发生错误时的处理。"""
        self.progress_dialog.close()
        QMessageBox.critical(self, "批量分析错误", error_msg)
        self._update_table() # 恢复表格状态
        self.batch_thread.quit()

    def _run_single_analysis(self, filepath):
        """
        [v2.4 - 修复版]
        对列表中的单个文件运行分析，并立即更新UI。
        此版本与批量分析逻辑保持一致，使用实时状态更新，并修复了信号签名错误。
        """
        # 0. 检查是否有分析任务正在进行，防止重叠
        if self.single_analysis_thread and self.single_analysis_thread.isRunning():
            QMessageBox.warning(self, "操作繁忙", "另一个单文件分析任务正在进行中，请稍后再试。")
            return
        
        # 1. 设置进度对话框
        progress_dialog = QProgressDialog(f"正在分析: {os.path.basename(filepath)}...", "取消", 0, 100, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setStyleSheet(self.main_page.parent_window.styleSheet())
        progress_dialog.setWindowIcon(self.main_page.parent_window.windowIcon())
        progress_dialog.show()

        # 2. 获取分析参数
        params = {
            'analyze_f0_intensity': True, 'analyze_formants': True,
            'pre_emphasis': self.main_page.pre_emphasis_checkbox.isChecked(),
            'f0_min': self.main_page.f0_range_slider.lowerValue(),
            'f0_max': self.main_page.f0_range_slider.upperValue(),
            'render_density': self.main_page.render_density_slider.value(),
            'formant_density': self.main_page.formant_density_slider.value(),
            'is_wide_band': self.main_page.spectrogram_type_checkbox.isChecked(),
        }

        # 3. 创建 QThread 和 Worker
        self.single_analysis_thread = QThread()
        # 即使是单个文件，Worker也需要一个列表
        self.single_analysis_worker = BatchAnalysisWorker([filepath], params)
        self.single_analysis_worker.moveToThread(self.single_analysis_thread)

        # 4. 定义完成和错误处理的内部函数
        def on_finish(success_cache, failure_info): # <-- [修复] 修正了签名
            progress_dialog.setValue(100)
            progress_dialog.close()
        
            # 将结果更新到主缓存中
            self.analysis_cache.update(success_cache)
        
            # 如果当前选中的就是这个文件，刷新中央视图以显示新分析的结果
            current_row = self.file_table.currentRow()
            if current_row != -1 and self.file_table.item(current_row, 0).data(Qt.UserRole) == filepath:
                self._perform_delayed_load() # 复用延迟加载逻辑来刷新视图
        
            # 如果有任何成功分析的文件，则启用保存按钮
            if any(status == "已分析" for _, status in self.file_list):
                self.save_all_btn.setEnabled(True)

            self.single_analysis_thread.quit()

        def on_error(err_msg):
            progress_dialog.close()
            QMessageBox.critical(self, "分析失败", err_msg)
            self.single_analysis_thread.quit()

        def on_chunk_progress(chunk_time_s, total_duration_s):
            if total_duration_s > 0:
                percent = (chunk_time_s / total_duration_s) * 100
                progress_dialog.setValue(int(percent))

        # [修复] 将 single_file_completed 连接到 _on_single_file_completed 槽
        self.single_analysis_worker.single_file_completed.connect(self._on_single_file_completed)
        self.single_analysis_worker.finished.connect(on_finish)
        self.single_analysis_worker.error.connect(on_error)
        self.single_analysis_worker.chunk_progress.connect(on_chunk_progress)
    
        self.single_analysis_thread.started.connect(self.single_analysis_worker.run)
    
        def cleanup():
            if self.single_analysis_worker:
                self.single_analysis_worker.deleteLater()
                self.single_analysis_worker = None
            if self.single_analysis_thread:
                self.single_analysis_thread.deleteLater()
                self.single_analysis_thread = None

        self.single_analysis_thread.finished.connect(cleanup)
    
        progress_dialog.canceled.connect(self.single_analysis_thread.requestInterruption)
        progress_dialog.canceled.connect(self.single_analysis_thread.quit)

        self.single_analysis_thread.start()


    def save_all_results(self):
        """
        [v2.3 - 渲染修复版]
        批量保存所有已分析的结果。
        此版本在调用主模块的渲染函数时，会传递当前文件的完整上下文（包括路径和时长），
        从而彻底修复了在批量保存图片时因状态不同步导致的 'TypeError'。
        """
        # 1. 弹出主选择对话框，让用户决定要保存什么
        main_dialog = BatchSaveDialog(self)
        if main_dialog.exec_() != QDialog.Accepted:
            return
            
        main_options = main_dialog.get_options()
        save_csv = main_options['save_csv']
        save_image = main_options['save_image']

        if not save_csv and not save_image:
            return

        # 2. 初始化选项字典
        csv_options, image_options = None, None

        # 3. 弹出特定类型的选项对话框
        if save_csv:
            csv_dialog = AdvancedCsvSaveDialog(self)
            if csv_dialog.exec_() == QDialog.Accepted:
                csv_options = csv_dialog.get_options()
            else:
                save_csv = False # 用户取消

        if save_image:
            image_dialog = AdvancedImageSaveDialog(self)
            if image_dialog.exec_() == QDialog.Accepted:
                image_options = image_dialog.get_options()
            else:
                save_image = False # 用户取消

        if not save_csv and not save_image:
            return

        # 4. 获取保存路径
        save_dir = QFileDialog.getExistingDirectory(self, "选择保存所有结果的文件夹")
        
        # 严格检查 save_dir 是否是一个非空的字符串
        if not (isinstance(save_dir, str) and save_dir):
            return # 用户点击了取消或关闭，静默返回

        # 5. 执行保存操作
        try:
            # --- CSV 合并模式的准备 ---
            all_dfs_to_merge = []
            if save_csv and csv_options.get('merge', False):
                merged_filename = f"merged_analysis_{int(time.time())}.csv"
                merged_filepath = os.path.join(save_dir, merged_filename)

            # --- 循环处理每个分析结果 ---
            num_files = len(self.analysis_cache)
            progress = QProgressDialog("正在批量保存结果...", "取消", 0, num_files, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.show()

            for i, (filepath, results) in enumerate(self.analysis_cache.items()):
                # 在循环内部对每个文件路径进行有效性检查
                if not (isinstance(filepath, str) and filepath):
                    print(f"警告: 在分析缓存中发现无效的文件路径，跳过此条目。")
                    continue

                progress.setValue(i)
                base_name = os.path.splitext(os.path.basename(filepath))[0]
                progress.setLabelText(f"正在保存: {base_name}...")
                QApplication.processEvents()

                if progress.wasCanceled():
                    break

                # --- 保存CSV逻辑 ---
                if save_csv:
                    df = self.main_page.convert_analysis_to_dataframe(results)
                    if df is not None:
                        if csv_options.get('merge', False):
                            df['source_file'] = base_name
                            all_dfs_to_merge.append(df)
                        else: # 单独保存模式
                            csv_path = os.path.join(save_dir, f"{base_name}_analysis.csv")
                            df.to_csv(csv_path, index=False, encoding='utf-8-sig')
                
                # --- 保存图片逻辑 ---
                if save_image:
                    # a. 加载音频数据以准备渲染环境
                    temp_y, temp_sr = librosa.load(filepath, sr=None, mono=True)
                    
                    # b. [核心修复] 在渲染前，将当前文件的完整上下文同步到主页面。
                    #    这确保了 render_high_quality_image 函数能获取到正确的文件名、时长等信息。
                    self.main_page.audio_data = temp_y
                    self.main_page.sr = temp_sr
                    self.main_page.current_filepath = filepath
                    self.main_page.known_duration = (len(temp_y) / temp_sr) * 1000

                    # c. 将分析结果应用到主页面的UI控件上
                    self.main_page.spectrogram_widget.set_data(results['S_db'], temp_sr, results['hop_length'])
                    self.main_page.spectrogram_widget.set_analysis_data(
                        f0_data=results.get('f0_data'),
                        f0_derived_data=results.get('f0_derived_data'),
                        intensity_data=results.get('intensity_data'),
                        formants_data=results.get('formants_data')
                    )
                    
                    # d. 给予UI足够的时间来处理和渲染更新
                    QApplication.processEvents()
                    time.sleep(0.05)
                    
                    # e. [核心修复] 调用渲染函数时，将当前循环的 `filepath` 作为新参数传递进去。
                    pixmap = self.main_page.render_high_quality_image(image_options, source_filepath=filepath)
                    
                    # f. 保存图片并释放内存
                    img_path = os.path.join(save_dir, f"{base_name}_view.png")
                    pixmap.save(img_path)
                    del temp_y
            
            # --- CSV 合并模式的最终写入 ---
            if save_csv and csv_options.get('merge', False) and all_dfs_to_merge:
                progress.setLabelText("正在合并CSV文件...")
                final_df = pd.concat(all_dfs_to_merge, ignore_index=True)
                final_df.sort_values(by=['source_file', 'timestamp'], inplace=True)
                final_df.to_csv(merged_filepath, index=False, encoding='utf-8-sig')
            
            progress.setValue(num_files)
            if not progress.wasCanceled():
                QMessageBox.information(self, "保存成功", f"结果已成功保存到:\n{save_dir}")

        except Exception as e:
            if 'progress' in locals() and progress.isVisible():
                progress.close()
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "保存失败", f"批量保存时出错: {e}")

    def _open_context_menu(self, position):
        """
        [v2.0 - 多选与插件集成版]
        构建并显示文件列表的右键上下文菜单。
        此版本支持多选，并能将选中的分析数据发送到可视化插件。
        """
        selected_rows = sorted(list(set(item.row() for item in self.file_table.selectedItems())))
        if not selected_rows:
            return

        menu = QMenu(self)
        num_selected = len(selected_rows)
        
        # --- 1. 获取选中文件的基本信息 ---
        selected_filepaths = [self.file_table.item(row, 0).data(Qt.UserRole) for row in selected_rows]
        # 检查选中的文件中，有多少已经分析过（有缓存数据）
        analyzed_filepaths = [fp for fp in selected_filepaths if fp in self.analysis_cache]
        num_analyzed = len(analyzed_filepaths)

        # --- 2. 构建菜单项 ---

        # 2.1. 分析操作
        analyze_action = menu.addAction(self.icon_manager.get_icon("analyze"), f"分析选中的 {num_selected} 个文件")
        analyze_action.triggered.connect(lambda: self._run_analysis_on_selected(selected_filepaths))
        
        menu.addSeparator()

        # 2.2. 发送到可视化插件 (只有在有已分析文件时才显示)
        if num_analyzed > 0:
            # 获取插件实例
            plotter_plugin = self.main_page.parent_window.plugin_manager.get_plugin_instance("com.phonacq.vowel_space_plotter")
            intonation_plugin = self.main_page.parent_window.plugin_manager.get_plugin_instance("com.phonacq.intonation_visualizer")

            # 只有当至少一个插件可用时，才创建子菜单
            if plotter_plugin or intonation_plugin:
                send_to_menu = menu.addMenu(self.icon_manager.get_icon("chart2"), f"发送 {num_analyzed} 个已分析文件到")
                
                if plotter_plugin:
                    plotter_action = send_to_menu.addAction(self.icon_manager.get_icon("chart"), "元音空间绘制器")
                    plotter_action.triggered.connect(lambda: self._send_data_to_plugin(analyzed_filepaths, 'formants'))
                
                if intonation_plugin:
                    intonation_action = send_to_menu.addAction(self.icon_manager.get_icon("chart"), "语调可视化器")
                    intonation_action.triggered.connect(lambda: self._send_data_to_plugin(analyzed_filepaths, 'f0'))
            
            menu.addSeparator()

        # 2.3. 文件操作
        play_action = menu.addAction(self.icon_manager.get_icon("play_audio"), "试听")
        play_action.setEnabled(num_selected == 1) # 只有单选时才能试听
        if num_selected == 1:
            play_action.triggered.connect(lambda: self._play_file(selected_filepaths[0]))

        delete_action = menu.addAction(self.icon_manager.get_icon("delete"), f"从此列表移除 {num_selected} 项")
        delete_action.triggered.connect(lambda: self._remove_selected_files(selected_rows))
        
        details_action = menu.addAction(self.icon_manager.get_icon("info"), "音频详情")
        details_action.setEnabled(num_selected == 1) # 只有单选时才能看详情
        if num_selected == 1:
            details_action.triggered.connect(lambda: self._show_file_details(selected_filepaths[0]))
        
        # 3. 显示菜单
        menu.exec_(QCursor.pos())


    def _send_data_to_plugin(self, filepaths, data_type):
        """
        [v2.1 - 音频路径修复版]
        核心数据发送逻辑。此版本现在会将每个文件的完整音频路径
        一同发送给插件，以实现自动音频加载。
        """
        plugin_id = None
        if data_type == 'f0':
            plugin_id = "com.phonacq.intonation_visualizer"
        elif data_type == 'formants':
            plugin_id = "com.phonacq.vowel_space_plotter"

        if not plugin_id: return

        plugin_instance = self.main_page.parent_window.plugin_manager.get_plugin_instance(plugin_id)
        if not plugin_instance:
            QMessageBox.warning(self, "插件未激活", f"无法执行操作，因为目标插件 ({plugin_id}) 未激活。")
            return

        files_sent_count = 0
        for fp in filepaths:
            if fp not in self.analysis_cache: continue
                
            cache = self.analysis_cache[fp]
            source_name = os.path.splitext(os.path.basename(fp))[0]
            
            single_file_data_points = []

            if data_type == 'f0' and 'f0_data' in cache:
                times, f0_values = cache['f0_data']
                for t, f0 in zip(times, f0_values):
                    single_file_data_points.append({'timestamp': t, 'f0_hz': f0})

            elif data_type == 'formants' and 'formants_data' in cache:
                sr = cache.get('sr', self.main_page.sr)
                if not sr: continue
                
                formants_list = cache.get('formants_data', [])
                for sample_pos, formants in formants_list:
                    if len(formants) >= 2:
                        single_file_data_points.append({
                            'timestamp': sample_pos / sr,
                            'F1': formants[0],
                            'F2': formants[1],
                        })
            
            if single_file_data_points:
                df = pd.DataFrame(single_file_data_points)
                
                # --- [核心修复] ---
                # 在 execute_kwargs 中增加 audio_filepath 参数，
                # 将当前正在处理的文件路径 fp 传递过去。
                execute_kwargs = {
                    'dataframe': df, 
                    'source_name': source_name,
                    'audio_filepath': fp  # <-- 关键的修复！
                }
                
                self.main_page.parent_window.plugin_manager.execute_plugin(plugin_id, **execute_kwargs)
                files_sent_count += 1

        if files_sent_count == 0:
            QMessageBox.warning(self, "无数据", f"在选中的已分析文件中，未找到任何有效的 {data_type} 数据可以发送。")

    def _play_file(self, filepath):
        """辅助方法：播放单个文件。"""
        self.main_page.player.stop()
        self.main_page.player.setMedia(QMediaContent(QUrl.fromLocalFile(filepath)))
        self.main_page.player.play()

    def _remove_selected_files(self, rows_to_remove):
        """辅助方法：从列表中移除所有选中的文件。"""
        # 从后往前删除，避免索引错乱
        for row in sorted(rows_to_remove, reverse=True):
            filepath_to_remove = self.file_list[row][0]
            
            # 如果删除的是当前正在显示的文件，则清理中心视图
            current_row = self.file_table.currentRow()
            if current_row != -1 and self.file_table.item(current_row, 0).data(Qt.UserRole) == filepath_to_remove:
                self.main_page.clear_all_central_widgets()
            
            del self.file_list[row]
            
        self._update_table()

    def _show_file_details(self, filepath):
        """辅助方法：显示单个文件的详细信息。"""
        try:
            info = sf.info(filepath)
            details = (f"文件名: {os.path.basename(filepath)}\n"
                       f"路径: {filepath}\n"
                       f"时长: {info.duration:.2f} 秒\n"
                       f"采样率: {info.samplerate} Hz\n"
                       f"通道数: {info.channels}\n"
                       f"格式: {info.format_info}")
            QMessageBox.information(self, "音频详情", details)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法获取文件详情: {e}")
    def load_files_from_external(self, filepaths):
        """
        [新增] 公共API，用于从外部模块接收文件列表并加载到批量分析面板中。
        
        :param filepaths: (list) 一个包含音频文件完整路径的列表。
        """
        if not filepaths:
            return

        added_count = 0
        for fp in filepaths:
            # 检查文件是否存在且未被添加
            if os.path.exists(fp) and not any(f[0] == fp for f in self.file_list):
                self.file_list.append((fp, "待处理"))
                added_count += 1
        
        if added_count > 0:
            self._update_table()
            self.run_all_btn.setEnabled(True)
            # 给用户一个明确的反馈
            QMessageBox.information(self, "加载成功", f"已成功从音频管理器导入 {added_count} 个文件到批量分析列表。")
        else:
            QMessageBox.information(self, "提示", "所有传送过来的文件都已存在于列表中。")