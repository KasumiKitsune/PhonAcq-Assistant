# --- START OF FILE modules/audio_manager_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "音频数据管理器" # [修改] 简化名称
MODULE_DESCRIPTION = "浏览、试听、管理已录制的口音数据、语音包和TTS文件。"
# ---

import os
import sys
import shutil
from datetime import datetime
import subprocess 

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QMenu, QSplitter, QInputDialog, QLineEdit,
                             QSlider, QComboBox, QApplication)
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QIcon
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

def create_page(parent_window, CONFIG, BASE_PATH, RESULTS_DIR, AUDIO_RECORD_DIR, icon_manager):
    AUDIO_TTS_DIR = os.path.join(BASE_PATH, "audio_tts")
    return AudioManagerPage(parent_window, CONFIG, BASE_PATH, RESULTS_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, icon_manager)

class AudioManagerPage(QWidget):
    def __init__(self, parent_window, config, base_path, results_dir, audio_record_dir, audio_tts_dir, icon_manager):
        super().__init__()
        self.parent_window = parent_window; self.config = config; self.BASE_PATH = base_path
        self.icon_manager = icon_manager
        
        self.DATA_SOURCES = {
            "口音采集会话": {"path": results_dir, "filter": lambda d, p: os.path.exists(os.path.join(p, d, 'log.txt'))},
            "语音包/图文采集": {"path": audio_record_dir, "filter": lambda d, p: True},
            "TTS 语音": {"path": audio_tts_dir, "filter": lambda d, p: True}
        }
        
        self.current_session_path = None; self.current_data_type = None; self.current_displayed_duration = 0
        self.player = QMediaPlayer(); self.player.setNotifyInterval(50) 
        
        self._init_ui()
        self._connect_signals()
        self.update_icons()
        self.apply_layout_settings()

    def _init_ui(self):
        main_splitter = QSplitter(Qt.Horizontal, self); self.left_panel = QWidget(); left_layout = QVBoxLayout(self.left_panel)
        left_layout.addWidget(QLabel("选择数据源:"))
        self.source_combo = QComboBox(); self.source_combo.addItems(self.DATA_SOURCES.keys()); self.source_combo.setToolTip("选择要查看的数据类型：\n- 口音采集会话: 来自'标准朗读采集'的会话文件夹。\n- 语音包/图文采集: 来自'提示音录制'和'看图说话'的文件夹。\n- TTS语音: 来自'TTS工具'生成的文件夹。")
        left_layout.addWidget(self.source_combo); left_layout.addWidget(QLabel("项目列表:"))
        self.session_list_widget = QListWidget(); self.session_list_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.session_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.session_list_widget.setToolTip("此处列出所选数据源下的所有项目文件夹。\n支持按住Ctrl或Shift进行多选，然后右键进行批量操作。")
        left_layout.addWidget(self.session_list_widget, 1)
        
        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        self.table_label = QLabel("请从左侧选择一个项目以查看文件"); self.table_label.setAlignment(Qt.AlignCenter)
        self.audio_table_widget = QTableWidget(); self.audio_table_widget.setColumnCount(4); self.audio_table_widget.setHorizontalHeaderLabels(["文件名", "文件大小", "修改日期", ""]); self.audio_table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.audio_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows); self.audio_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers); self.audio_table_widget.verticalHeader().setVisible(False); self.audio_table_widget.setAlternatingRowColors(True)
        self.audio_table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.audio_table_widget.setColumnWidth(1, 120); self.audio_table_widget.setColumnWidth(2, 180); self.audio_table_widget.setColumnWidth(3, 80)
        self.audio_table_widget.setToolTip("显示所选项目中的所有音频文件。\n双击可播放，右键可进行更多操作。")
        
        playback_panel = QWidget(); playback_layout = QHBoxLayout(playback_panel); playback_layout.setContentsMargins(0, 5, 0, 5)
        self.play_pause_btn = QPushButton(""); self.play_pause_btn.setMinimumWidth(80); self.play_pause_btn.setToolTip("播放或暂停当前选中的音频。")
        self.playback_slider = QSlider(Qt.Horizontal); self.playback_slider.setToolTip("显示当前播放进度，可拖动以快进或后退。")
        self.duration_label = QLabel("00:00.00 / 00:00.00")
        self.volume_label = QLabel("音量:"); self.volume_slider = QSlider(Qt.Horizontal); self.volume_slider.setFixedWidth(100); self.volume_slider.setToolTip("调整播放音量。")
        self.volume_percent_label = QLabel("75%"); self.volume_slider.setRange(0, 100); self.volume_slider.setValue(75); self.player.setVolume(75)
        playback_layout.addWidget(self.play_pause_btn); playback_layout.addWidget(self.playback_slider); playback_layout.addWidget(self.duration_label); playback_layout.addSpacing(20); playback_layout.addWidget(self.volume_label); playback_layout.addWidget(self.volume_slider); playback_layout.addWidget(self.volume_percent_label)
        
        right_layout.addWidget(self.table_label); right_layout.addWidget(self.audio_table_widget); right_layout.addWidget(playback_panel)
        main_splitter.addWidget(self.left_panel); main_splitter.addWidget(right_panel); main_splitter.setStretchFactor(0, 1); main_splitter.setStretchFactor(1, 3)
        page_layout = QHBoxLayout(self); page_layout.addWidget(main_splitter)

    def _connect_signals(self):
        self.player.positionChanged.connect(self.update_playback_position); self.player.durationChanged.connect(self.update_playback_duration); self.player.stateChanged.connect(self.on_player_state_changed); self.player.volumeChanged.connect(self.update_volume_label_from_player)
        self.source_combo.currentTextChanged.connect(self.populate_session_list); self.session_list_widget.itemSelectionChanged.connect(self.on_session_selection_changed); self.session_list_widget.customContextMenuRequested.connect(self.open_folder_context_menu)
        self.play_pause_btn.clicked.connect(self.on_play_button_clicked); self.playback_slider.sliderMoved.connect(self.set_playback_position); self.volume_slider.valueChanged.connect(self.player.setVolume)
        self.audio_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked); self.audio_table_widget.customContextMenuRequested.connect(self.open_file_context_menu)

    def update_icons(self):
        self.on_player_state_changed(self.player.state()) # 更新播放/暂停按钮图标
        # 更新表格内的按钮图标
        for row in range(self.audio_table_widget.rowCount()):
            btn = self.audio_table_widget.cellWidget(row, 3)
            if isinstance(btn, QPushButton): btn.setIcon(self.icon_manager.get_icon("delete"))

    def apply_layout_settings(self):
        config = self.parent_window.config; ui_settings = config.get("ui_settings", {}); width = ui_settings.get("editor_sidebar_width", 350); self.left_panel.setFixedWidth(width)
        
    def load_and_refresh(self):
        self.config = self.parent_window.config; self.apply_layout_settings(); self.update_icons()
        self.DATA_SOURCES["口音采集会话"]["path"] = self.config['file_settings'].get("results_dir", os.path.join(self.BASE_PATH, "Results"))
        self.DATA_SOURCES["语音包/图文采集"]["path"] = os.path.join(self.BASE_PATH, "audio_record"); self.DATA_SOURCES["TTS 语音"]["path"] = os.path.join(self.BASE_PATH, "audio_tts")
        self.populate_session_list()
        if self.session_list_widget.currentItem(): self.on_session_selection_changed()
        else: self.audio_table_widget.clearContents(); self.audio_table_widget.setRowCount(0); self.table_label.setText("请从左侧选择一个项目以查看文件"); self.reset_player()
            
    def populate_session_list(self):
        source_name = self.source_combo.currentText(); source_info = self.DATA_SOURCES.get(source_name)
        if not source_info: return
        current_text = self.session_list_widget.currentItem().text() if self.session_list_widget.currentItem() else None; self.session_list_widget.clear()
        base_path = source_info["path"]; path_filter = source_info["filter"]
        if not os.path.exists(base_path): os.makedirs(base_path, exist_ok=True); return
        try:
            sessions = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d)) and path_filter(d, base_path)], key=lambda s: os.path.getmtime(os.path.join(base_path, s)), reverse=True)
            self.session_list_widget.addItems(sessions)
            if current_text:
                items = self.session_list_widget.findItems(current_text, Qt.MatchFixedString)
                if items: self.session_list_widget.setCurrentItem(items[0])
        except Exception as e: QMessageBox.critical(self, "错误", f"加载项目列表失败: {e}")

    def populate_audio_table(self):
        self.audio_table_widget.setRowCount(0); self.reset_player()
        if not self.current_session_path: return
        try:
            supported_exts = ('.wav', '.mp3', '.flac', '.ogg')
            audio_files = sorted([f for f in os.listdir(self.current_session_path) if f.lower().endswith(supported_exts)])
            self.audio_table_widget.setRowCount(len(audio_files))
            for row, filename in enumerate(audio_files): self.update_table_row(row, os.path.join(self.current_session_path, filename))
        except Exception as e: QMessageBox.critical(self, "错误", f"加载音频文件列表失败: {e}")

    def on_session_selection_changed(self):
        selected_items = self.session_list_widget.selectedItems()
        if len(selected_items) != 1:
            self.current_session_path = None; self.current_data_type = None; self.audio_table_widget.setRowCount(0)
            self.table_label.setText(f"已选择 {len(selected_items)} 个项目" if selected_items else "请从左侧选择一个项目"); self.reset_player(); return
        current_item = selected_items[0]; source_name = self.source_combo.currentText(); source_info = self.DATA_SOURCES.get(source_name)
        if not source_info: return
        self.current_data_type = source_name; base_dir = source_info["path"]; self.current_session_path = os.path.join(base_dir, current_item.text())
        self.table_label.setText(f"正在查看: {current_item.text()}"); self.populate_audio_table()

    def update_table_row(self, row, filepath):
        filename = os.path.basename(filepath); file_size = os.path.getsize(filepath); mod_time = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M')
        item_filename = QTableWidgetItem(filename); item_filename.setData(Qt.UserRole, filepath)
        self.audio_table_widget.setItem(row, 0, item_filename); self.audio_table_widget.setItem(row, 1, QTableWidgetItem(f"{file_size / 1024:.1f} KB")); self.audio_table_widget.setItem(row, 2, QTableWidgetItem(mod_time))
        delete_btn = QPushButton("删除") # 恢复文本
        # delete_btn.setIcon(...) # 注释或删除这一行
        delete_btn.setToolTip("删除此文件")
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.setObjectName("LinkButton") # 恢复原来的对象名以便应用链接样式
        delete_btn.clicked.connect(lambda _, f=filepath: self.delete_file(f))
        # delete_btn.setProperty("isDeleteButton", True) # 可以保留也可以删除，取决于您的QSS
        self.audio_table_widget.setCellWidget(row, 3, delete_btn)
        self.audio_table_widget.setCellWidget(row, 3, delete_btn)

    def open_folder_context_menu(self, position):
        selected_items = self.session_list_widget.selectedItems();
        if not selected_items: return
        source_name = self.source_combo.currentText(); base_dir = self.DATA_SOURCES[source_name]["path"]
        menu = QMenu(); open_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "打开文件夹"); rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名"); delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除选中项")
        if len(selected_items) > 1: rename_action.setEnabled(False)
        action = menu.exec_(self.session_list_widget.mapToGlobal(position))
        if action == open_action: self.open_in_explorer(os.path.join(base_dir, selected_items[0].text()))
        elif action == rename_action: self.rename_folder(selected_items[0], base_dir)
        elif action == delete_action: self.delete_folders(selected_items, base_dir)

    def open_file_context_menu(self, position):
        item = self.audio_table_widget.itemAt(position);
        if not item: return
        row = item.row(); menu = QMenu(); play_action = menu.addAction(self.icon_manager.get_icon("play_audio"), "试听 / 暂停"); rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名"); delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除"); menu.addSeparator(); open_folder_action = menu.addAction(self.icon_manager.get_icon("show_in_explorer"), "在文件浏览器中显示")
        action = menu.exec_(self.audio_table_widget.mapToGlobal(position))
        if action == play_action: self.play_selected_item(row)
        elif action == rename_action: self.rename_selected_file()
        elif action == delete_action: self.delete_file(self.audio_table_widget.item(row, 0).data(Qt.UserRole))
        elif action == open_folder_action: self.open_in_explorer(self.current_session_path, select_file=os.path.basename(self.audio_table_widget.item(row, 0).data(Qt.UserRole)))

    def on_player_state_changed(self, state):
        if state == QMediaPlayer.PlayingState: self.play_pause_btn.setText("暂停"); self.play_pause_btn.setIcon(self.icon_manager.get_icon("pause"))
        else: self.play_pause_btn.setText("播放"); self.play_pause_btn.setIcon(self.icon_manager.get_icon("play"))
        if state == QMediaPlayer.EndOfMedia: self.playback_slider.setValue(0); self.duration_label.setText(f"00:00.00 / {self.format_time(self.player.duration())}")

    # ... (all other methods are correct and can remain unchanged) ...
    def update_volume_label_from_player(self, volume): self.volume_percent_label.setText(f"{volume}%")
    def on_item_double_clicked(self, item): self.play_selected_item(item.row())
    def rename_folder(self, item, base_dir):
        old_name = item.text(); old_path = os.path.join(base_dir, old_name)
        new_name, ok = QInputDialog.getText(self, "重命名文件夹", "请输入新的文件夹名称:", QLineEdit.Normal, old_name)
        if ok and new_name and new_name != old_name:
            new_path = os.path.join(base_dir, new_name.strip())
            if os.path.exists(new_path): QMessageBox.warning(self, "错误", "该名称的文件夹已存在。"); return
            try: os.rename(old_path, new_path); item.setText(new_name)
            except Exception as e: QMessageBox.critical(self, "错误", f"重命名失败: {e}")
    def delete_folders(self, items, base_dir):
        count = len(items); reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除选中的 {count} 个项目及其所有内容吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.parent_window.statusBar().showMessage(f"正在删除 {count} 个项目...", 0); QApplication.processEvents()
            error_occurred = False
            for item in items:
                try: self.parent_window.statusBar().showMessage(f"正在删除: {item.text()}...", 0); QApplication.processEvents(); shutil.rmtree(os.path.join(base_dir, item.text()))
                except Exception as e: self.parent_window.statusBar().showMessage(f"删除 '{item.text()}' 时出错。", 5000); QMessageBox.critical(self, "删除失败", f"删除文件夹 '{item.text()}' 时出错: {e}"); error_occurred = True; break
            if not error_occurred: self.parent_window.statusBar().showMessage(f"成功删除 {count} 个项目。", 4000)
            self.populate_session_list()
    def rename_selected_file(self):
        selected_items = self.audio_table_widget.selectedItems()
        if not selected_items: return
        row = selected_items[0].row(); old_filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole); old_basename, ext = os.path.splitext(os.path.basename(old_filepath))
        new_basename, ok = QInputDialog.getText(self, "重命名文件", "请输入新的文件名 (不含扩展名):", QLineEdit.Normal, old_basename)
        if ok and new_basename and new_basename.strip() and new_basename != old_basename:
            new_filepath = os.path.join(self.current_session_path, new_basename.strip() + ext)
            if os.path.exists(new_filepath): QMessageBox.warning(self, "错误", "文件名已存在。"); return
            try: os.rename(old_filepath, new_filepath); self.update_table_row(row, new_filepath)
            except Exception as e: QMessageBox.critical(self, "错误", f"重命名失败: {e}")
    def open_in_explorer(self, path, select_file=None):
        if not path or not os.path.exists(path): return
        try:
            if sys.platform == 'win32':
                if select_file: subprocess.run(['explorer', '/select,', os.path.join(path, select_file)])
                else: os.startfile(os.path.realpath(path))
            elif sys.platform == 'darwin': subprocess.check_call(['open', '-R', os.path.join(path, select_file)] if select_file else ['open', path])
            else: subprocess.check_call(['xdg-open', path])
        except Exception as e: QMessageBox.critical(self, "错误", f"无法打开路径: {e}")
    def play_selected_item(self, row):
        if row < 0 or row >= self.audio_table_widget.rowCount(): return
        filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
        if filepath and os.path.exists(filepath):
            if self.player.media().canonicalUrl() == QUrl.fromLocalFile(filepath) and self.player.state() != QMediaPlayer.StoppedState: self.toggle_playback()
            else: self.reset_player(); self.player.setMedia(QMediaContent(QUrl.fromLocalFile(filepath))); self.player.play()
    def delete_file(self, filepath):
        filename = os.path.basename(filepath); reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除文件 '{filename}' 吗？\n此操作不可撤销。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
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
    def update_playback_position(self, position):
        if not self.playback_slider.isSliderDown(): self.playback_slider.setValue(position)
        current_player_duration = self.player.duration()
        if current_player_duration > self.current_displayed_duration: self.update_playback_duration(current_player_duration)
        self.duration_label.setText(f"{self.format_time(position)} / {self.format_time(self.current_displayed_duration)}")
    def update_playback_duration(self, duration):
        if duration > 0 and duration != self.current_displayed_duration:
            self.current_displayed_duration = duration; self.playback_slider.setRange(0, duration); self.duration_label.setText(f"{self.format_time(self.player.position())} / {self.format_time(duration)}")
    def set_playback_position(self, position): self.player.setPosition(position)
    def format_time(self, ms):
        if ms <= 0: return "00:00.00"
        total_seconds = ms / 1000.0; m, s_frac = divmod(total_seconds, 60); s_int = int(s_frac); cs = int(round((s_frac - s_int) * 100));
        if cs == 100: cs = 0; s_int +=1
        if s_int == 60: s_int = 0; m += 1
        return f"{int(m):02d}:{s_int:02d}.{cs:02d}" 
    def reset_player(self):
        self.player.stop(); self.playback_slider.setValue(0); self.playback_slider.setRange(0, 0); self.duration_label.setText("00:00.00 / 00:00.00"); self.current_displayed_duration = 0