import sys
import os
import subprocess
import shutil
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QTextEdit, QLineEdit, 
                             QGroupBox, QLabel, QStatusBar, QMessageBox,
                             QSplitter, QComboBox) # 新增导入
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QIcon

# --- 样式表 (QSS) ---
# 这将作为在 themes 文件夹中找不到任何主题时的后备默认样式
APP_STYLE = """
/* 全局样式 */
QWidget {
    background-color: #2E3440; /* Nord Polar Night */
    color: #ECEFF4; /* Nord Snow Storm */
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 14px;
}

/* 主窗口 */
QMainWindow {
    background-color: #2E3440;
}

/* 分组框 */
QGroupBox {
    background-color: #3B4252;
    border: 1px solid #4C566A;
    border-radius: 8px;
    margin-top: 1em;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top center;
    padding: 5px 10px;
    background-color: #434C5E;
    border-radius: 4px;
}

/* 按钮 */
QPushButton {
    background-color: #5E81AC; /* Nord Frost */
    color: #ECEFF4;
    border: none;
    padding: 10px 20px;
    border-radius: 6px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #81A1C1;
}
QPushButton:pressed {
    background-color: #88C0D0;
}
QPushButton:disabled {
    background-color: #4C566A;
    color: #D8DEE9;
}

/* 文本编辑区域 (用于显示状态和日志) */
QTextEdit {
    background-color: #272B36;
    border: 1px solid #4C566A;
    border-radius: 6px;
    padding: 5px;
    font-family: 'Consolas', 'Courier New', monospace;
}

/* 单行输入框 (用于提交信息) */
QLineEdit {
    background-color: #3B4252;
    border: 1px solid #4C566A;
    border-radius: 6px;
    padding: 8px;
}
QLineEdit:focus {
    border: 1px solid #5E81AC;
}

/* 状态栏 */
QStatusBar {
    background-color: #3B4252;
    color: #ECEFF4;
    font-weight: bold;
}
QStatusBar::item {
    border: none;
}

/* 滚动条 */
QScrollBar:vertical {
    border: none;
    background: #3B4252;
    width: 12px;
    margin: 15px 0 15px 0;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #5E81AC;
    min-height: 20px;
    border-radius: 6px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
"""

