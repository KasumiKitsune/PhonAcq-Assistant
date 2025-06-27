# --- START OF FILE audio_manager_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "数据管理器"
MODULE_DESCRIPTION = "浏览、试听、管理已录制的口音数据和语音包。"
# ---

import os
import sys
import shutil
from datetime import datetime
import subprocess 

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QMenu, QSplitter, QInputDialog, QLineEdit,
                             QSlider)
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QIcon
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

def create_page(parent_window, CONFIG, BASE_PATH, RESULTS_DIR, AUDIO_RECORD_DIR):
    return AudioManagerPage(parent_window, CONFIG, BASE_PATH, RESULTS_DIR, AUDIO_RECORD_DIR)

class AudioManagerPage(QWidget):
    def __init__(self, parent_window, config, base_path, results_dir, audio_record_dir):
        super().__init__()
        self.parent_window = parent_window; self.config = config
        self.BASE_PATH = base_path; self.RESULTS_DIR = results_dir; self.AUDIO_RECORD_DIR = audio_record_dir
        self.current_session_path = None; self.current_data_type = None

        self.current_displayed_duration = 0

        self.player = QMediaPlayer()
        self.player.setNotifyInterval(50) 
        self.player.positionChanged.connect(self.update_playback_position)
        self.player.durationChanged.connect(self.update_playback_duration)
        self.player.stateChanged.connect(self.on_player_state_changed)
        self.player.volumeChanged.connect(self.update_volume_label_from_player)
        
        self._init_ui()

        self.accent_list_widget.itemSelectionChanged.connect(lambda: self.on_session_selection_changed(self.accent_list_widget, 'accent'))
        self.voicebank_list_widget.itemSelectionChanged.connect(lambda: self.on_session_selection_changed(self.voicebank_list_widget, 'voicebank'))
        self.play_pause_btn.clicked.connect(self.on_play_button_clicked)
        self.playback_slider.sliderMoved.connect(self.set_playback_position)
        self.volume_slider.valueChanged.connect(self.player.setVolume)
        self.audio_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.apply_layout_settings()

    def _init_ui(self):
        # ... (UI 初始化代码与上一版本相同) ...
        main_splitter = QSplitter(Qt.Horizontal, self)
        self.left_panel = QWidget(); left_layout = QVBoxLayout(self.left_panel)
        self.accent_list_label = QLabel("口音采集会话:"); self.accent_list_widget = QListWidget()
        self.voicebank_list_label = QLabel("已录制的语音包:"); self.voicebank_list_widget = QListWidget()
        self.accent_list_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.accent_list_widget.customContextMenuRequested.connect(lambda pos: self.open_folder_context_menu(self.accent_list_widget, pos, 'accent')); self.accent_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.voicebank_list_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.voicebank_list_widget.customContextMenuRequested.connect(lambda pos: self.open_folder_context_menu(self.voicebank_list_widget, pos, 'voicebank')); self.voicebank_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        left_layout.addWidget(self.accent_list_label); left_layout.addWidget(self.accent_list_widget, 1); left_layout.addWidget(self.voicebank_list_label); left_layout.addWidget(self.voicebank_list_widget, 1)
        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        self.table_label = QLabel("请从左侧选择一个项目以查看文件"); self.table_label.setAlignment(Qt.AlignCenter)
        self.audio_table_widget = QTableWidget(); self.audio_table_widget.setColumnCount(4); self.audio_table_widget.setHorizontalHeaderLabels(["文件名", "文件大小", "修改日期", ""])
        self.audio_table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.audio_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows); self.audio_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.audio_table_widget.verticalHeader().setVisible(False); self.audio_table_widget.setAlternatingRowColors(True)
        self.audio_table_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.audio_table_widget.customContextMenuRequested.connect(self.open_file_context_menu)
        self.audio_table_widget.setColumnWidth(1, 120); self.audio_table_widget.setColumnWidth(2, 180); self.audio_table_widget.setColumnWidth(3, 80)
        playback_panel = QWidget(); playback_layout = QHBoxLayout(playback_panel); playback_layout.setContentsMargins(0, 5, 0, 5)
        self.play_pause_btn = QPushButton("播放"); self.play_pause_btn.setMinimumWidth(80)
        self.playback_slider = QSlider(Qt.Horizontal); self.duration_label = QLabel("00:00.00 / 00:00.00")
        self.volume_label = QLabel("音量:"); self.volume_slider = QSlider(Qt.Horizontal); self.volume_slider.setFixedWidth(100)
        self.volume_percent_label = QLabel("75%"); self.volume_slider.setRange(0, 100); self.volume_slider.setValue(75); self.player.setVolume(75)
        playback_layout.addWidget(self.play_pause_btn); playback_layout.addWidget(self.playback_slider); playback_layout.addWidget(self.duration_label)
        playback_layout.addSpacing(20); playback_layout.addWidget(self.volume_label); playback_layout.addWidget(self.volume_slider); playback_layout.addWidget(self.volume_percent_label)
        right_layout.addWidget(self.table_label); right_layout.addWidget(self.audio_table_widget); right_layout.addWidget(playback_panel)
        main_splitter.addWidget(self.left_panel); main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1); main_splitter.setStretchFactor(1, 3)
        page_layout = QHBoxLayout(self); page_layout.addWidget(main_splitter)

    def apply_layout_settings(self):
        config = self.parent_window.config
        ui_settings = config.get("ui_settings", {})
        width = ui_settings.get("editor_sidebar_width", 350)
        self.left_panel.setFixedWidth(width)
        
    def load_and_refresh(self):
        # ... (保持不变)
        self.config = self.parent_window.config; self.apply_layout_settings()
        self.RESULTS_DIR = self.config['file_settings'].get("results_dir", os.path.join(self.BASE_PATH, "Results"))
        self.AUDIO_RECORD_DIR = os.path.join(self.BASE_PATH, "audio_record")
        self.populate_accent_list(); self.populate_voicebank_list()
        if self.accent_list_widget.currentItem() or self.voicebank_list_widget.currentItem():
             list_widget = self.accent_list_widget if self.accent_list_widget.currentItem() else self.voicebank_list_widget
             data_type = 'accent' if self.accent_list_widget.currentItem() else 'voicebank'
             self.on_session_selection_changed(list_widget, data_type)
        else: self.audio_table_widget.clearContents(); self.audio_table_widget.setRowCount(0); self.table_label.setText("请从左侧选择一个项目以查看文件"); self.reset_player()
            
    def populate_audio_table(self):
        # ... (保持不变)
        self.audio_table_widget.setRowCount(0); self.reset_player()
        if not self.current_session_path: return
        try:
            ext = '.wav' if self.current_data_type == 'accent' else '.mp3'
            audio_files = sorted([f for f in os.listdir(self.current_session_path) if f.lower().endswith(ext)])
            self.audio_table_widget.setRowCount(len(audio_files))
            for row, filename in enumerate(audio_files):
                filepath = os.path.join(self.current_session_path, filename); self.update_table_row(row, filepath)
        except Exception as e: QMessageBox.critical(self, "错误", f"加载音频文件列表失败: {e}")

    def update_table_row(self, row, filepath):
        # ... (保持不变)
        filename = os.path.basename(filepath); file_size = os.path.getsize(filepath); mod_time = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M')
        item_filename = QTableWidgetItem(filename); item_filename.setData(Qt.UserRole, filepath)
        self.audio_table_widget.setItem(row, 0, item_filename); self.audio_table_widget.setItem(row, 1, QTableWidgetItem(f"{file_size / 1024:.1f} KB")); self.audio_table_widget.setItem(row, 2, QTableWidgetItem(mod_time))
        delete_btn = QPushButton("删除"); delete_btn.setObjectName("LinkButton"); delete_btn.setToolTip("删除此文件")
        delete_btn.setCursor(Qt.PointingHandCursor); delete_btn.clicked.connect(lambda _, f=filepath: self.delete_file(f))
        self.audio_table_widget.setCellWidget(row, 3, delete_btn)

    def update_volume_label_from_player(self, volume):
        # ... (保持不变)
        self.volume_percent_label.setText(f"{volume}%")

    # ===== 修改/MODIFIED: 修正 populate_accent_list 方法 =====
    def populate_accent_list(self):
        current_text = self.accent_list_widget.currentItem().text() if self.accent_list_widget.currentItem() else None
        self.accent_list_widget.clear()
        if not os.path.exists(self.RESULTS_DIR): os.makedirs(self.RESULTS_DIR); return
        sessions = sorted([d for d in os.listdir(self.RESULTS_DIR) if os.path.isdir(os.path.join(self.RESULTS_DIR, d)) and os.path.exists(os.path.join(self.RESULTS_DIR, d, 'log.txt'))], key=lambda s: os.path.getmtime(os.path.join(self.RESULTS_DIR, s)), reverse=True)
        self.accent_list_widget.addItems(sessions)
        if current_text:
            items = self.accent_list_widget.findItems(current_text, Qt.MatchFixedString)
            if items: 
                self.accent_list_widget.setCurrentItem(items[0])

    # ===== 修改/MODIFIED: 修正 populate_voicebank_list 方法 =====
    def populate_voicebank_list(self):
        current_text = self.voicebank_list_widget.currentItem().text() if self.voicebank_list_widget.currentItem() else None
        self.voicebank_list_widget.clear()
        if not os.path.exists(self.AUDIO_RECORD_DIR): os.makedirs(self.AUDIO_RECORD_DIR); return
        voicebanks = sorted([d for d in os.listdir(self.AUDIO_RECORD_DIR) if os.path.isdir(os.path.join(self.AUDIO_RECORD_DIR, d))], key=lambda s: os.path.getmtime(os.path.join(self.AUDIO_RECORD_DIR, s)), reverse=True)
        self.voicebank_list_widget.addItems(voicebanks)
        if current_text:
            items = self.voicebank_list_widget.findItems(current_text, Qt.MatchFixedString)
            if items: 
                self.voicebank_list_widget.setCurrentItem(items[0])

    def on_session_selection_changed(self, list_widget, data_type):
        # ... (保持不变)
        selected_items = list_widget.selectedItems()
        if len(selected_items) != 1:
            self.current_session_path = None; self.current_data_type = None; self.audio_table_widget.setRowCount(0)
            self.table_label.setText(f"已选择 {len(selected_items)} 个项目" if selected_items else "请从左侧选择一个项目"); self.reset_player()
            return
        current_item = selected_items[0]
        if data_type == 'accent': self.voicebank_list_widget.clearSelection()
        else: self.accent_list_widget.clearSelection()
        self.current_data_type = data_type
        base_dir = self.RESULTS_DIR if data_type == 'accent' else self.AUDIO_RECORD_DIR
        self.current_session_path = os.path.join(base_dir, current_item.text())
        self.table_label.setText(f"正在查看: {current_item.text()}"); self.populate_audio_table()

    def on_item_double_clicked(self, item):
        # ... (保持不变)
        self.play_selected_item(item.row())

    # ... (所有其他方法，包括重构后的播放逻辑，都保持不变) ...
    def open_folder_context_menu(self, list_widget, position, data_type):
        selected_items = list_widget.selectedItems()
        if not selected_items: return
        menu = QMenu(); open_action = menu.addAction("打开文件夹"); rename_action = menu.addAction("重命名"); delete_action = menu.addAction("删除选中项")
        if len(selected_items) > 1: rename_action.setEnabled(False)
        action = menu.exec_(list_widget.mapToGlobal(position)); base_dir = self.RESULTS_DIR if data_type == 'accent' else self.AUDIO_RECORD_DIR
        if action == open_action: self.open_in_explorer(os.path.join(base_dir, selected_items[0].text()))
        elif action == rename_action: self.rename_folder(list_widget, selected_items[0], base_dir)
        elif action == delete_action: self.delete_folders(list_widget, selected_items, base_dir)
    def rename_folder(self, list_widget, item, base_dir):
        old_name = item.text(); old_path = os.path.join(base_dir, old_name)
        new_name, ok = QInputDialog.getText(self, "重命名文件夹", "请输入新的文件夹名称:", QLineEdit.Normal, old_name)
        if ok and new_name and new_name != old_name:
            new_path = os.path.join(base_dir, new_name.strip())
            if os.path.exists(new_path): QMessageBox.warning(self, "错误", "该名称的文件夹已存在。"); return
            try: os.rename(old_path, new_path); item.setText(new_name)
            except Exception as e: QMessageBox.critical(self, "错误", f"重命名失败: {e}")
    def delete_folders(self, list_widget, items, base_dir):
        count = len(items)
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除选中的 {count} 个项目及其所有内容吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for item in items:
                try: shutil.rmtree(os.path.join(base_dir, item.text()))
                except Exception as e: QMessageBox.critical(self, "删除失败", f"删除文件夹 '{item.text()}' 时出错: {e}"); break
            self.load_and_refresh()
    def open_file_context_menu(self, position):
        item = self.audio_table_widget.itemAt(position);
        if not item: return
        row = item.row(); menu = QMenu(); play_action = menu.addAction("试听 / 暂停"); rename_action = menu.addAction("重命名"); delete_action = menu.addAction("删除"); menu.addSeparator(); open_folder_action = menu.addAction("在文件浏览器中显示")
        action = menu.exec_(self.audio_table_widget.mapToGlobal(position))
        if action == play_action: self.play_selected_item(row)
        elif action == rename_action: self.rename_selected_file()
        elif action == delete_action: self.delete_file(self.audio_table_widget.item(row, 0).data(Qt.UserRole))
        elif action == open_folder_action: self.open_in_explorer(self.current_session_path)
    def rename_selected_file(self):
        selected_items = self.audio_table_widget.selectedItems()
        if not selected_items: return
        row = selected_items[0].row(); old_filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
        old_basename, ext = os.path.splitext(os.path.basename(old_filepath))
        new_basename, ok = QInputDialog.getText(self, "重命名文件", "请输入新的文件名 (不含扩展名):", QLineEdit.Normal, old_basename)
        if ok and new_basename and new_basename != old_basename:
            new_filepath = os.path.join(self.current_session_path, new_basename.strip() + ext)
            if os.path.exists(new_filepath): QMessageBox.warning(self, "错误", "文件名已存在。"); return
            try: os.rename(old_filepath, new_filepath); self.update_table_row(row, new_filepath)
            except Exception as e: QMessageBox.critical(self, "错误", f"重命名失败: {e}")
    def open_in_explorer(self, path):
        if not path or not os.path.exists(path): return
        try:
            if sys.platform == 'win32': os.startfile(os.path.realpath(path))
            elif sys.platform == 'darwin': subprocess.check_call(['open', path])
            else: subprocess.check_call(['xdg-open', path])
        except Exception as e: QMessageBox.critical(self, "错误", f"无法打开路径: {e}")
    def play_selected_item(self, row):
        if row < 0 or row >= self.audio_table_widget.rowCount(): return
        filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
        if filepath and os.path.exists(filepath):
            if self.player.media().canonicalUrl() == QUrl.fromLocalFile(filepath): self.toggle_playback()
            else: self.reset_player(); self.player.setMedia(QMediaContent(QUrl.fromLocalFile(filepath))); self.player.play()
    def delete_file(self, filepath):
        filename = os.path.basename(filepath)
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除文件 '{filename}' 吗？\n此操作不可撤销。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                if self.player.media().canonicalUrl() == QUrl.fromLocalFile(filepath): self.reset_player()
                os.remove(filepath); self.populate_audio_table()
            except Exception as e: QMessageBox.critical(self, "错误", f"删除失败: {e}")
    def on_play_button_clicked(self):
        if self.player.state() in [QMediaPlayer.PlayingState, QMediaPlayer.PausedState]: self.toggle_playback()
        else:
            current_row = self.audio_table_widget.currentRow()
            if current_row != -1: self.play_selected_item(current_row)
    def toggle_playback(self):
        if self.player.state() == QMediaPlayer.PlayingState: self.player.pause()
        else: self.player.play()
    def on_player_state_changed(self, state):
        if state == QMediaPlayer.PlayingState: self.play_pause_btn.setText("暂停")
        else: self.play_pause_btn.setText("播放")
        if state == QMediaPlayer.LoadedMedia or state == QMediaPlayer.EndOfMedia:
            self.update_playback_duration(self.player.duration())
            if state == QMediaPlayer.EndOfMedia:
                self.playback_slider.setValue(0); self.duration_label.setText(f"00:00.00 / {self.format_time(self.player.duration())}")
    def update_playback_position(self, position):
        if not self.playback_slider.isSliderDown(): self.playback_slider.setValue(position)
        current_player_duration = self.player.duration()
        if current_player_duration > self.current_displayed_duration: self.update_playback_duration(current_player_duration)
        self.duration_label.setText(f"{self.format_time(position)} / {self.format_time(self.current_displayed_duration)}")
    def update_playback_duration(self, duration):
        if duration > 0 and duration != self.current_displayed_duration:
            self.current_displayed_duration = duration
            self.playback_slider.setRange(0, duration)
            self.duration_label.setText(f"{self.format_time(self.player.position())} / {self.format_time(duration)}")
    def set_playback_position(self, position): self.player.setPosition(position)
    def format_time(self, ms):
        if ms <= 0: return "00:00.00"
        total_seconds = ms / 1000.0; m, s_frac = divmod(total_seconds, 60); s_int = int(s_frac)
        cs = int(round((s_frac - s_int) * 100));
        if cs == 100: cs = 0; s_int +=1
        if s_int == 60: s_int = 0; m += 1
        return f"{int(m):02d}:{s_int:02d}.{cs:02d}" 
    def reset_player(self):
        self.player.stop(); self.playback_slider.setValue(0); self.playback_slider.setRange(0, 0)
        self.duration_label.setText("00:00.00 / 00:00.00"); self.current_displayed_duration = 0