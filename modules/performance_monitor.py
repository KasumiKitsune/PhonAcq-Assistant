import sys
import psutil
from collections import deque
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout, 
                             QPushButton, QFrame, QStyle, QGroupBox, QWidget) # 导入 QWidget
from PyQt5.QtCore import QTimer, Qt, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QPolygonF

class PlotWidget(QWidget):
    # PlotWidget 的 __init__ 和 add_point/clear_data 方法保持不变
    def __init__(self, unit="", max_points=60, fixed_max=None, parent=None):
        super().__init__(parent)
        self.max_points = max_points
        self.unit = f"({unit})"
        self.data_points = deque(maxlen=self.max_points)
        self.setMinimumHeight(120)
        self.fixed_max = fixed_max
        self.max_value = self.fixed_max if self.fixed_max is not None else 1.0
        self.left_padding = 50
        self.bottom_padding = 20
        self.top_padding = 10
        self.right_padding = 10

    def add_point(self, value):
        self.data_points.append(value)
        if self.fixed_max is None:
            current_max = max(self.data_points) if self.data_points else 1.0
            new_max_value = max(0.1, current_max * 1.25)
            font_metrics = self.fontMetrics()
            label_width = font_metrics.width(f"{new_max_value:.1f}") + 10
            self.left_padding = max(50, label_width)
            self.max_value = new_max_value
        else:
            font_metrics = self.fontMetrics()
            label_width = font_metrics.width(f"{self.fixed_max:.1f}") + 10
            self.left_padding = max(50, label_width)
        self.update()

    def clear_data(self):
        self.data_points.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().color(self.backgroundRole()))

        plot_rect = self.rect().adjusted(self.left_padding, self.top_padding, -self.right_padding, -self.bottom_padding)
        if not plot_rect.isValid(): return

        axis_pen = QPen(self.palette().color(self.foregroundRole()), 1, Qt.SolidLine)
        grid_pen = QPen(self.palette().color(self.foregroundRole()), 0.5, Qt.DotLine)
        text_pen = QPen(self.palette().color(self.foregroundRole()))
        painter.setPen(text_pen)

        # Y轴绘制逻辑 (保持不变)
        num_y_ticks = 4
        for i in range(num_y_ticks + 1):
            val = self.max_value * i / num_y_ticks
            y = plot_rect.bottom() - (plot_rect.height() * i / num_y_ticks)
            label = f"{val:.1f}"
            painter.drawText(0, int(y) - 10, self.left_padding - 5, 20, Qt.AlignVCenter | Qt.AlignRight, label)
            if i > 0:
                painter.setPen(grid_pen)
                painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y))

        # [核心修复] 使用一个明确的矩形来绘制X轴标签，确保空间充足
        painter.setPen(text_pen)
        text_y_start = plot_rect.bottom()
        text_rect_height = self.bottom_padding

        # 绘制 "60s ago"
        painter.drawText(
            plot_rect.left(), text_y_start, 
            100, text_rect_height, # 给予一个足够宽的矩形
            Qt.AlignVCenter | Qt.AlignLeft, "60s ago"
        )
        # 绘制 "Now"
        painter.drawText(
            plot_rect.right() - 100, text_y_start,
            100, text_rect_height, # 给予一个足够宽的矩形
            Qt.AlignVCenter | Qt.AlignRight, "Now"
        )
        
        # 绘制坐标轴线和数据线 (保持不变)
        painter.setPen(axis_pen)
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.topLeft())
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.bottomRight())
        if not self.data_points: return
        data_pen = QPen(QColor("#007AFF"), 2)
        painter.setPen(data_pen)
        points = QPolygonF()
        for i, value in enumerate(self.data_points):
            x = plot_rect.left() + plot_rect.width() * i / max(1, self.max_points - 1)
            plot_value = min(value, self.max_value) 
            y = plot_rect.bottom() - (plot_rect.height() * plot_value / self.max_value)
            points.append(QPointF(x, y))
        painter.drawPolyline(points)