# --- 后台工作线程 ---
# 用于执行耗时的 Git 命令，避免 UI 阻塞
class GitWorker(QObject):
    """
    在后台线程中运行 Git 命令的工作器。
    """
    command_output = pyqtSignal(str)
    command_finished = pyqtSignal(bool, str)
    
    def __init__(self, commands):
        super().__init__()
        self.commands = commands
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        for command, description in self.commands:
            if not self.is_running:
                self.command_finished.emit(False, "操作被用户取消。")
                return

            self.command_output.emit(f"\n--- {description} ---\n")
            self.command_output.emit(f"> {' '.join(command)}\n")
            
            try:
                process = subprocess.Popen(
                    command, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    text=True, 
                    encoding='utf-8', 
                    errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                
                for line in iter(process.stdout.readline, ''):
                    if not self.is_running:
                        process.terminate()
                        break
                    self.command_output.emit(line)
                
                process.wait()
                
                if not self.is_running:
                     self.command_finished.emit(False, "操作被用户取消。")
                     return

                if process.returncode != 0:
                    error_message = f"命令执行失败，退出代码: {process.returncode}"
                    self.command_finished.emit(False, error_message)
                    return

            except FileNotFoundError:
                self.command_finished.emit(False, f"错误: 命令 '{command[0]}' 未找到。请确保 Git 已安装并已添加到系统 PATH。")
                return
            except Exception as e:
                self.command_finished.emit(False, f"发生意外错误: {e}")
                return
        
        self.command_finished.emit(True, "所有操作已成功完成！")


# --- 主窗口 ---
class GitUIMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Git 可视化提交工具")
        self.setGeometry(100, 100, 900, 650) # 稍微加宽窗口
        
        self.worker_thread = None
        self.git_worker = None
        
        # 定义 themes 文件夹的路径
        self.themes_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes")

        self.init_ui()
        self.populate_themes() # 填充主题下拉框
        self.check_git_environment()

    def init_ui(self):
        """
        初始化用户界面。
        """
        # --- 主布局 ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- 左侧面板 ---
        left_pane_widget = QWidget()
        left_layout = QVBoxLayout(left_pane_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Git 状态区域
        status_group = QGroupBox("Git 仓库状态")
        status_layout = QVBoxLayout(status_group)
        self.status_display = QTextEdit()
        self.status_display.setReadOnly(True)
        self.refresh_button = QPushButton("刷新状态")
        self.refresh_button.clicked.connect(self.refresh_git_status)
        status_layout.addWidget(self.status_display)
        status_layout.addWidget(self.refresh_button, alignment=Qt.AlignRight)

        # 2. 提交与推送区域
        commit_group = QGroupBox("提交与推送")
        commit_layout = QVBoxLayout(commit_group)
        commit_message_label = QLabel("提交信息:")
        self.commit_message_input = QLineEdit()
        self.commit_message_input.setPlaceholderText("例如：Feat: 添加新功能模块")
        self.commit_push_button = QPushButton("提交并推送到远程仓库")
        self.commit_push_button.clicked.connect(self.start_commit_and_push)
        commit_layout.addWidget(commit_message_label)
        commit_layout.addWidget(self.commit_message_input)
        commit_layout.addWidget(self.commit_push_button)
        
        left_layout.addWidget(status_group)
        left_layout.addWidget(commit_group)

        # --- 右侧面板 (日志) ---
        console_group = QGroupBox("实时日志")
        console_layout = QVBoxLayout(console_group)
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        console_layout.addWidget(self.console_output)

        # --- 创建可拖动的分割器 ---
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left_pane_widget)
        main_splitter.addWidget(console_group)
        main_splitter.setStretchFactor(0, 1) # 设置拉伸因子
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([450, 450]) # 设置初始大小

        # --- 底部主题选择区域 ---
        theme_widget = QWidget()
        theme_layout = QHBoxLayout(theme_widget)
        theme_layout.setContentsMargins(0, 10, 0, 0)
        theme_label = QLabel("界面主题:")
        self.theme_combo = QComboBox()
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        self.theme_combo.currentTextChanged.connect(self.apply_theme)

        # --- 组合最终布局 ---
        main_layout.addWidget(main_splitter)
        main_layout.addWidget(theme_widget)

        # --- 状态栏 ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def populate_themes(self):
        """
        扫描 'themes' 目录，填充主题选择下拉框，并尝试应用指定的默认主题。
        """
        if not os.path.exists(self.themes_path):
            try:
                os.makedirs(self.themes_path)
                print(f"创建 themes 目录于: {self.themes_path}")
            except OSError as e:
                print(f"创建 themes 目录失败: {e}")
                self.theme_combo.setEnabled(False)
                return

        themes = [f for f in os.listdir(self.themes_path) if f.endswith('.qss')]
        if themes:
            self.theme_combo.addItems(themes)
            
            # 尝试设置 "The_Great_Wave - light.qss" 为默认主题
            default_theme_name = "The_Great_Wave - light.qss"
            if default_theme_name in themes:
                self.theme_combo.setCurrentText(default_theme_name)
            else:
                # 如果找不到指定的默认主题，则列表中的第一个主题会自动被应用
                # 因为 `addItems` 会设置第一个项目为当前项，并触发 `currentTextChanged` 信号
                print(f"警告: 找不到默认主题 '{default_theme_name}'。将应用列表中的第一个主题。")
        else:
            print("未找到任何主题文件。使用内置默认样式。")
            self.theme_combo.addItem("默认主题")
            self.theme_combo.setEnabled(False)
            # 应用后备样式
            QApplication.instance().setStyleSheet(APP_STYLE)

    def apply_theme(self, theme_name):
        """
        应用所选的主题。
        """
        if not theme_name or theme_name == "默认主题":
            QApplication.instance().setStyleSheet(APP_STYLE)
            return
            
        theme_file = os.path.join(self.themes_path, theme_name)
        if os.path.exists(theme_file):
            try:
                with open(theme_file, 'r', encoding='utf-8') as f:
                    style = f.read()
                QApplication.instance().setStyleSheet(style)
                self.status_bar.showMessage(f"主题 '{theme_name}' 已应用。", 3000)
            except Exception as e:
                QMessageBox.warning(self, "主题错误", f"加载主题文件失败:\n{e}")
        else:
            print(f"主题文件未找到: {theme_file}")

    def check_git_environment(self):
        if not shutil.which("git"):
            self.show_error_and_disable("Git 未安装", "错误: Git 命令未找到。请安装 Git 并确保它在您的系统 PATH 中。")
            return

        try:
            subprocess.check_call(
                ['git', 'rev-parse', '--is-inside-work-tree'], 
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            self.status_bar.showMessage("Git 环境正常，准备就绪。", 5000)
            self.refresh_git_status()
        except subprocess.CalledProcessError:
            self.show_error_and_disable("非 Git 仓库", f"错误: 当前目录 ({os.getcwd()}) 不是一个有效的 Git 仓库。")
        except Exception as e:
            self.show_error_and_disable("环境检查失败", f"检查 Git 环境时出错: {e}")

    def show_error_and_disable(self, title, message):
        QMessageBox.critical(self, title, message)
        self.refresh_button.setEnabled(False)
        self.commit_push_button.setEnabled(False)
        self.commit_message_input.setEnabled(False)
        self.status_bar.showMessage("错误: Git 环境异常。", 0)
        self.status_display.setText(message)

    def refresh_git_status(self):
        self.status_display.clear()
        self.run_command_in_worker([(['git', 'status'], "正在获取 Git 状态...")], self.handle_status_finished)

    def start_commit_and_push(self):
        commit_message = self.commit_message_input.text().strip()
        if not commit_message:
            QMessageBox.warning(self, "信息缺失", "提交信息不能为空！")
            return

        commands = [
            (['git', 'add', '.'], "正在添加所有文件到暂存区..."),
            (['git', 'commit', '-m', commit_message], "正在提交更改..."),
            (['git', 'push'], "正在推送到远程仓库...")
        ]
        self.console_output.clear()
        self.run_command_in_worker(commands, self.handle_commit_push_finished)

    def run_command_in_worker(self, commands, on_finish_slot):
        self.set_controls_enabled(False)
        self.status_bar.showMessage(commands[0][1], 0)

        self.worker_thread = QThread()
        self.git_worker = GitWorker(commands)
        self.git_worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.git_worker.run)
        self.git_worker.command_output.connect(self.append_to_relevant_output)
        self.git_worker.command_finished.connect(on_finish_slot)
        
        self.git_worker.command_finished.connect(self.worker_thread.quit)
        self.git_worker.command_finished.connect(self.git_worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.on_worker_finished)

        self.worker_thread.start()

    def on_worker_finished(self):
        self.git_worker = None
        self.worker_thread = None
        print("后台线程已清理。")

    def set_controls_enabled(self, enabled):
        self.refresh_button.setEnabled(enabled)
        self.commit_push_button.setEnabled(enabled)
        self.commit_message_input.setEnabled(enabled)

    def append_to_relevant_output(self, text):
        if not self.git_worker: return

        # 'git status' 的输出进入左侧的状态显示区
        if self.git_worker.commands[0][0] == ['git', 'status']:
            self.status_display.append(text.strip())
        # 其他命令 (add, commit, push) 的输出进入右侧的日志区
        else:
            self.console_output.append(text.strip())

    def handle_status_finished(self, success, message):
        self.set_controls_enabled(True)
        if success:
            self.status_bar.showMessage("状态刷新成功！", 5000)
        else:
            self.status_bar.showMessage(f"状态刷新失败: {message}", 0)
            self.status_display.append(f"\n错误: {message}")

    def handle_commit_push_finished(self, success, message):
        self.set_controls_enabled(True)
        self.status_bar.showMessage(message, 10000)
        if success:
            QMessageBox.information(self, "成功", message)
            self.commit_message_input.clear()
            self.refresh_git_status()
        else:
            QMessageBox.critical(self, "失败", message)
    
    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            self.status_bar.showMessage("正在等待后台任务完成...", 0)
            if self.git_worker: self.git_worker.stop()
            self.worker_thread.quit()
            
            if not self.worker_thread.wait(5000):
                self.worker_thread.terminate()
                self.worker_thread.wait()
        
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    window = GitUIMainWindow()
    window.show()
    
    sys.exit(app.exec_())
