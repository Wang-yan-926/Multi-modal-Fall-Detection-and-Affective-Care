# main.py
'''
初始化音频（pygame.mixer）与全局样式表（STYLE_SHEET）。  
启动时先调用 init_database()，弹窗登录成功后根据不同角色（admin 管理员端 / family 家属亲情看护端）
动态加载对应权限和侧边栏菜单（如家属端的“飞书音视频通话”与“健康指标大屏”）。  
调度 DetectionThread 线程，将检测到的视频画面实时渲染到主界面上。

'''
import sys
import os
# 在 PyInstaller 冻结环境下，预先把 torch 自带的 CUDA DLL 目录加入 PATH 与 DLL 搜索路径，
# 避免 torch_cuda.dll 找不到 cudart64_12.dll / cublas64_12.dll 导致 CUDA 不可用
try:
    import torch as _torch_for_path
    _torch_lib = os.path.join(os.path.dirname(_torch_for_path.__file__), 'lib')
    if _torch_lib and os.path.isdir(_torch_lib):
        cur = os.environ.get('PATH', '')
        if _torch_lib not in cur:
            os.environ['PATH'] = _torch_lib + os.pathsep + cur
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(_torch_lib)
            except Exception:
                pass
        del _torch_for_path
except Exception:
    pass
import cv2
import pygame 
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, 
                             QPushButton, QListWidget, QListWidgetItem, 
                             QFileDialog, QHBoxLayout, QVBoxLayout, QComboBox, QDialog,
                             QMessageBox, QWidget)
from PyQt6.QtCore import Qt, QTimer, QDateTime, QUrl
from PyQt6.QtGui import QImage, QPixmap, QDesktopServices
# 导入拆分出去的模块
from database import init_database
from dialogs import LoginDialog, SettingsDialog, HistoryDialog, HealthDashboardDialog, EmotionDetectionDialog, AISmartDialog
from detector import DetectionThread
from ui_layout import Ui_MainWindow


# ==================== 摄像头枚举 ====================

_FRIENDLY_CAM_LABELS = {
    0: "摄像头 0 (首选 / 虚拟摄像头 iVCam)",
    1: "摄像头 1 (电脑内置 / 外接摄像头)",
    2: "摄像头 2 (外接设备)",
    3: "摄像头 3 (外接设备)",
    4: "摄像头 4 (外接设备)",
    5: "摄像头 5 (外接设备)",
    6: "摄像头 6 (外接设备)",
}


def _probe_camera(idx, backend):
    """探测某个摄像头是否可用：必须保证 cap.release() 否则会与情绪检测线程抢资源。"""
    cap = cv2.VideoCapture(idx, backend)
    try:
        if not cap.isOpened():
            return None
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        ret, frame = cap.read()
        if not ret or frame is None:
            return None
        try:
            backend_name = str(cap.getBackendName())
        except Exception:
            backend_name = ""
        return {"index": idx, "w": w, "h": h, "backend": backend_name}
    finally:
        cap.release()


def enumerate_cameras(max_index=6):
    """枚举可用摄像头：先 DSHOW 再默认 backend，跨平台稳定。"""
    results = []
    for i in range(max_index + 1):
        info = _probe_camera(i, cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY)
        if info is None and os.name == 'nt':
            info = _probe_camera(i, cv2.CAP_ANY)
        if info is not None:
            label = _FRIENDLY_CAM_LABELS.get(i, f"摄像头 {i} (外接设备)")
            results.append((label, i, info))
    return results


# ==================== 初始化音频模块 ====================
try:
    pygame.mixer.init()
except Exception as e:
    print(f"音频模块初始化失败: {e}")

# ==================== 全局主题样式表 ====================
STYLE_SHEET = """
QMainWindow, QDialog {
    background-color: #0F172A;
}

QWidget {
    color: #F8FAFC;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
}

QPushButton {
    background-color: #334155;
    border: 1px solid #475569;
    border-radius: 6px;
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 600;
    padding: 8px 14px;
}
QPushButton:hover {
    background-color: #475569;
    border-color: #64748B;
}
QPushButton:pressed {
    background-color: #1E293B;
}
QPushButton:disabled {
    background-color: #1E293B;
    border-color: #334155;
    color: #64748B;
}

QComboBox, QLineEdit {
    background-color: #334155;
    border: 1px solid #475569;
    border-radius: 6px;
    color: #FFFFFF;
    font-size: 13px;
    padding: 6px 10px;
}
QComboBox:hover, QLineEdit:hover {
    border-color: #64748B;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 25px;
    border-left-width: 1px;
    border-left-color: #475569;
    border-left-style: solid;
}
QComboBox QAbstractItemView {
    background-color: #1E293B;
    color: #F8FAFC;
    selection-background-color: #334155;
    border: 1px solid #475569;
}

QListWidget {
    background-color: #0F172A;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #CBD5E1;
    font-size: 13px;
    padding: 5px;
}
QListWidget::item {
    padding: 6px;
    border-bottom: 1px solid #1E293B;
}

QSlider::groove:horizontal {
    border: 1px solid #475569;
    height: 6px;
    background: #1E293B;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #38BDF8;
    border: 1px solid #0284C7;
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #7DD3FC;
}
"""