class PerformanceMonitor(QDialog):
    # __init__ 方法保持不变
    def __init__(self, target_widget, parent=None):
        super().__init__(parent)
        self.target_widget = target_widget
        self.process = psutil.Process()
        self.cpu_cores = psutil.cpu_count()
        self.last_io_counters = psutil.disk_io_counters()
        self.setWindowTitle("性能监视器")
        self.setWindowIcon(parent.windowIcon() if parent else self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.setMinimumSize(800, 500)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)
        self.update_stats()

    def _init_ui(self):
        top_layout = QHBoxLayout(self)
        top_layout.setContentsMargins(15, 15, 15, 15)
        top_layout.setSpacing(15)

        # --- 左栏: 图表 ---
        # [核心修复] 使用 QWidget 替换 QFrame，并移除 setFrameShape
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0) # 确保布局没有额外的边距
        
        self.cpu_plot = PlotWidget(unit="%", fixed_max=100.0)
        self.mem_plot = PlotWidget(unit="MB")
        self.disk_io_plot = PlotWidget(unit="MB/s")

        left_layout.addWidget(QLabel("<b>CPU 使用率</b> (%)"))
        left_layout.addWidget(self.cpu_plot)
        left_layout.addWidget(QLabel("<b>内存占用</b> (MB)"))
        left_layout.addWidget(self.mem_plot)
        left_layout.addWidget(QLabel("<b>磁盘占用 (总 I/O)</b> (MB/s)"))
        left_layout.addWidget(self.disk_io_plot)

        # --- 右栏: 实时报告 (保持不变) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(20)
        
        target_group = QGroupBox("监视信息")
        target_layout = QGridLayout(target_group)
        target_id = self.target_widget.property('main_window_attr_name') or "未知模块"
        target_layout.addWidget(QLabel("<b>监视目标:</b>"), 0, 0)
        target_layout.addWidget(QLabel(f"{target_id}"), 0, 1)
        target_layout.addWidget(QLabel("<b>CPU 核心数:</b>"), 1, 0)
        target_layout.addWidget(QLabel(f"{self.cpu_cores} 核"), 1, 1)

        report_group = QGroupBox("实时数据")
        report_layout = QGridLayout(report_group)
        self.total_cpu_label = QLabel("N/A")
        self.total_mem_label = QLabel("N/A")
        self.est_cpu_label = QLabel("N/A")
        self.est_mem_label = QLabel("N/A")
        report_layout.addWidget(QLabel("总进程 CPU:"), 0, 0)
        report_layout.addWidget(self.total_cpu_label, 0, 1)
        report_layout.addWidget(QLabel("总进程内存:"), 1, 0)
        report_layout.addWidget(self.total_mem_label, 1, 1)
        report_layout.addWidget(QLabel("模块CPU增量:"), 2, 0)
        report_layout.addWidget(self.est_cpu_label, 2, 1)
        report_layout.addWidget(QLabel("模块内存增量:"), 3, 0)
        report_layout.addWidget(self.est_mem_label, 3, 1)
        
        control_group = QGroupBox("控制")
        control_layout = QVBoxLayout(control_group)
        self.reset_baseline_btn = QPushButton("重置增量基线")
        self.reset_baseline_btn.clicked.connect(self.reset_baseline)
        info_label = QLabel("提示：增量为当前值与基线值的差。负数表示资源被释放 (例如GC)。")
        info_label.setWordWrap(True)
        control_layout.addWidget(self.reset_baseline_btn)
        control_layout.addWidget(info_label)

        right_layout.addWidget(target_group)
        right_layout.addWidget(report_group)
        right_layout.addWidget(control_group)

        top_layout.addWidget(left_panel, 2)
        top_layout.addWidget(right_panel, 1)

    # 其他所有逻辑方法 (update_stats, reset_baseline等) 均保持不变
    def update_stats(self):
        try:
            _ = self.target_widget.isVisible()
        except RuntimeError:
            self.close()
            return
        try:
            cpu_percent = self.process.cpu_percent(interval=None)
            mem_info = self.process.memory_info()
            mem_rss_mb = mem_info.rss / (1024 * 1024)
            io_counters = psutil.disk_io_counters()
            read_mb_s = (io_counters.read_bytes - self.last_io_counters.read_bytes) / (1024 * 1024)
            write_mb_s = (io_counters.write_bytes - self.last_io_counters.write_bytes) / (1024 * 1024)
            self.last_io_counters = io_counters
            total_io_mb_s = read_mb_s + write_mb_s

            self.cpu_plot.add_point(cpu_percent)
            self.mem_plot.add_point(mem_rss_mb)
            self.disk_io_plot.add_point(total_io_mb_s)

            self.total_cpu_label.setText(f"<b>{cpu_percent:.1f} %</b>")
            self.total_mem_label.setText(f"<b>{mem_rss_mb:.1f} MB</b>")
            self.estimate_widget_impact(cpu_percent, mem_rss_mb)
        except psutil.NoSuchProcess:
            self.timer.stop()
            self.setWindowTitle("性能监视器 (进程已结束)")
        except Exception as e:
            print(f"更新性能统计时发生错误: {e}")

    def estimate_widget_impact(self, current_cpu, current_mem):
        if not hasattr(self, 'baseline_cpu'):
            self.reset_baseline()
        cpu_delta = current_cpu - self.baseline_cpu
        mem_delta = current_mem - self.baseline_mem
        cpu_color = "#C62828" if cpu_delta > 0.1 else "#2E7D32"
        mem_color = "#C62828" if mem_delta > 0.1 else "#2E7D32"
        self.est_cpu_label.setText(f"<b style='color:{cpu_color}'>{cpu_delta:+.1f} %</b>")
        self.est_mem_label.setText(f"<b style='color:{mem_color}'>{mem_delta:+.1f} MB</b>")

    def reset_baseline(self):
        try:
            self.baseline_cpu = self.process.cpu_percent(interval=None)
            self.baseline_mem = self.process.memory_info().rss / (1024 * 1024)
            self.est_cpu_label.setText("基线已重置")
            self.est_mem_label.setText("基线已重置")
            self.cpu_plot.clear_data()
            self.mem_plot.clear_data()
            self.disk_io_plot.clear_data()
            print("Performance baseline reset.")
        except psutil.NoSuchProcess:
            pass
        
    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)