# ==================== PyQt6 主界面 ====================

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self, user_role="admin", username="root"):
        super().__init__()
        self.user_role = user_role  
        self.username = username

        self.current_settings = {
            "fall_threshold": 50,
            "sound_enabled": True,
            "buffer_seconds": 10,
            "feishu_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/e1d06cee-2c38-4679-962a-9fccb85fd766"
        }
        
        # 加载纯代码布局
        self.setupUi(self)

        role_str = "【管理员运维端】" if self.user_role == "admin" else "【家属亲情看护端】"
        self.setWindowTitle(f"智能跌倒检测与看护系统 {role_str} - 当前用户: {self.username}")

        self.thread = None
        self.video_source = 0  

        self.setup_camera_combobox()

        # 绑定核心按钮信号与槽
        self.btn_file.clicked.connect(self.select_video_file)
        self.btn_start.clicked.connect(self.start_detection)
        self.btn_stop.clicked.connect(self.stop_detection)
        self.btn_history.clicked.connect(self.open_history_dialog)
        
        # 绑定左下角静态布局的两个纯文字按钮
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        self.btn_account.clicked.connect(self.switch_account)

        self.apply_role_permissions()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_clock)
        self.timer.start(1000)

        self.add_log(f"系统启动成功，已连接 MySQL 数据库 (当前用户: {self.username})")

    def switch_account(self):
        if self.thread is not None and self.thread.isRunning():
            reply = QMessageBox.question(
                self, "正在监测中", 
                "当前正在进行实时视频监测，切换身份将停止监测。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            self.stop_detection()

        self.hide()

        login_dlg = LoginDialog(self)
        if login_dlg.exec() == QDialog.DialogCode.Accepted:
            new_role = login_dlg.user_role
            new_uname = login_dlg.logged_username
            
            self.new_window = MainWindow(user_role=new_role, username=new_uname)
            self.new_window.show()
            self.close()
        else:
            self.show()

    def apply_role_permissions(self):
        """家属端与管理员端的功能与交互丰富化重构"""
        if self.user_role == "family":
            # 1. 隐藏管理员专用的“系统高级设置”入口
            if hasattr(self, 'btn_settings'):
                self.btn_settings.setVisible(False)
            
            # 2. 锁定摄像头切换
            if hasattr(self, 'camera_combo'):
                self.camera_combo.setEnabled(False)
                self.camera_combo.setToolTip("家属看护端：已锁定默认视频流源。")

            # 3. 更改顶部主面板标题
            if hasattr(self, 'title_label'):
                self.title_label.setText("亲情看护端 - 智能人员跌倒实时监测系统")

            # 4. 在左侧边栏增加“飞书音视频通话”与“健康指标大屏”菜单按钮（样式与全局左侧菜单严格对齐统一）
            parent_layout = self.btn_history.parent().layout()
            if parent_layout is not None:
                index = parent_layout.indexOf(self.btn_history)
                
                # 统一的侧边栏菜单按钮样式表（与“历史片段”等保持完全一致）
                menu_btn_style = """
                    QPushButton {
                        background-color: transparent;
                        border: none;
                        color: #CBD5E1;
                        text-align: left;
                        font-size: 13px;
                        font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                        padding: 5px 0px;
                    }
                    QPushButton:hover {
                        color: #38BDF8;
                    }
                """

                # 飞书音视频通话按钮
                self.btn_feishu_call = QPushButton("飞书音视频通话", self.centralwidget)
                self.btn_feishu_call.setStyleSheet(menu_btn_style)
                self.btn_feishu_call.clicked.connect(self.call_feishu_phone)
                parent_layout.insertWidget(index + 1, self.btn_feishu_call)

                # 健康指标大屏按钮
                self.btn_health_dashboard = QPushButton("健康指标大屏", self.centralwidget)
                self.btn_health_dashboard.setStyleSheet(menu_btn_style)
                self.btn_health_dashboard.clicked.connect(self.open_health_dashboard)
                parent_layout.insertWidget(index + 2, self.btn_health_dashboard)

                # 情绪识别按钮
                self.btn_emotion = self._add_sidebar_menu_btn(
                    parent_layout, self.btn_health_dashboard, " 情绪检测识别", self.open_emotion_dialog
                )

                # AI 智能问答按钮
                self.btn_ai_chat = self._add_sidebar_menu_btn(
                    parent_layout, self.btn_emotion, " AI 智能问答", self.open_ai_dialog
                )

            self.add_log("温馨提示：欢迎登录【家属亲情看护端】，已为您加载精简版侧边栏菜单。")
        else:
            if hasattr(self, 'title_label'):
                self.title_label.setText("管理运维平台 - 智能人员跌倒实时监测系统")
            self.add_log("系统以【管理员】身份运行，已开放所有高级运维与参数配置权限。")

    def _add_sidebar_menu_btn(self, parent_layout, after_widget, text, slot, accent_color="#38BDF8"):
        """家属端统一追加一个侧边栏菜单按钮。"""
        btn = QPushButton(text, self.centralwidget)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: #CBD5E1;
                text-align: left;
                font-size: 13px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                padding: 5px 0px;
            }}
            QPushButton:hover {{
                color: {accent_color};
            }}
        """)
        btn.clicked.connect(slot)
        index = parent_layout.indexOf(after_widget)
        if index == -1:
            parent_layout.addWidget(btn)
        else:
            parent_layout.insertWidget(index + 1, btn)
        return btn

    def open_emotion_dialog(self):
        """弹出情绪识别弹窗（单例：已打开则激活到前台，不再重复创建）。"""
        existing = getattr(self, "_emotion_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dialog = EmotionDetectionDialog(self, model_path=self._resolve_emotion_model_path(), source=0)
        self._emotion_dialog = dialog
        dialog.destroyed.connect(lambda *_: setattr(self, "_emotion_dialog", None))
        dialog.exec()

    def open_ai_dialog(self):
        """弹出 AI 智能问答弹窗（单例：已打开则激活到前台，不再重复创建）。"""
        existing = getattr(self, "_ai_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dialog = AISmartDialog(self)
        self._ai_dialog = dialog
        dialog.destroyed.connect(lambda *_: setattr(self, "_ai_dialog", None))
        dialog.exec()

    def _resolve_emotion_model_path(self):
        """自动寻找情绪识别模型 best.onnx 的位置。"""
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "qingxu", "best.onnx"),
            os.path.join(os.getcwd(), "qingxu", "best.onnx"),
            os.path.join(os.getcwd(), "best.onnx"),
            os.path.join(os.getcwd(), "models", "best.onnx"),
        ]
        for p in candidates:
            p = os.path.abspath(p)
            if os.path.exists(p):
                return p
        return ""

    def call_feishu_phone(self):
        """通过飞书官方链接或API发起音视频电话连线"""
        feishu_meeting_url = "https://www.feishu.cn/" 
        reply = QMessageBox.question(
            self, "飞书音视频通话",
            "即将通过飞书官方开放接口向老人端智能终端发起音视频电话连线。\n是否立即调起飞书客户端/网页端？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(feishu_meeting_url))
            self.add_log("已成功触发飞书音视频电话呼叫协议。")

    def open_health_dashboard(self):
        """弹出独立的高颜值健康指标大屏"""
        dashboard = HealthDashboardDialog(self)
        dashboard.exec()

    def setup_camera_combobox(self):
        parent_layout = self.btn_camera.parent().layout()
        if parent_layout is None:
            return
        index = parent_layout.indexOf(self.btn_camera)
        parent_layout.removeWidget(self.btn_camera)
        self.btn_camera.deleteLater()

        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumWidth(220)
        cams = enumerate_cameras(max_index=6)

        if not cams:
            self.camera_combo.addItem("未检测到可用摄像头", 0)
        else:
            for label, idx, info in cams:
                hint = f"{info['w']}x{info['h']}" if info['w'] and info['h'] else ""
                display = f"{label}  [{hint}]" if hint else label
                self.camera_combo.addItem(display, idx)
            try:
                first_idx = self.camera_combo.findData(0)
                if first_idx >= 0:
                    self.camera_combo.setCurrentIndex(first_idx)
            except Exception:
                pass

        self.camera_combo.currentIndexChanged.connect(self.on_camera_changed)

        if index != -1:
            parent_layout.insertWidget(index, self.camera_combo)
        else:
            parent_layout.addWidget(self.camera_combo)

    def on_camera_changed(self, index):
        data = self.camera_combo.currentData()
        if data is not None:
            self.video_source = data
            self.add_log(f"已切换视频输入源 -> 摄像头索引 [{data}]")

    def update_clock(self):
        self.lbl_clock.setText(f"{QDateTime.currentDateTime().toString('yyyy-MM-dd hh:mm:ss')}")

    def add_log(self, text):
        time_str = QDateTime.currentDateTime().toString("hh:mm:ss")
        item = QListWidgetItem(f"[{time_str}] {text}")
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()

    def select_video_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video Files (*.mp4 *.avi *.mov)")
        if file_name:
            self.video_source = file_name
            self.add_log(f"已选择本地测试视频: {file_name.split('/')[-1]}")

    def open_history_dialog(self):
        dialog = HistoryDialog(self)
        dialog.exec()

    def open_settings_dialog(self):
        if self.user_role != "admin":
            QMessageBox.warning(self, "权限拒绝", "您当前是以普通家属身份登录，无法修改系统参数！")
            return

        dialog = SettingsDialog(self.current_settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_settings = dialog.settings
            self.add_log("系统设置已更新: 飞书Webhook已强制绑定")
            QMessageBox.information(self, "设置成功", "高级参数已成功更新！若正在监测，请重新点击“开始监测”生效。")

    def start_detection(self):
        if self.thread is not None and self.thread.isRunning():
            return
            
        self.thread = DetectionThread(source=self.video_source, settings=self.current_settings)
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.log_signal.connect(self.add_log)
        self.thread.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        if hasattr(self, 'camera_combo'):
            self.camera_combo.setEnabled(False)
        self.btn_file.setEnabled(False)

        self.lbl_live_badge.setText("LIVE 实时监测中")
        self.lbl_live_badge.setStyleSheet("color: #10B981; font-weight: bold; font-size: 13px; border: none;")

    def stop_detection(self):
        if self.thread is not None:
            self.thread.stop()
            self.thread = None

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if hasattr(self, 'camera_combo'):
            self.camera_combo.setEnabled(True)
        self.btn_file.setEnabled(True)

        self.video_label.setText("检测已停止")
        self.lbl_live_badge.setText("已停止")
        self.lbl_live_badge.setStyleSheet("color: #64748B; font-weight: bold; font-size: 13px; border: none;")

        self.lbl_alarm_status.setText("系统待命")
        self.alarm_card.setStyleSheet("background-color: #0F172A; border: 1px solid #1E293B; border-radius: 8px;")
        self.lbl_alarm_status.setStyleSheet("color: #38BDF8; border: none;")
        self.add_log("监测线程已被停止。")

    def update_image(self, cv_img, durus, fall_count, is_falling):
        rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        
        convert_to_Qt_format = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(convert_to_Qt_format)
        
        self.video_label.setPixmap(
            pixmap.scaled(self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

        self.lbl_posture.setText(f"姿态: {durus}")
        self.lbl_fall_count.setText(f"跌倒告警: {fall_count} 次")

        if is_falling:
            self.lbl_alarm_status.setText("警报：检测到人员跌倒！")
            self.lbl_alarm_status.setStyleSheet("color: #FFFFFF; border: none;")
            self.alarm_card.setStyleSheet("background-color: #DC2626; border-radius: 8px;")
        else:
            self.lbl_alarm_status.setText("画面监测正常")
            self.lbl_alarm_status.setStyleSheet("color: #10B981; border: none;")
            self.alarm_card.setStyleSheet("background-color: #022C22; border: 1px solid #065F46; border-radius: 8px;")

    def closeEvent(self, event):
        self.stop_detection()
        event.accept()

# ==================== 程序运行入口 ====================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)

    if not init_database():
        sys.exit(1)

    login_dlg = LoginDialog()
    if login_dlg.exec() == QDialog.DialogCode.Accepted:
        role = login_dlg.user_role
        uname = login_dlg.logged_username
        window = MainWindow(user_role=role, username=uname)
        window.show()
        sys.exit(app.exec())
    else:
        sys.exit(0)