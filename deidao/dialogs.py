import math as _math
import struct as _struct


def _resample_to_16k(audio):
    """将 AudioData 重采样到 16kHz / 16bit / mono（Vosk small 模型要求）。"""
    try:
        import speech_recognition as sr
        if audio.sample_rate == 16000 and audio.sample_width == 2:
            return audio
        # 用 AudioData 自带的 get_raw_data + 重新打包的方式做最简单的线性重采样
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        return sr.AudioData(raw, 16000, 2)
    except Exception:
        return audio


def _audio_rms(audio):
    """粗略估算一段音频的均方根能量，用于诊断。"""
    try:
        raw = audio.get_raw_data()
        # 16bit signed little endian
        n = len(raw) // 2
        if n <= 0:
            return 0.0
        samples = _struct.unpack(f"<{n}h", raw[:n * 2])
        s = sum(x * x for x in samples) / n
        return _math.sqrt(s)
    except Exception:
        return 0.0


# dialogs.py
'''
弹窗与交互功能模块核心功能：
封装了系统中所有的独立弹窗界面及特定业务交互逻辑。
主要内容：LoginDialog：系统身份验证登录框（校验 MySQL 中的账号角色）。  
SettingsDialog：系统高级参数设置（调节跌倒倾斜角阈值、声音开关、缓冲区秒数等）。 
 HistoryDialog：历史跌倒告警记录与亲情处理中心（支持左侧列表查看历史、右侧视频回放、填写家属处理意见并同步更新数据库状态）。  
 HealthDashboardDialog：专属老人健康指标可视化监控大屏（模拟心率、血氧、血压等体征，支持未来物联网硬件接入扩展）。
 EmotionDetectionDialog：基于 YOLOv11 的人脸情绪识别弹窗（左侧视频流 + 右侧当前情绪、置信度、各类占比与给老人的关怀建议占位）。
 AISmartDialog：智能问答弹窗，集成打字输入与系统麦克风语音识别（基于 speech_recognition + Vosk），为后续接入本地/云端大模型预留 answer_question() 接口。
'''
import os
import time as _time
import threading
import pymysql
import cv2
import numpy as np
from PyQt6.QtWidgets import (QDialog, QLabel, QPushButton, QListWidget, QListWidgetItem,
                             QFileDialog, QHBoxLayout, QVBoxLayout, QLineEdit,
                             QMessageBox, QSlider, QCheckBox, QFormLayout, QTextEdit, QGridLayout, QFrame,
                             QComboBox, QProgressBar, QPlainTextEdit, QToolButton, QMenu)
from PyQt6.QtCore import Qt, QTimer, QUrl, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QDesktopServices, QFont, QAction

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(" 系统身份验证 (MySQL版)")
        self.resize(360, 230)
        self.user_role = None  
        self.logged_username = None

        layout = QVBoxLayout(self)

        title_label = QLabel("智能跌倒检测与看护系统")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #38BDF8; margin-bottom: 10px;")
        layout.addWidget(title_label)

        form_layout = QFormLayout()
        
        self.txt_user = QLineEdit()
        self.txt_user.setPlaceholderText("请输入账户名 (如: root)")
        self.txt_user.setText("family")
        form_layout.addRow("账    号:", self.txt_user)

        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pass.setPlaceholderText("请输入密码")
        self.txt_pass.setText("123456")
        form_layout.addRow("密    码:", self.txt_pass)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        btn_login = QPushButton("登录系统")
        btn_login.clicked.connect(self.handle_login)
        btn_layout.addWidget(btn_login)

        btn_cancel = QPushButton("退出")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def handle_login(self):
        username = self.txt_user.text().strip()
        password = self.txt_pass.text().strip()

        try:
            db = pymysql.connect(
                host='localhost', user='root', password='231006410',
                database='fall_detector_db', charset='utf8mb4'
            )
            cursor = db.cursor()
            cursor.execute("SELECT role FROM users WHERE username=%s AND password=%s;", (username, password))
            result = cursor.fetchone()
            cursor.close()
            db.close()

            if result:
                self.user_role = result[0]  
                self.logged_username = username
                self.accept()
            else:
                QMessageBox.warning(self, "登录失败", "用户名或密码错误，请检查 MySQL 中的凭证！")
        except Exception as e:
            QMessageBox.critical(self, "数据库错误", f"无法连接到 MySQL 数据库:\n{e}")


class SettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("️ 系统高级参数与飞书机器人设置")
        self.resize(600, 340)
        self.settings = current_settings.copy()
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.slider_angle = QSlider(Qt.Orientation.Horizontal)
        self.slider_angle.setRange(30, 70)
        self.slider_angle.setValue(self.settings.get("fall_threshold", 50))
        self.lbl_angle_val = QLabel(f"{self.slider_angle.value()} °")
        self.slider_angle.valueChanged.connect(lambda v: self.lbl_angle_val.setText(f"{v} °"))
        
        angle_layout = QHBoxLayout()
        angle_layout.addWidget(self.slider_angle)
        angle_layout.addWidget(self.lbl_angle_val)
        form_layout.addRow("跌倒倾斜角阈值:", angle_layout)

        self.chk_sound = QCheckBox("启用声音告警 (alarm.mp3)")
        self.chk_sound.setChecked(self.settings.get("sound_enabled", True))
        form_layout.addRow("声 音 告 警:", self.chk_sound)

        self.slider_buffer = QSlider(Qt.Orientation.Horizontal)
        self.slider_buffer.setRange(3, 20)
        self.slider_buffer.setValue(self.settings.get("buffer_seconds", 10))
        self.lbl_buffer_val = QLabel(f"{self.slider_buffer.value()} 秒")
        self.slider_buffer.valueChanged.connect(lambda v: self.lbl_buffer_val.setText(f"{v} 秒"))

        buffer_layout = QHBoxLayout()
        buffer_layout.addWidget(self.slider_buffer)
        buffer_layout.addWidget(self.lbl_buffer_val)
        form_layout.addRow("录制前置缓冲区:", buffer_layout)

        self.txt_webhook = QLineEdit()
        self.txt_webhook.setPlaceholderText("请输入飞书机器人 Webhook 链接")
        self.txt_webhook.setText("https://open.feishu.cn/open-apis/bot/v2/hook/e1d06cee-2c38-4679-962a-9fccb85fd766")
        self.txt_webhook.setReadOnly(True)  
        form_layout.addRow("飞书Webhook:", self.txt_webhook)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存配置")
        btn_save.clicked.connect(self.save_settings)
        btn_layout.addWidget(btn_save)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def save_settings(self):
        self.settings["fall_threshold"] = self.slider_angle.value()
        self.settings["sound_enabled"] = self.chk_sound.isChecked()
        self.settings["buffer_seconds"] = self.slider_buffer.value()
        self.settings["feishu_webhook"] = "https://open.feishu.cn/open-apis/bot/v2/hook/e1d06cee-2c38-4679-962a-9fccb85fd766"
        self.accept()


class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(" 历史跌倒告警记录与亲情处理中心")
        self.resize(1000, 560)

        self.save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result')
        os.makedirs(self.save_dir, exist_ok=True)

        self.cap = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

        self.initUI()
        self.load_logs_from_db()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        
        left_layout = QVBoxLayout()
        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self.on_file_selected)
        left_layout.addWidget(self.file_list, stretch=3)

        lbl_note = QLabel("️ 家属处理意见与备注:")
        lbl_note.setStyleSheet("font-weight: bold; color: #38BDF8; margin-top: 5px;")
        left_layout.addWidget(lbl_note)

        self.txt_note = QTextEdit()
        self.txt_note.setPlaceholderText("请输入处理说明，例如：已电话联系老人，确认系不小心绊倒，无大碍。")
        self.txt_note.setMaximumHeight(80)
        # 强制设置输入框内文字为清晰的黑色，背景为纯白
        self.txt_note.setStyleSheet("color: #000000; background-color: #FFFFFF; font-size: 13px; border-radius: 4px; padding: 4px;")
        left_layout.addWidget(self.txt_note)

        self.btn_resolve = QPushButton(" 提交处理结果并标记已解决")
        self.btn_resolve.setStyleSheet("background-color: #059669; color: #FFFFFF; font-weight: bold; padding: 8px;")
        self.btn_resolve.clicked.connect(self.mark_as_resolved)
        left_layout.addWidget(self.btn_resolve)

        btn_open = QPushButton(" 打开本地视频存档目录")
        btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.save_dir)))
        left_layout.addWidget(btn_open)

        main_layout.addLayout(left_layout, stretch=4)

        right_layout = QVBoxLayout()
        self.video_label = QLabel("请从左侧选择告警记录进行回放")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #020617; border-radius: 8px; color: #64748B;")
        right_layout.addWidget(self.video_label, stretch=1)

        main_layout.addLayout(right_layout, stretch=5)

    def mark_as_resolved(self):
        current_item = self.file_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先在左侧列表中选择一条告警记录！")
            return
            
        file_path = current_item.data(Qt.ItemDataRole.UserRole)
        filename = os.path.basename(file_path)
        note_text = self.txt_note.toPlainText().strip()
        status_str = f"已处理: {note_text}" if note_text else "已处理 (家属已确认)"
        
        try:
            db = pymysql.connect(
                host='localhost', user='root', password='231006410',
                database='fall_detector_db', charset='utf8mb4'
            )
            cursor = db.cursor()
            cursor.execute("UPDATE alarm_logs SET status = %s WHERE video_filename = %s;", (status_str, filename))
            db.commit()
            cursor.close()
            db.close()
            
            QMessageBox.information(self, "成功", "告警状态与家属处理意见已同步至数据库！")
            self.load_logs_from_db() 
        except Exception as e:
            QMessageBox.critical(self, "错误", f"更新数据库失败: {e}")

    def load_logs_from_db(self):
        self.file_list.clear()
        try:
            db = pymysql.connect(
                host='localhost', user='root', password='231006410',
                database='fall_detector_db', charset='utf8mb4'
            )
            cursor = db.cursor()
            cursor.execute("SELECT id, alarm_time, video_filename, status FROM alarm_logs ORDER BY id DESC;")
            records = cursor.fetchall()
            cursor.close()
            db.close()

            for row in records:
                log_id, alarm_time, filename, status = row
                file_path = os.path.join(self.save_dir, filename)
                
                if os.path.exists(file_path):
                    item_text = f"[{alarm_time}] {filename}\n状态: {status}"
                    item = QListWidgetItem(item_text)
                    item.setData(Qt.ItemDataRole.UserRole, file_path)
                    self.file_list.addItem(item)
                else:
                    try:
                        cleanup_db = pymysql.connect(
                            host='localhost', user='root', password='231006410',
                            database='fall_detector_db', charset='utf8mb4'
                        )
                        c = cleanup_db.cursor()
                        c.execute("DELETE FROM alarm_logs WHERE id = %s;", (log_id,))
                        cleanup_db.commit()
                        c.close()
                        cleanup_db.close()
                    except:
                        pass
        except Exception as e:
            print(f"从数据库读取历史失败: {e}")

    def on_file_selected(self, item):
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "文件缺失", f"在本地磁盘中未找到该视频文件:\n{file_path}")
            return

        if self.cap is not None:
            self.cap.release()

        self.cap = cv2.VideoCapture(file_path)
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        interval = int(1000 / fps) if fps > 0 else 33
        self.timer.start(interval)

    def update_frame(self):
        if self.cap is not None and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame_rgb.shape
                qt_img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(qt_img)
                self.video_label.setPixmap(
                    pixmap.scaled(self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
            else:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def closeEvent(self, event):
        self.timer.stop()
        if self.cap is not None:
            self.cap.release()
        event.accept()


class HealthDashboardDialog(QDialog):
    """️ 专属老人健康指标可视化大屏弹窗（与主界面尺寸相当，极具科技感与美观度）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(" 智能养老 - 老人健康指标可视化监控大屏")
        self.resize(1100, 650)
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # 1. 顶部标题与左上角开发注释说明
        top_frame = QFrame()
        top_frame.setStyleSheet("background-color: #1E293B; border-radius: 8px; border: 1px solid #334155;")
        top_layout = QVBoxLayout(top_frame)
        
        title_lbl = QLabel(" 老人实时健康体征与多维传感可视化大屏")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #38BDF8; border: none;")
        top_layout.addWidget(title_lbl)

        # 醒目的左上角注释说明
        note_lbl = QLabel("ℹ️ 开发注释说明：当前大屏展示的各项心率、血氧、血压及运动体征数据均为系统模拟生成。后期正式部署时，可通过 MQTT/TCP 协议无缝接入老人佩戴的智能手环、毫米波雷达等嵌入式物联网硬件设备进行实时数据采集。")
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("color: #94A3B8; font-size: 12px; border: none; line-height: 1.4;")
        top_layout.addWidget(note_lbl)
        
        main_layout.addWidget(top_frame)

        # 2. 中部核心卡片网格布局（2行3列）
        grid_layout = QGridLayout()
        grid_layout.setSpacing(15)

        # 卡片1：实时心率
        card_hr = self.create_metric_card("️ 实时心率 (Heart Rate)", "76 bpm", "状态: 正常平稳 (波形: ▂▃▅▆▇▆▅▃)", "#0284C7")
        grid_layout.addWidget(card_hr, 0, 0)

        # 卡片2：血氧饱和度
        card_spo2 = self.create_metric_card(" 血氧饱和度 (SpO2)", "98 %", "状态: 优良安全", "#059669")
        grid_layout.addWidget(card_spo2, 0, 1)

        # 卡片3：血压监测
        card_bp = self.create_metric_card(" 血压状况 (Blood Pressure)", "118 / 76 mmHg", "状态: 正常血压范围", "#7C3AED")
        grid_layout.addWidget(card_bp, 0, 2)

        # 卡片4：今日运动步数
        card_steps = self.create_metric_card(" 今日活动步数", "3,420 步", "目标达成率: 68% (活跃)", "#D97706")
        grid_layout.addWidget(card_steps, 1, 0)

        # 卡片5：体表温度
        card_temp = self.create_metric_card("️ 实时体表温度", "36.5 ℃", "状态: 无发热迹象", "#DC2626")
        grid_layout.addWidget(card_temp, 1, 1)

        # 卡片6：智能终端设备电量
        card_battery = self.create_metric_card(" 穿戴设备剩余电量", "92 %", "状态: 续航充足", "#2563EB")
        grid_layout.addWidget(card_battery, 1, 2)

        main_layout.addLayout(grid_layout)

        # 3. 底部操作区
        btn_layout = QHBoxLayout()
        btn_refresh = QPushButton(" 刷新最新体征数据")
        btn_refresh.setStyleSheet("background-color: #334155; color: #F8FAFC; font-weight: bold; padding: 10px 20px;")
        btn_refresh.clicked.connect(lambda: QMessageBox.information(self, "刷新成功", "已向嵌入式网关发送数据同步指令，当前体征已更新！"))
        btn_layout.addWidget(btn_refresh)

        btn_layout.addStretch()

        btn_close = QPushButton("关闭大屏")
        btn_close.setStyleSheet("background-color: #475569; color: #FFFFFF; font-weight: bold; padding: 10px 20px;")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        main_layout.addLayout(btn_layout)

    def create_metric_card(self, title, value, status, accent_color):
        card = QFrame()
        card.setStyleSheet(f"background-color: #1E293B; border-radius: 8px; border-left: 5px solid {accent_color}; border-top: 1px solid #334155; border-right: 1px solid #334155; border-bottom: 1px solid #334155;")
        layout = QVBoxLayout(card)
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #94A3B8; font-size: 13px; font-weight: bold; border: none;")
        layout.addWidget(lbl_title)

        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(f"color: {accent_color}; font-size: 26px; font-weight: bold; border: none; margin: 5px 0;")
        layout.addWidget(lbl_val)

        lbl_status = QLabel(status)
        lbl_status.setStyleSheet("color: #E2E8F0; font-size: 12px; border: none;")
        layout.addWidget(lbl_status)

        return card


# ==================== 情绪检测弹窗（独立摄像头） ====================

EMOTION_ADVICE_TEMPLATES = {
    "愤怒": [
        "建议先深呼吸三次，让心率慢慢平复。",
        "先离开引起情绪波动的环境，换个房间走走。",
        "可以倒一杯温水，慢慢喝，让身体先放松下来。",
    ],
    "厌恶": [
        "如果是对某件事的反感，可以尝试换个话题聊聊天。",
        "找一件喜欢的小事做，转移一下注意力。",
        "可以听一段舒缓的音乐，让心情恢复平静。",
    ],
    "恐惧": [
        "您现在是安全的，深呼吸会帮助您稳定下来。",
        "尝试和家人通个电话，让熟悉的声音陪伴您。",
        "握住身边一件柔软的物品（如毛毯），感受当下的安心。",
    ],
    "高兴": [
        "看到您精神这么好，真为您开心！",
        "可以和老朋友分享今天的好心情。",
        "保持这份愉悦，做一些轻松的伸展运动更好。",
    ],
    "悲伤": [
        "心情低落是正常的，允许自己先休息一下。",
        "可以听听喜欢的戏曲或老歌，熟悉的旋律能带来安慰。",
        "要不要和家人视频聊聊天？我们都在关心您。",
    ],
    "惊讶": [
        "不用紧张，慢慢整理一下刚才收到的信息。",
        "如果感到不适应，先坐下来喝口水。",
        "随时可以呼唤家属过来陪伴您。",
    ],
    "平静": [
        "您现在的状态很好，继续保持轻松的心情。",
        "适合做一些轻度的活动或读书看报。",
        "记得定时喝水，注意休息哦。",
    ],
}


def get_emotion_advice(emotion_cn):
    """根据情绪中文名给出本地建议（兜底用；正常流程由 _AdviceWorker 异步调用 AI 生成）。"""
    import random
    pool = EMOTION_ADVICE_TEMPLATES.get(emotion_cn, [
        "您现在的状态已被记录，建议多与家人沟通或拨打亲属号码。",
    ])
    return random.choice(pool)


def _build_advice_prompt(emotion_cn, dist=None):
    """给 LLM 的 prompt：让 AI 为老人生成定制关怀建议。"""
    dist_str = ""
    if dist:
        try:
            parts = [f"{k}:{round(v*100,1)}%" for k, v in sorted(dist.items(), key=lambda x: -x[1]) if v > 0.01]
            if parts:
                dist_str = f"（当前情绪分布：{'、'.join(parts)}）"
        except Exception:
            pass
    return (
        f"你是一位为老年人家属提供情绪陪伴建议的看护助手。"
        f"系统刚刚通过摄像头识别出老人当前主要情绪是「{emotion_cn}」{dist_str}。"
        f"请用 80~120 字、温柔可执行的口吻，给出 2~3 条具体关怀建议。"
        f"语气像晚辈关心长辈，避免专业术语，必要时提醒联系家属或医生。"
    )


class EmotionDetectionDialog(QDialog):
    """基于 YOLOv11 的人脸情绪识别弹窗。"""
    _tts_finished_signal = pyqtSignal(int)
    _last_emotion_cn = None  # 跨实例共享，供 AI 对话读取视觉情绪

    def __init__(self, parent=None, model_path=None, source=0):
        super().__init__(parent)
        self.setWindowTitle(" 老人情绪识别与分析中心")
        self.resize(1100, 680)

        self.model_path = model_path
        self.source = source
        self.thread = None
        self._current_emotion = "--"
        self._current_conf = 0.0
        self._current_dist = {}
        self._advice_worker = None
        self._advice_workers = set()
        self._tts_engine = None
        self._tts_lock = threading.Lock()
        self._tts_cancel_event = threading.Event()
        self._tts_pending = False
        self._pipeline_active = False
        self._pipeline_stop = False
        self._pipeline_current_emo = None
        self._diagnosis_id = 0
        self._diagnosis_snapshot = None
        self._current_frame = None
        self._last_polled_frame_id = 0
        self._tts_finished_signal.connect(self._on_tts_finished)

        self.initUI()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(14)

        # ============ 左侧：视频流与控制 ============
        left_layout = QVBoxLayout()

        header_lbl = QLabel(" 实时人脸情绪检测 (YOLOv11)")
        header_lbl.setStyleSheet("color: #38BDF8; font-size: 14px; font-weight: bold; border: none;")
        left_layout.addWidget(header_lbl)

        self.video_label = QLabel("请点击「启动情绪检测」开始", self)
        self.video_label.setMinimumSize(640, 360)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #020617; border-radius: 8px; color: #64748B; font-size: 13px;")
        left_layout.addWidget(self.video_label)

        ctrl_layout = QHBoxLayout()

        self.btn_pick_model = QPushButton(" 选择模型 (best.onnx)")
        self.btn_pick_model.clicked.connect(self.pick_model)
        ctrl_layout.addWidget(self.btn_pick_model)

        self.btn_pick_source = QToolButton()
        self.btn_pick_source.setText(" 切换视频源 ▾")
        self.btn_pick_source.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_pick_source.setStyleSheet(
            "QToolButton{background-color:#3B82F6;color:#FFFFFF;font-weight:bold;padding:8px 14px;"
            "border:1px solid #2563EB;border-radius:6px;}"
            "QToolButton::menu-indicator{image:none;width:0;}"
            "QToolButton:hover{background-color:#2563EB;}"
        )
        self.btn_pick_source.setFixedHeight(34)
        self._source_menu = QMenu(self.btn_pick_source)
        self._source_menu.setStyleSheet(
            "QMenu{background-color:#1E293B;border:1px solid #334155;border-radius:8px;padding:6px;}"
            "QMenu::item{padding:6px 18px;color:#F8FAFC;font-size:14px;border-radius:4px;}"
            "QMenu::item:selected{background-color:#3B82F6;color:#FFFFFF;}"
            "QMenu::item:disabled{color:#94A3B8;font-weight:bold;background-color:transparent;padding-top:10px;padding-bottom:2px;}"
            "QMenu::separator{height:1px;background:#334155;margin:4px 6px;}"
        )
        self.btn_pick_source.setMenu(self._source_menu)
        self._source_menu.aboutToShow.connect(self._refresh_source_menu)
        ctrl_layout.addWidget(self.btn_pick_source)

        self.btn_start = QPushButton("▶ 启动情绪检测")
        self.btn_start.setStyleSheet("background-color: #10B981; color: #FFFFFF; font-weight: bold; padding: 8px;")
        self.btn_start.clicked.connect(self.start_detection)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton(" 停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("background-color: #DC2626; color: #FFFFFF; font-weight: bold; padding: 8px;")
        self.btn_stop.clicked.connect(self.stop_detection)
        ctrl_layout.addWidget(self.btn_stop)

        self.chk_tts = QCheckBox("🔊 语音朗读建议")
        self.chk_tts.setChecked(True)
        self.chk_tts.setStyleSheet("color:#F8FAFC; font-size:13px; padding:0 6px;")
        self.chk_tts.setToolTip("点击 AI 诊断后，自动用 TTS 朗读生成的关怀建议")
        ctrl_layout.addWidget(self.chk_tts)

        self.lbl_pipeline = QLabel("")
        self.lbl_pipeline.setStyleSheet("color:#FBBF24; font-size:12px; padding-left:8px;")
        ctrl_layout.addWidget(self.lbl_pipeline, stretch=1)

        left_layout.addLayout(ctrl_layout)

        # 日志
        self.log_list = QListWidget()
        self.log_list.setMaximumHeight(120)
        self.log_list.setStyleSheet("background-color: #0F172A; border: 1px solid #334155; border-radius: 6px; color: #CBD5E1; font-size: 12px; padding: 4px;")
        left_layout.addWidget(self.log_list)

        main_layout.addLayout(left_layout, stretch=6)

        # ============ 右侧：情绪指标与建议 ============
        right_layout = QVBoxLayout()

        cur_card = QFrame()
        cur_card.setStyleSheet("background-color: #1E293B; border-radius: 8px; border-left: 5px solid #38BDF8;")
        cur_layout = QVBoxLayout(cur_card)
        cur_layout.setContentsMargins(14, 14, 14, 14)

        cur_title = QLabel(" 当前情绪")
        cur_title.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold; border: none;")
        cur_layout.addWidget(cur_title)

        self.lbl_current_emotion = QLabel("--")
        self.lbl_current_emotion.setStyleSheet("color: #38BDF8; font-size: 30px; font-weight: bold; border: none; margin: 4px 0;")
        self.lbl_current_emotion.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cur_layout.addWidget(self.lbl_current_emotion)

        self.lbl_current_conf = QLabel("置信度: --")
        self.lbl_current_conf.setStyleSheet("color: #E2E8F0; font-size: 12px; border: none;")
        self.lbl_current_conf.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cur_layout.addWidget(self.lbl_current_conf)

        right_layout.addWidget(cur_card)

        dist_title = QLabel(" 7 类情绪占比 (本时段)")
        dist_title.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold;")
        right_layout.addWidget(dist_title)

        self.dist_widget = QFrame()
        self.dist_widget.setStyleSheet("background-color: #1E293B; border-radius: 8px; border: 1px solid #334155;")
        self.dist_layout = QVBoxLayout(self.dist_widget)
        self.dist_layout.setContentsMargins(10, 10, 10, 10)
        self.dist_layout.setSpacing(4)
        self._init_dist_rows()
        right_layout.addWidget(self.dist_widget)

        advice_title = QLabel(" AI 表情诊断与关怀建议（手动触发）")
        advice_title.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold;")
        right_layout.addWidget(advice_title)

        self.txt_advice = QTextEdit()
        self.txt_advice.setReadOnly(True)
        self.txt_advice.setStyleSheet("background-color: #1E293B; border: 1px solid #334155; border-radius: 8px; color: #F8FAFC; font-size: 13px; padding: 8px;")
        self.txt_advice.setPlaceholderText("启动检测后，点击「AI 诊断」分析当前时刻的表情……")
        right_layout.addWidget(self.txt_advice, stretch=1)

        diagnosis_controls = QHBoxLayout()
        self.btn_ai_diagnose = QPushButton("AI 诊断")
        self.btn_ai_diagnose.setEnabled(False)
        self.btn_ai_diagnose.setStyleSheet(
            "QPushButton{background-color:#7C3AED;color:#FFFFFF;font-weight:bold;padding:8px;}"
            "QPushButton:hover{background-color:#6D28D9;}"
            "QPushButton:disabled{background-color:#475569;color:#94A3B8;}"
        )
        self.btn_ai_diagnose.setToolTip("截取当前时刻已识别的表情和分布，生成 AI 关怀建议")
        self.btn_ai_diagnose.clicked.connect(self.start_ai_diagnosis)
        diagnosis_controls.addWidget(self.btn_ai_diagnose)

        self.btn_cancel_diagnosis = QPushButton("终止诊断")
        self.btn_cancel_diagnosis.setEnabled(False)
        self.btn_cancel_diagnosis.setStyleSheet(
            "QPushButton{background-color:#DC2626;color:#FFFFFF;font-weight:bold;padding:8px;}"
            "QPushButton:hover{background-color:#B91C1C;}"
            "QPushButton:disabled{background-color:#475569;color:#94A3B8;}"
        )
        self.btn_cancel_diagnosis.setToolTip("终止当前 AI 分析或语音播报，视频检测不受影响")
        self.btn_cancel_diagnosis.clicked.connect(
            lambda _checked=False: self.cancel_ai_diagnosis(show_message=True)
        )
        diagnosis_controls.addWidget(self.btn_cancel_diagnosis)
        right_layout.addLayout(diagnosis_controls)

        btn_close = QPushButton("关闭情绪识别")
        btn_close.clicked.connect(self.close)
        right_layout.addWidget(btn_close)

        main_layout.addLayout(right_layout, stretch=4)

        self._update_info("请选择情绪识别模型 (.onnx) 后启动检测。")

    def _init_dist_rows(self, ordered=None):
        """初始化情绪分布行 (名称 + 进度条 + 百分比)。"""
        if ordered is None:
            ordered = ["高兴", "平静", "悲伤", "愤怒", "惊讶", "恐惧", "厌恶"]
        from PyQt6.QtWidgets import QProgressBar
        self._dist_rows = {}
        self._dist_order = list(ordered)
        self._build_dist_rows()

    def _build_dist_rows(self):
        """根据 self._dist_order 重建分布行。"""
        from PyQt6.QtWidgets import QProgressBar
        if self.dist_layout is None:
            return
        while self.dist_layout.count():
            item = self.dist_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._dist_rows = {}
        for emo in self._dist_order:
            row = QFrame()
            row.setStyleSheet("background: transparent; border: none;")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 2, 0, 2)
            lbl = QLabel(emo)
            lbl.setFixedWidth(60)
            lbl.setStyleSheet("color: #CBD5E1; font-size: 12px; border: none;")
            pb = QProgressBar()
            pb.setRange(0, 100)
            pb.setValue(0)
            pb.setTextVisible(False)
            pb.setFixedHeight(8)
            pb.setStyleSheet("""
                QProgressBar { background-color: #0F172A; border: 1px solid #334155; border-radius: 4px; }
                QProgressBar::chunk { background-color: #38BDF8; border-radius: 4px; }
            """)
            pct = QLabel("0%")
            pct.setFixedWidth(40)
            pct.setAlignment(Qt.AlignmentFlag.AlignRight)
            pct.setStyleSheet("color: #94A3B8; font-size: 11px; border: none;")
            h.addWidget(lbl)
            h.addWidget(pb)
            h.addWidget(pct)
            self.dist_layout.addWidget(row)
            self._dist_rows[emo] = (pb, pct)

    def pick_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择情绪识别模型", "", "ONNX Model (*.onnx);;All Files (*)")
        if path:
            self.model_path = path
            self._update_info(f"已选择模型: {os.path.basename(path)}")

    def _refresh_source_menu(self):
        """每次展开下拉时重建菜单项，动态枚举摄像头。"""
        m = self._source_menu
        m.clear()
        title = m.addAction("▣ 摄像头 (实时流)")
        title.setEnabled(False)
        try:
            from main import enumerate_cameras
            cams = enumerate_cameras(max_index=4)
            if not cams:
                a = m.addAction("  未检测到可用摄像头")
                a.setEnabled(False)
            else:
                for label, idx, info in cams:
                    hint = f"  [{info['w']}x{info['h']}]" if info.get('w') and info.get('h') else ""
                    act = m.addAction(f"  {label}{hint}")
                    act.triggered.connect(lambda checked=False, i=idx: self._set_source(i, f"摄像头 {i}"))
        except Exception as e:
            m.addAction(f"  摄像头枚举失败: {e}")

        m.addSeparator()
        cur = m.addAction(f"当前: {self._describe_source()}")
        cur.setEnabled(False)

    def _describe_source(self):
        s = self.source
        if isinstance(s, int):
            return f"摄像头 {s}"
        if isinstance(s, str) and s.isdigit():
            return f"摄像头 {s}"
        if isinstance(s, str):
            return os.path.basename(s) or s
        return str(s)

    def _set_source(self, source, label):
        self.source = source
        self._update_info(f"情绪检测视频源已切换: {label}")
        try:
            if self.thread is not None and self.thread.isRunning():
                self.stop_detection()
                self.start_detection()
        except Exception:
            pass

    def start_detection(self):
        if not self.model_path or not os.path.exists(self.model_path):
            QMessageBox.warning(self, "模型未选择", "请先点击「选择模型」加载 best.onnx 模型文件。")
            return
        if self.thread is not None and self.thread.isRunning():
            return

        self._pipeline_stop = False
        self._pipeline_active = False
        self._diagnosis_snapshot = None
        self._last_polled_frame_id = 0
        self.lbl_pipeline.setText("检测运行中，请在需要时点击 AI 诊断")

        from detector import EmotionDetectionThread
        self.thread = EmotionDetectionThread(model_path=self.model_path, source=self.source)
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.log_signal.connect(self._update_info)
        self.thread.finished.connect(self._on_thread_finished)
        self.thread.start()

        # 关键修复：主线程 QTimer 轮询子线程最新帧，绕开跨线程 numpy emit 导致的卡死
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(33)  # 约 30fps
        self._poll_timer.timeout.connect(self._poll_latest_frame)
        self._poll_timer.start()

        QTimer.singleShot(2500, self._resync_dist_rows_from_thread)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_pick_model.setEnabled(False)
        self.btn_pick_source.setEnabled(False)
        self.btn_ai_diagnose.setEnabled(False)
        self.btn_cancel_diagnosis.setEnabled(False)

    def _resync_dist_rows_from_thread(self):
        """从线程读取真实类别顺序，重建分布行。"""
        try:
            if self.thread is None:
                return
            names = self.thread.get_class_names()
            if not names:
                return
            if list(names) != getattr(self, "_dist_order", None):
                self._dist_order = list(names)
                self._build_dist_rows()
                self._update_info(f"已根据模型同步分布面板，共 {len(names)} 类: {', '.join(names)}")
        except Exception as e:
            self._update_info(f"同步分布行失败: {e}")

    def _on_thread_finished(self):
        try:
            if getattr(self, "_poll_timer", None) is not None:
                self._poll_timer.stop()
                self._poll_timer = None
        except Exception:
            pass
        self.thread = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pick_model.setEnabled(True)
        self.btn_pick_source.setEnabled(True)
        self.btn_ai_diagnose.setEnabled(False)
        self.btn_cancel_diagnosis.setEnabled(False)
        self._update_info("情绪检测已停止。")

    def stop_detection(self):
        self.cancel_ai_diagnosis(show_message=False)
        self._pipeline_stop = True
        self.lbl_pipeline.setText("情绪检测已停止")
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop()

    def _poll_latest_frame(self):
        """主线程 QTimer 轮询子线程最新帧，绕开跨线程 numpy emit 卡死。"""
        try:
            t = self.thread
            if t is None:
                return
            with t._frame_lock:
                frame_id = getattr(t, "_latest_frame_id", 0)
                if frame_id == self._last_polled_frame_id:
                    return
                frame = t._latest_frame
                emo, conf, dist = t._latest_payload
            if frame is None:
                return
            self._last_polled_frame_id = frame_id
            self.update_image(frame, emo, conf, dist)
        except Exception as e:
            self._update_info(f"读取情绪视频帧异常: {e}")

    def update_image(self, cv_img, emotion_cn, conf, dist):
        try:
            if cv_img is None:
                self._update_info("情绪视频帧为空")
                return
            if not isinstance(cv_img, np.ndarray):
                cv_img = np.asarray(cv_img)
            if cv_img.ndim == 2:
                cv_img = cv2.cvtColor(cv_img, cv2.COLOR_GRAY2BGR)
            rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            # 关键：必须先 contiguious + tobytes()，避免跨线程 ndarray.data 指针失效导致 PyQt 渲染卡死
            if not rgb_image.flags['C_CONTIGUOUS']:
                rgb_image = np.ascontiguousarray(rgb_image)
            img_bytes = rgb_image.tobytes()
            bytes_per_line = ch * w
            qt_img = QImage(img_bytes, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(qt_img)
            self.video_label.setPixmap(
                pixmap.scaled(self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            # 强制重绘
            self.video_label.update()

            self._current_emotion = emotion_cn
            self._current_conf = float(conf) if conf is not None else 0.0
            self._current_dist = dict(dist or {})
            self._current_frame = cv_img.copy()
            EmotionDetectionDialog._last_emotion_cn = self._current_emotion

            self.lbl_current_emotion.setText(emotion_cn if emotion_cn and emotion_cn != "--" else "--")
            self.lbl_current_conf.setText(
                f"置信度: {self._current_conf*100:.1f}%" if self._current_conf > 0 else "置信度: --"
            )

            for emo, (pb, pct) in self._dist_rows.items():
                v = self._current_dist.get(emo, 0.0)
                try:
                    pct_val = int(round(float(v) * 100))
                except Exception:
                    pct_val = 0
                pb.setValue(max(0, min(100, pct_val)))
                pct.setText(f"{pct_val}%")

            can_diagnose = (
                self.thread is not None
                and self.thread.isRunning()
                and bool(emotion_cn)
                and emotion_cn != "--"
                and self._current_conf > 0
                and not self._pipeline_active
            )
            self.btn_ai_diagnose.setEnabled(can_diagnose)
        except Exception as e:
            self._update_info(f"画面更新异常: {e}")

    def start_ai_diagnosis(self):
        """截取点击瞬间的识别结果，手动启动一次 AI 诊断。"""
        if self._pipeline_active:
            return
        if self.thread is None or not self.thread.isRunning():
            QMessageBox.information(self, "无法诊断", "请先启动情绪检测。")
            return
        emotion = self._current_emotion
        confidence = self._current_conf
        if not emotion or emotion == "--" or confidence <= 0:
            QMessageBox.information(self, "暂无表情", "当前画面还没有有效的表情识别结果，请稍后再试。")
            return

        self._diagnosis_id += 1
        diagnosis_id = self._diagnosis_id
        self._diagnosis_snapshot = {
            "id": diagnosis_id,
            "emotion": emotion,
            "confidence": confidence,
            "dist": dict(self._current_dist or {}),
            "frame": self._current_frame.copy() if isinstance(self._current_frame, np.ndarray) else None,
        }
        self._pipeline_stop = False
        self._pipeline_active = True
        self._pipeline_current_emo = emotion
        self.btn_ai_diagnose.setEnabled(False)
        self.btn_cancel_diagnosis.setEnabled(True)
        self.lbl_pipeline.setText(f"已截取当前表情「{emotion}」，AI 正在分析…")
        self.txt_advice.setPlainText(
            f"正在诊断点击时刻的表情：{emotion}（置信度 {confidence * 100:.1f}%）…"
        )
        self._update_info(f"已手动截取表情「{emotion}」，开始第 {diagnosis_id} 次 AI 诊断")

        worker = _AdviceWorker(
            emotion_cn=emotion,
            dist=dict(self._diagnosis_snapshot["dist"]),
        )
        self._advice_workers.add(worker)
        self._advice_worker = worker
        worker.done_signal.connect(
            lambda text, did=diagnosis_id, w=worker: self._on_advice_done(did, w, text)
        )
        worker.finished.connect(lambda w=worker: self._on_advice_finished(w))
        worker.start()

    def cancel_ai_diagnosis(self, show_message=True):
        """终止当前诊断状态和播报；尚未返回的网络结果将被安全丢弃。

        关键约束：主线程绝不能直接调 pyttsx3 engine 的任何方法。
        pyttsx3 在 sapi5 上是 apartment-threaded 的 COM 对象，
        在 worker 线程里 init 后如果主线程再去 touch 它的方法，
        会触发跨 apartment 调用 COM marshalling，导致主线程死锁（UI 卡死）。

        所以这里只：
          1. 把 _pipeline_stop 置 True —— worker 自己轮询这个标志做软退出。
          2. 把 _tts_cancel_event 也 set 上 —— 兼容旧路径。
          3. 不动 engine 对象。等 worker 自己退出后，下次 _ensure_tts() 会重建。
          4. 取消在跑的 _AdviceWorker（仅 requestInterruption，不 wait，不锁主线程）。
        """
        was_active = self._pipeline_active or self._tts_pending
        self._diagnosis_id += 1
        self._pipeline_stop = True
        self._pipeline_active = False
        self._pipeline_current_emo = None
        self._diagnosis_snapshot = None
        self._tts_pending = False

        try:
            self._tts_cancel_event.set()
        except Exception:
            pass

        # 取消正在跑的 AI 生成线程（如果有）—— 不 wait，不锁主线程
        try:
            w = getattr(self, "_advice_worker", None)
            if w is not None and w.isRunning():
                try:
                    w.requestInterruption()
                except Exception:
                    pass
        except Exception:
            pass

        # 注意：刻意不动 self._tts_engine。
        # worker 线程会在 _pipeline_stop == True 后自然停掉 engine 并自己清理。
        # 这样不会触发跨线程 COM 调用，避免 UI 死锁。

        self.btn_cancel_diagnosis.setEnabled(False)
        self.btn_ai_diagnose.setEnabled(
            self.thread is not None
            and self.thread.isRunning()
            and bool(self._current_emotion)
            and self._current_emotion != "--"
            and self._current_conf > 0
        )
        if show_message:
            self.lbl_pipeline.setText("当前 AI 诊断或播报已终止，视频检测继续运行")
            self._update_info("用户已终止当前 AI 诊断或语音播报")
            if was_active:
                self.txt_advice.setPlainText("本次 AI 诊断已终止。可随时点击「AI 诊断」重新分析当前表情。")

    def _on_advice_done(self, diagnosis_id, worker, text):
        """仅接收当前手动诊断会话的结果，终止后的迟到结果会被忽略。"""
        if (
            diagnosis_id != self._diagnosis_id
            or not self._pipeline_active
            or self._pipeline_stop
            or worker is not self._advice_worker
        ):
            return
        if not text:
            # AI 线程被中断 / 跳过；走正常结束路径，避免朗读空文本
            self._finish_ai_diagnosis(diagnosis_id, "本次 AI 诊断已取消")
            return
        self.txt_advice.setPlainText(text)
        if self.chk_tts.isChecked():
            self.lbl_pipeline.setText(f"正在朗读「{self._pipeline_current_emo}」的诊断建议…")
            self._speak_async(text, diagnosis_id)
        else:
            self._finish_ai_diagnosis(diagnosis_id, "AI 诊断完成（语音朗读已关闭）")

    def _on_advice_finished(self, worker):
        self._advice_workers.discard(worker)
        if worker is self._advice_worker:
            self._advice_worker = None

    def _speak_async(self, text, diagnosis_id):
        """在子线程朗读；支持安全打断。

        关键约束：pyttsx3 的 sapi5 backend 是 apartment-threaded COM，
        engine 必须只在创建它的线程里被调用。因此：
          - cancel 只置 _pipeline_stop / _tts_cancel_event，主线程不碰 engine。
          - 本 worker 线程自己 init / use / destroy engine。
          - 每次朗读都是全新的 engine；用完立刻 stop + endLoop + del，
            否则 sapi5 第二次 reuse 同一个 engine 会哑火。
          - 文本拆成短句逐句 say + runAndWait，每句之间检测取消，命中立刻 stop()
            并 break；这样 reader 能在 50~150ms 内收声，不会再卡死。

        注意：self._tts_engine 在 cancel 后**不**置 None，避免和 worker 产生竞态；
        引擎的 stop() 由 worker 自己调，endLoop() 由 worker 自己调（如果进入过）。
        """
        self._tts_pending = True
        cancel_event = threading.Event()
        self._tts_cancel_event = cancel_event

        def _split_sentences(s):
            """按中英文标点切短句，保证每段 <= 60 字。"""
            import re
            if not s:
                return []
            pieces = re.split(r"(?<=[。！？!?；;])\s*", s)
            out = []
            buf = ""
            for p in pieces:
                if not p:
                    continue
                buf += p
                if len(buf) >= 40 or p[-1] in "。！？!?；;,，":
                    out.append(buf.strip())
                    buf = ""
            if buf.strip():
                out.append(buf.strip())
            return [x for x in out if x]

        def _interruptible_wait(eng):
            """用 startLoop+iterate 替代 runAndWait：
            句间轮询取消标志 → 命中立刻 engine.stop()，50~150ms 内收声。
            """
            try:
                eng.startLoop(False)
                while eng.isBusy():
                    if self._pipeline_stop or cancel_event.is_set() or \
                            diagnosis_id != self._diagnosis_id:
                        try:
                            eng.stop()
                        except Exception:
                            pass
                        break
                    eng.iterate()
                eng.endLoop()
            except Exception:
                # 兜底：用 runAndWait（可能挂住直到当前句结束，但比静默好）
                try:
                    eng.runAndWait()
                except Exception:
                    pass

        def _run():
            import pyttsx3
            engine = None
            try:
                if self._pipeline_stop or diagnosis_id != self._diagnosis_id:
                    return
                # 每次朗读都 init 一个全新的 engine；sapi5 不重用 engine 才能稳定出声
                try:
                    engine = pyttsx3.init(driverName='sapi5' if os.name == 'nt' else None)
                except Exception as e:
                    try:
                        self.lbl_pipeline.setText(f"⚠ TTS 引擎初始化失败（朗读已跳过）: {e}")
                    except Exception:
                        pass
                    return
                try:
                    engine.setProperty('rate', 165)
                    engine.setProperty('volume', 0.9)
                    # 优先选中文音色；没有 fallback 到默认音色
                    try:
                        voices = engine.getProperty('voices') or []
                        for v in voices:
                            desc = (getattr(v, 'id', '') + ' ' + getattr(v, 'name', '')).lower()
                            if 'chinese' in desc or 'zh' in desc or 'mandarin' in desc:
                                engine.setProperty('voice', v.id)
                                break
                    except Exception:
                        pass
                except Exception:
                    pass

                clean = self._clean_for_tts(text)
                sentences = _split_sentences(clean)
                if not sentences:
                    return

                # 逐句朗读，每句之间轮询取消标志。
                # 关键：使用 _interruptible_wait() 替代 runAndWait()，
                # 这样 stop 命中后能 50~150ms 内收声。
                for i, sent in enumerate(sentences):
                    # 取锁前先看取消标志，避免拿锁时主线程 cancel 永远进不来
                    if self._pipeline_stop or cancel_event.is_set() or \
                            diagnosis_id != self._diagnosis_id:
                        try:
                            engine.stop()
                        except Exception:
                            pass
                        return
                    try:
                        engine.say(sent)
                        _interruptible_wait(engine)
                    except Exception:
                        # 比如引擎被另一条 cancel 流程释放了；安全退出
                        return

                    # 句间检测取消，发现要停时立刻 stop 当次语音
                    if self._pipeline_stop or cancel_event.is_set() or \
                            diagnosis_id != self._diagnosis_id:
                        try:
                            engine.stop()
                        except Exception:
                            pass
                        return
            finally:
                # 用完立刻销毁 engine：sapi5 不支持重用，下次必须重建。
                # 否则下次朗读会哑火（这是“第一次能朗读，第二次无声”的根因）。
                try:
                    if engine is not None:
                        try:
                            engine.stop()
                        except Exception:
                            pass
                        try:
                            engine.endLoop()
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    self._tts_finished_signal.emit(diagnosis_id)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    def _on_tts_finished(self, diagnosis_id):
        if diagnosis_id != self._diagnosis_id:
            return
        self._tts_pending = False
        if self._pipeline_stop or not self._pipeline_active:
            return
        self._finish_ai_diagnosis(diagnosis_id, "AI 诊断与语音播报完成")

    def _finish_ai_diagnosis(self, diagnosis_id, status_text):
        if diagnosis_id != self._diagnosis_id:
            return
        self._pipeline_active = False
        self._pipeline_current_emo = None
        self.btn_cancel_diagnosis.setEnabled(False)
        self.btn_ai_diagnose.setEnabled(
            self.thread is not None
            and self.thread.isRunning()
            and bool(self._current_emotion)
            and self._current_emotion != "--"
            and self._current_conf > 0
        )
        self.lbl_pipeline.setText(status_text)
        self._update_info(status_text)

    def _ensure_tts(self):
        if self._tts_engine is not None:
            return
        try:
            import pyttsx3
            engine = pyttsx3.init(driverName='sapi5' if os.name == 'nt' else None)
            try:
                engine.setProperty('rate', 165)
                engine.setProperty('volume', 0.9)
                # 优先选中文音色；没有中文音色也不报错（兼容英文 fallback）
                try:
                    voices = engine.getProperty('voices') or []
                    for v in voices:
                        desc = (getattr(v, 'id', '') + ' ' + getattr(v, 'name', '')).lower()
                        if 'chinese' in desc or 'zh' in desc or 'mandarin' in desc:
                            engine.setProperty('voice', v.id)
                            break
                except Exception:
                    pass
            except Exception:
                pass
            self._tts_engine = engine
        except Exception as e:
            self._tts_engine = None
            # 给 UI 一个明确提示：TTS 不可用，朗读会被跳过
            try:
                self.lbl_pipeline.setText(f"⚠ TTS 引擎初始化失败（朗读已跳过）: {e}")
            except Exception:
                pass
            try:
                self.error_signal.emit(f"TTS 不可用: {e}")
            except Exception:
                pass

    @staticmethod
    def _clean_for_tts(text):
        if not text:
            return ""
        text = text.replace("\n", "。").replace("\r", "。")
        import re
        text = re.sub(r"[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffefa-zA-Z0-9，。！？、；：,.!?;:]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _update_info(self, text):
        from PyQt6.QtCore import QDateTime
        time_str = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.log_list.addItem(QListWidgetItem(f"[{time_str}] {text}"))
        self.log_list.scrollToBottom()

    def closeEvent(self, event):
        self.cancel_ai_diagnosis(show_message=False)
        self.stop_detection()
        event.accept()


# ==================== Kimi AI 异步调用线程 ====================

class _KimiAskWorker(QThread):
    """在线程里调用 Kimi / Ollama / 本地规则，避免阻塞 UI。"""
    done_signal = pyqtSignal(str)

    def __init__(self, question, history=None, visual_emotion_cn=None,
                 text_emotion_cn=None, text_score=0.0, model_mode="kimi"):
        super().__init__()
        self.question = question
        self.history = history or []
        self.visual_emotion_cn = visual_emotion_cn
        self.text_emotion_cn = text_emotion_cn
        self.text_score = text_score
        self.model_mode = model_mode

    def run(self):
        try:
            answer = answer_question(
                self.question,
                history=self.history,
                visual_emotion_cn=self.visual_emotion_cn,
                text_emotion_cn=self.text_emotion_cn,
                text_score=self.text_score,
                model_mode=self.model_mode,
            )
        except Exception as e:
            answer = f"AI 调用失败：{e}"
        self.done_signal.emit(answer)


class _AdviceWorker(QThread):
    """异步生成情绪关怀建议：调 Kimi 大模型，无 Key 时回退本地模板。"""
    done_signal = pyqtSignal(str)

    def __init__(self, emotion_cn, dist=None):
        super().__init__()
        self.emotion_cn = emotion_cn
        self.dist = dist or {}

    def run(self):
        try:
            if self.isInterruptionRequested():
                self.done_signal.emit("")
                return
            prompt = _build_advice_prompt(self.emotion_cn, self.dist)
            if self.isInterruptionRequested():
                self.done_signal.emit("")
                return
            reply = _kimi_chat([{"role": "user", "content": prompt}])
            if reply and reply.strip():
                self.done_signal.emit(reply.strip())
                return
        except Exception:
            pass
        # 即使用模板也检查一次取消，避免文本仍然被写回 UI
        if self.isInterruptionRequested():
            self.done_signal.emit("")
            return
        self.done_signal.emit(get_emotion_advice(self.emotion_cn))


class _TTSWorker(QThread):
    """用 pyttsx3 离线朗读（不阻塞 UI）；支持运行时安全中断。

    关键设计：每次 run() 内是一次性 init → 用 → 销毁。
    SAPI5 后端不支持 engine 复用（reuse 后会哑火或 runAndWait 卡死），
    所以本 worker 自身拥有完整 engine 生命周期，绝不与别的 worker 共享。
    """
    status_signal = pyqtSignal(str)

    def __init__(self, text):
        super().__init__()
        self._text = text
        self._stop_flag = False
        self._engine = None

    def stop(self):
        """仅设置停止标记；不要在主线程里碰 pyttsx3 engine —— 跨线程 COM 调用
        会和 worker 线程上的 startLoop/iterate 死锁（sapi5 apartment-threaded）。"""
        self._stop_flag = True

    def _interruptible_wait(self, engine):
        """用 startLoop+iterate 替代 runAndWait。
        这样 stop_flag 翻转后，下一次 iterate() 会立即看到 stop，runAndWait 则会卡死。
        """
        try:
            engine.startLoop(False)
            while engine.isBusy():
                if self._stop_flag:
                    engine.stop()
                    break
                engine.iterate()
            engine.endLoop()
        except Exception:
            # 退化为同步 runAndWait（兼容性兜底）
            try:
                engine.runAndWait()
            except Exception:
                pass

    def run(self):
        text = self._text
        if not text:
            return
        import re
        engine = None
        try:
            import pyttsx3
            # 1) 每次 run() init 一个新 engine；sapi5 不重用 engine
            engine = pyttsx3.init(driverName='sapi5' if os.name == 'nt' else None)
            self._engine = engine
            try:
                # 优先选中文音色；找不到就 fallback 到默认
                voices = engine.getProperty("voices") or []
                for v in voices:
                    name = (getattr(v, "name", "") or "").lower()
                    vid = (getattr(v, "id", "") or "").lower()
                    if "chinese" in name or "zh" in name or "中文" in name or "mandarin" in name \
                            or "zh-cn" in vid or "chinese" in vid:
                        engine.setProperty("voice", v.id)
                        break
            except Exception:
                pass
            engine.setProperty("rate", 165)
            engine.setProperty("volume", 1.0)

            # 2) 清理文本：把换行统一成句号、压缩多余空白
            clean = text
            try:
                clean = re.sub(r"\s+", " ", clean.replace("\n", "。")).strip()
            except Exception:
                pass
            if not clean:
                return

            # 3) 取消检查
            if self._stop_flag:
                return

            self.status_signal.emit("正在朗读…")

            # 4) 拆短句，按句 say + 可中断 wait。
            #    每句话之间轮询 stop_flag → 命中即 engine.stop() 立刻收声。
            #    整段仍是一次 init 一次 engine，没有"复用 engine 哑火"问题。
            sentences = re.split(r"(?<=[。！？!?；;])\s*", clean)
            sentences = [s.strip() for s in sentences if s and s.strip()]
            if not sentences:
                # 没有可拆句的标点：整段一次性 say + 可中断 wait
                try:
                    engine.say(clean)
                except Exception:
                    pass
                self._interruptible_wait(engine)
            else:
                for sent in sentences:
                    if self._stop_flag:
                        try:
                            engine.stop()
                        except Exception:
                            pass
                        break
                    try:
                        engine.say(sent)
                    except Exception:
                        break
                    self._interruptible_wait(engine)
                    if self._stop_flag:
                        try:
                            engine.stop()
                        except Exception:
                            pass
                        break

            # 5) 句尾再确认一次取消状态
            if self._stop_flag:
                try:
                    engine.stop()
                except Exception:
                    pass
        except Exception as e:
            try:
                self.status_signal.emit(f"TTS 不可用: {e}")
            except Exception:
                pass
        finally:
            # 6) 完整销毁本 worker 的 engine：sapi5 必须这样，否则下次 init 会失败
            try:
                if engine is not None:
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    try:
                        engine.endLoop()
                    except Exception:
                        pass
                    del engine
            except Exception:
                pass
            self._engine = None
            if self._stop_flag:
                self.status_signal.emit("朗读已停止")
            else:
                self.status_signal.emit("朗读结束")


# ==================== AI 智能问答弹窗（语音 + 打字） ====================

class _VoiceRecognitionWorker(QThread):
    """极简语音输入：开嘴就听，识别出来就增量写到 UI 文本框；用户停止即停。

    行为（按用户要求）：
      - 启动后 opening mic → 立即开始 listen；
      - 每听完一段立刻调识别引擎，结果通过 partial_signal 送到主线程的 txt_input；
      - 用户点停止 → 主线程调 stop() 设标志位；本线程立刻退出，不再无限阻塞。

    实现：
      - 用 recognizer.listen_in_background() 让 speech_recognition 自己起一个守护线程
        持续监听并按 phrase 切分吐回 AudioData。本线程不调用阻塞的 listen()，因此
        stop_flag 每 50ms 就能被检查一次 → 停止按钮 ≤ 50ms 响应。
      - 拿到 AudioData 后再做识别；Vosk 模型只加载一次。
    """
    text_signal = pyqtSignal(str)        # 最终识别完成（发送完整文本）
    partial_signal = pyqtSignal(str)     # 每段识别结果（增量）
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)      # 状态信息（用于 UI 状态栏）

    def __init__(self, engine="google", duration=60):
        super().__init__()
        self.engine = engine
        self.duration = duration          # 总允许最长录音时长（s）
        self._stop_flag = False
        self._stop_listening_fn = None    # recognizer.listen_in_background() 返回的停止函数
        self._collected = []              # 主线程 UI 的追加素材

    def stop(self):
        """主线程调用：停止后台监听 + 设标志位。"""
        self._stop_flag = True
        try:
            if self._stop_listening_fn is not None:
                # 立即中断后台监听线程；不会阻塞主线程
                self._stop_listening_fn(wait_for_stop=False)
        except Exception:
            pass

    def run(self):
        try:
            import speech_recognition as sr
        except ImportError:
            self.error_signal.emit("未安装 SpeechRecognition，请先 pip install SpeechRecognition pyaudio")
            return

        # Vosk 模型一次性加载
        vosk_model = None
        if self.engine == "vosk":
            try:
                from vosk import Model
                import os as _os
                model_dir = _os.path.join(
                    _os.path.dirname(_os.path.abspath(__file__)),
                    "..", "model", "vosk-model-small-cn-0.22",
                )
                model_dir = _os.path.abspath(model_dir)
                if not _os.path.exists(model_dir):
                    self.error_signal.emit(
                        f"未找到 Vosk 中文模型目录: {model_dir}\n请下载 vosk-model-small-cn-0.22 并放到该路径。"
                    )
                    return
                vosk_model = Model(model_dir)
            except ImportError:
                self.error_signal.emit("未安装 vosk，请先 pip install vosk")
                return
            except Exception as e:
                self.error_signal.emit(f"Vosk 模型加载失败: {e}")
                return

        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300        # 降低静音阈值，让轻语音也能触发
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.6         # 0.6 秒静音算一段话结束

        def _on_audio(recognizer_, audio):
            """后台监听线程回调：拿到 AudioData 后识别一次，结果 emit 到主线程。"""
            try:
                # 强制重采样到 16kHz / 16bit / mono，Vosk small 模型只接受这个格式
                if audio.sample_rate != 16000 or audio.sample_width != 2:
                    audio = _resample_to_16k(audio)
                # 诊断：让 UI 能看到回调实际拿到了多少音频
                energy = _audio_rms(audio)
                self.status_signal.emit(
                    f" 收到音频 {audio.sample_rate}Hz / {len(audio.frame_data)}B / 能量={energy:.0f}"
                )
                text = self._recognize(audio, recognizer_, vosk_model)
                if text:
                    self._collected.append(text)
                    self.partial_signal.emit("".join(self._collected))
            except Exception as e:
                self.error_signal.emit(f"语音识别回调异常: {e}")

        # 注意：sr.Microphone() 的 __enter__ 会在声卡上打开一次底层流，
        # 而 recognizer.listen_in_background() 内部还会再 enter 同一个 source。
        # Microphone 不允许嵌套 with，所以这里用「临时开」做一次噪音校准就关掉，
        # 再单独创建另一个 Microphone 实例交给 listen_in_background 自己 enter。
        source = None
        try:
            with sr.Microphone(sample_rate=16000) as cal_src:
                recognizer.adjust_for_ambient_noise(cal_src, duration=1.0)
            del cal_src
        except Exception as e:
            self.error_signal.emit(f"麦克风初始化失败: {e}")
            return

        try:
            source = sr.Microphone(sample_rate=16000)
            self.status_signal.emit(" 麦克风已打开，请开始说话")

            # listen_in_background 自己内部 enter source ——不要再外层 with 包裹
            self._stop_listening_fn = recognizer.listen_in_background(
                source, callback=_on_audio, phrase_time_limit=8
            )

            # 本线程进入 50ms 轮询，唯一职责就是等 stop_flag / 总时长超时
            import time as _time
            t_start = _time.time()
            while not self._stop_flag:
                if _time.time() - t_start >= self.duration:
                    break
                self.msleep(50)

            # 退出前确保后台监听停止（listen_in_background 内部会 exit source）
            try:
                if self._stop_listening_fn is not None:
                    self._stop_listening_fn(wait_for_stop=False)
            except Exception:
                pass
            try:
                del source
                source = None
            except Exception:
                pass

        except OSError as e:
            self.error_signal.emit(f"无法访问麦克风: {e}")
            return
        except Exception as e:
            self.error_signal.emit(f"语音识别异常: {e}")
            return

        if self._stop_flag:
            if self._collected:
                self.text_signal.emit("".join(self._collected))
            else:
                self.error_signal.emit("已停止语音识别")
            return
        if not self._collected:
            self.error_signal.emit("未能识别出有效内容。")
            return
        self.text_signal.emit("".join(self._collected))

    def _recognize(self, audio, recognizer, vosk_model):
        """识别一段 AudioData；返回文本，失败返回空串。"""
        try:
            if self.engine == "vosk":
                if vosk_model is None:
                    return ""
                try:
                    from vosk import KaldiRecognizer
                    import json as _json
                except Exception:
                    return ""
                rec = KaldiRecognizer(vosk_model, audio.sample_rate)
                rec.AcceptWaveform(audio.get_raw_data())
                final = _json.loads(rec.FinalResult())
                return (final.get("text", "") or "").strip()
            else:
                import speech_recognition as sr
                try:
                    return recognizer.recognize_google(audio, language="zh-CN").strip()
                except sr.UnknownValueError:
                    return ""
                except sr.RequestError as e:
                    self.error_signal.emit(f"在线识别服务不可用: {e}")
                    return ""
        except Exception:
            return ""


class AISmartDialog(QDialog):
    """智能问答弹窗：支持文字输入与系统麦克风语音识别，支持本地 Ollama / 云端 Kimi 两种 AI 模型切换。"""

    # 共享配置（弹窗关闭后下次重新读取）
    _local_url = None
    _local_model = None
    _loaded = False

    @classmethod
    def _ensure_config(cls):
        if cls._loaded:
            return
        cls._loaded = True
        path = os.path.join(os.path.dirname(__file__), "config_local_model.txt")
        try:
            lines = [l.strip() for l in open(path, "r", encoding="utf-8") if l.strip() and not l.startswith("#")]
            if len(lines) >= 2:
                cls._local_url = lines[0]
                cls._local_model = lines[1]
            else:
                cls._local_url = "http://localhost:11434"
                cls._local_model = "llama3"
        except Exception:
            cls._local_url = "http://localhost:11434"
            cls._local_model = "llama3"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(" AI 智能看护助手 (语音 + 打字)")
        self.resize(820, 620)
        self._voice_worker = None
        self._voice_suppress_until = 0.0  # send_text() 后短时间内忽略 voice partial 覆盖输入框
        self._chat_history = []
        self._current_model_mode = "kimi"  # "kimi" 或 "local"
        self.initUI()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "txt_input"):
            self.txt_input.setFocus()
            self.txt_input.activateWindow()

    def closeEvent(self, event):
        # 主线程绝不 wait 也不 join，只设标志让 worker 自己退出。
        if self._voice_worker is not None and self._voice_worker.isRunning():
            try:
                self._voice_worker.stop()
            except Exception:
                pass
        if self._ai_worker is not None and self._ai_worker.isRunning():
            try:
                self._ai_worker.requestInterruption()
            except Exception:
                pass
        if self._tts_worker is not None and self._tts_worker.isRunning():
            try:
                self._tts_worker.stop()
            except Exception:
                pass
        event.accept()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ===== 模型切换行 =====
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("AI 模型:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["☁️ 云端 Kimi 大模型", "💻 本地 Ollama 大模型"])
        self.model_combo.setStyleSheet(
            "QComboBox { background-color: #1E293B; border: 1px solid #475569; border-radius: 6px; "
            "color: #F8FAFC; padding: 6px 10px; font-size: 13px; }"
            "QComboBox::drop-down { border: none; width: 24px; }"
            "QComboBox::down-arrow { image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; "
            "border-top: 6px solid #94A3B8; margin-right: 6px; }"
            "QComboBox QAbstractItemView { background-color: #1E293B; color: #F8FAFC; selection-background-color: #38BDF8; }"
        )
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self.model_combo)

        # 本地模型配置按钮
        self.btn_config_local = QPushButton(" 配置本地模型")
        self.btn_config_local.setStyleSheet(
            "background-color: #334155; color: #94A3B8; padding: 6px 12px; border-radius: 6px;"
        )
        self.btn_config_local.clicked.connect(self._open_local_config)
        model_row.addWidget(self.btn_config_local)

        model_row.addStretch()
        self.lbl_model_status = QLabel("")
        self.lbl_model_status.setStyleSheet("color: #64748B; font-size: 11px;")
        model_row.addWidget(self.lbl_model_status)
        layout.addLayout(model_row)

        self.tip = QLabel()
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("color: #94A3B8; font-size: 12px; border: 1px solid #334155; border-radius: 6px; padding: 8px; background-color: #1E293B;")
        self._update_tip_text()
        layout.addWidget(self.tip)

        top_ctrl = QHBoxLayout()
        top_ctrl.addWidget(QLabel("语音引擎:"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["Google 在线识别 (需联网)", "Vosk 离线识别 (需本地模型)"])
        # 默认走 Vosk（国内环境 Google 不可达），如果你想用 Google 可以手动改回
        self.engine_combo.setCurrentIndex(1)
        top_ctrl.addWidget(self.engine_combo)

        top_ctrl.addStretch()
        self.btn_clear = QPushButton(" 清空对话")
        self.btn_clear.clicked.connect(self.clear_chat)
        top_ctrl.addWidget(self.btn_clear)
        layout.addLayout(top_ctrl)

        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        self.chat_view.setStyleSheet("background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; color: #F8FAFC; font-size: 13px; padding: 10px;")
        layout.addWidget(self.chat_view, stretch=1)

        input_row = QHBoxLayout()
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("请输入您想咨询的问题，例如：今天天气怎么样？")
        self.txt_input.setStyleSheet("background-color: #1E293B; border: 1px solid #475569; border-radius: 6px; color: #FFFFFF; padding: 8px; font-size: 13px;")
        self.txt_input.returnPressed.connect(self.send_text)
        input_row.addWidget(self.txt_input)

        self.btn_send = QPushButton("发送")
        self.btn_send.setStyleSheet("background-color: #10B981; color: #FFFFFF; font-weight: bold; padding: 8px 16px;")
        self.btn_send.clicked.connect(self.send_text)
        input_row.addWidget(self.btn_send)
        layout.addLayout(input_row)

        voice_row = QHBoxLayout()
        self.btn_voice = QPushButton(" 开始说话")
        self.btn_voice.setStyleSheet("background-color: #38BDF8; color: #0F172A; font-weight: bold; padding: 10px 20px; font-size: 14px;")
        self.btn_voice.clicked.connect(self.toggle_voice)
        voice_row.addWidget(self.btn_voice)

        self.lbl_voice_status = QLabel("空闲")
        self.lbl_voice_status.setStyleSheet("color: #94A3B8; font-size: 12px;")
        voice_row.addWidget(self.lbl_voice_status)
        voice_row.addStretch()
        layout.addLayout(voice_row)

        # ============ TTS 语音播报行 ============
        tts_row = QHBoxLayout()
        self.chk_tts = QCheckBox("AI 回复自动语音播报")
        self.chk_tts.setChecked(True)
        self.chk_tts.setStyleSheet("color: #94A3B8; font-size: 12px; border: none; padding: 4px;")
        tts_row.addWidget(self.chk_tts)

        self.btn_tts_once = QPushButton("朗读上一条回复")
        self.btn_tts_once.setStyleSheet("background-color: #6366F1; color: #FFFFFF; font-weight: bold; padding: 6px 12px;")
        self.btn_tts_once.clicked.connect(self._tts_last_reply)
        tts_row.addWidget(self.btn_tts_once)

        self.btn_tts_stop = QPushButton("停止朗读")
        self.btn_tts_stop.setEnabled(False)
        self.btn_tts_stop.setStyleSheet("background-color: #475569; color: #94A3B8; padding: 6px 12px;")
        self.btn_tts_stop.clicked.connect(self._tts_stop)
        tts_row.addWidget(self.btn_tts_stop)

        self.lbl_tts_status = QLabel("")
        self.lbl_tts_status.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        tts_row.addWidget(self.lbl_tts_status)
        tts_row.addStretch()
        layout.addLayout(tts_row)

        self._ai_worker = None
        self._last_assistant_text = ""
        self._tts_worker = None

        self._append_chat("assistant", "您好！我是您的 AI 看护助手。您可以问我关于健康、饮食、天气、作息等任何问题。")

    def _update_tip_text(self):
        mode = self.model_combo.currentIndex()
        if mode == 1:  # 本地 Ollama
            AISmartDialog._ensure_config()
            self.tip.setText(
                f" 当前使用本地 Ollama 模型（{AISmartDialog._local_model}），无需联网。\n"
                f"   请确保 Ollama 已启动且服务地址为 {AISmartDialog._local_url}"
            )
            self.lbl_model_status.setText(f"本地: {AISmartDialog._local_model}")
            self.lbl_model_status.setStyleSheet("color: #10B981; font-size: 11px;")
        else:  # 云端 Kimi
            self.tip.setText(
                " 当前使用云端 Kimi 大模型（kimi-k2.6），需要联网。\n"
                "   请确保网络通畅；也可切换到本地 Ollama 模型离线使用。"
            )
            self.lbl_model_status.setText("云端: Kimi")
            self.lbl_model_status.setStyleSheet("color: #38BDF8; font-size: 11px;")

    def _on_model_changed(self, index):
        self._current_model_mode = "local" if index == 1 else "kimi"
        self._update_tip_text()

    def _open_local_config(self):
        path = os.path.join(os.path.dirname(__file__), "config_local_model.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = "# Ollama 本地模型配置（请修改以下两行，不要删除 # 注释行）\n" \
                      "http://localhost:11434\nllama3\n"
        dlg = QDialog(self)
        dlg.setWindowTitle(" 配置本地 Ollama 模型")
        dlg.resize(520, 220)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.addWidget(QLabel("请填入 Ollama 服务地址和模型名称，按回车确认："))
        dlg_layout.addWidget(QLabel("(格式：每行一个，第一行是地址，第二行是模型名，如 qwen2.5）"))

        form = QFormLayout()
        le_url = QLineEdit()
        le_model = QLineEdit()
        lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
        if len(lines) >= 2:
            le_url.setText(lines[0])
            le_model.setText(lines[1])
        else:
            le_url.setText("http://localhost:11434")
            le_model.setText("llama3")
        form.addRow("服务地址:", le_url)
        form.addRow("模型名称:", le_model)
        dlg_layout.addLayout(form)

        btns = QHBoxLayout()
        btn_ok = QPushButton(" 保存")
        btn_ok.setStyleSheet("background-color: #10B981; color: white; padding: 6px 20px;")
        btn_cancel = QPushButton(" 取消")
        btn_cancel.setStyleSheet("background-color: #475569; color: white; padding: 6px 20px;")
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        dlg_layout.addLayout(btns)

        def save_and_close():
            cfg = f"# Ollama 本地模型配置\n{le_url.text().strip()}\n{le_model.text().strip()}\n"
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(cfg)
                AISmartDialog._loaded = False
                AISmartDialog._ensure_config()
                self._update_tip_text()
            except Exception as e:
                QMessageBox.warning(self, "保存失败", f"写入配置文件失败：{e}")
            dlg.accept()

        btn_ok.clicked.connect(save_and_close)
        btn_cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _append_chat(self, role, text):
        from PyQt6.QtCore import QDateTime
        ts = QDateTime.currentDateTime().toString("hh:mm:ss")
        if role == "user":
            html = f'<div style="margin:6px 0;"><b style="color:#38BDF8;">[{ts}] 老人：</b><span style="color:#F8FAFC;"> {text}</span></div>'
        else:
            html = f'<div style="margin:6px 0; background:#1E293B; padding:8px; border-radius:6px;"><b style="color:#10B981;">[{ts}] 助手：</b><span style="color:#F8FAFC;"> {text}</span></div>'
        self.chat_view.append(html)
        self._chat_history.append({"role": role, "text": text})

    def send_text(self):
        text = self.txt_input.text().strip()
        if not text:
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            return
        # 发送前先停掉语音 worker：避免它的 partial_signal 在发送后又把文本塞回输入框
        try:
            if self._voice_worker is not None and self._voice_worker.isRunning():
                self._voice_worker.stop()
                self._voice_worker.wait(500)
        except Exception:
            pass
        self._voice_suppress_until = _time.time() + 1.5  # 抑制后续 partial 覆盖输入框 1.5 秒
        self._tts_stop()
        self.txt_input.clear()
        self._append_chat("user", text)
        self._ask_ai(text)

    def toggle_voice(self):
        if self._voice_worker is not None and self._voice_worker.isRunning():
            try:
                self._voice_worker.stop()
            except Exception:
                pass
            # 立刻给用户视觉反馈：按钮灰掉，文案改成"停止中…"
            try:
                self.btn_voice.setEnabled(False)
                self.btn_voice.setText(" 停止中…")
            except Exception:
                pass
            return
        engine = "vosk" if self.engine_combo.currentIndex() == 1 else "google"
        try:
            self.btn_voice.setText(" 停止说话")
            self.btn_voice.setStyleSheet("background-color: #DC2626; color: #FFFFFF; font-weight: bold; padding: 10px 20px; font-size: 14px;")
            self.btn_voice.setEnabled(True)
            self.lbl_voice_status.setText(" 正在聆听... 边说会边显示在输入框")
            self.lbl_voice_status.setStyleSheet("color: #F59E0B; font-size: 12px; font-weight: bold;")
            self.txt_input.setText("")
            self.txt_input.setPlaceholderText("请开始说话，识别结果会实时显示在此…")
        except Exception:
            pass
        self._voice_worker = _VoiceRecognitionWorker(engine=engine, duration=60)
        self._voice_worker.partial_signal.connect(self._on_voice_partial)
        self._voice_worker.text_signal.connect(self._on_voice_text)
        self._voice_worker.error_signal.connect(self._on_voice_error)
        self._voice_worker.status_signal.connect(self._on_voice_status)
        self._voice_worker.finished.connect(self._on_voice_finished)
        self._voice_worker.start()

    def start_voice(self):
        self.toggle_voice()

    def _on_voice_partial(self, text):
        # 如果 send_text() 后短时间内还在 emit partial，跳过（防止覆盖已发送的空输入框）
        if _time.time() < getattr(self, "_voice_suppress_until", 0):
            return
        # 直接覆盖文本框：用户最简单需求——说啥就写啥
        if self.txt_input.text() != text:
            self.txt_input.setText(text)
            # 让光标在末尾，方便继续输入或按发送
            try:
                self.txt_input.setCursorPosition(len(text))
            except Exception:
                pass

    def _on_voice_text(self, text):
        # 如果 send_text() 后短时间内还有 final 文本到达，跳过（已被发送的空输入框不要被回填）
        if _time.time() < getattr(self, "_voice_suppress_until", 0):
            return
        # 最终文本：写一次到文本框
        if text:
            self.txt_input.setText(text)
            try:
                self.txt_input.setCursorPosition(len(text))
            except Exception:
                pass
            # 跟语音停止一起复用：语音识别完成不自动发送，保留给用户确认
            # 如果你希望完成时自动发送 AI，把下面注释打开：
            # self._append_chat("user", text)
            # self._ask_ai(text)

    def _on_voice_error(self, msg):
        try:
            self.lbl_voice_status.setText(f"⚠ {msg}")
            self.lbl_voice_status.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: bold;")
        except Exception:
            pass
        if "未能识别" not in msg and "已停止" not in msg:
            try:
                QMessageBox.warning(self, "语音识别提示", msg)
            except Exception:
                pass

    def _on_voice_status(self, msg):
        try:
            self.lbl_voice_status.setText(msg)
            self.lbl_voice_status.setStyleSheet("color: #38BDF8; font-size: 12px; font-weight: bold;")
        except Exception:
            pass

    def _on_voice_finished(self):
        try:
            self.btn_voice.setText(" 开始说话")
            self.btn_voice.setStyleSheet("background-color: #38BDF8; color: #0F172A; font-weight: bold; padding: 10px 20px; font-size: 14px;")
            self.btn_voice.setEnabled(True)
            self.lbl_voice_status.setText("空闲")
            self.lbl_voice_status.setStyleSheet("color: #94A3B8; font-size: 12px;")
            self.txt_input.setPlaceholderText("请输入您想咨询的问题，例如：今天天气怎么样？")
        except Exception:
            pass
        self._voice_worker = None

    def clear_chat(self):
        self.chat_view.clear()
        self._chat_history.clear()
        self._append_chat("assistant", "对话已清空。有什么我可以帮您的吗？")

    def _ask_ai(self, question):
        """异步调用 AI：情绪融合 → Kimi/Ollama → 文本情绪分析 → 动态语气。"""
        self.btn_send.setEnabled(False)
        self.txt_input.setEnabled(False)
        self._append_chat("assistant", "正在为您思考，请稍候…")

        visual_emotion = self._get_visual_emotion()
        text_emotion, text_score = _analyze_text_emotion(question)

        self._ai_worker = _KimiAskWorker(
            question=question,
            history=list(self._chat_history[:-1]),
            visual_emotion_cn=visual_emotion,
            text_emotion_cn=text_emotion,
            text_score=text_score,
            model_mode=self._current_model_mode,
        )
        self._ai_worker.done_signal.connect(self._on_ai_done)
        self._ai_worker.finished.connect(self._on_ai_finished)
        self._ai_worker.start()

    def _get_visual_emotion(self):
        """从情绪识别弹窗读取当前帧的视觉情绪（共享 class 变量）。"""
        try:
            emo = EmotionDetectionDialog._last_emotion_cn
            if not emo or emo == "--":
                return None
            return emo
        except Exception:
            return None

    def _tts_last_reply(self):
        if not self._last_assistant_text:
            return
        self._speak(self._last_assistant_text)

    def _tts_stop(self):
        """打断当前 TTS 朗读：不挂起主线程，只让 worker 自己软退出。"""
        try:
            if self._tts_worker is not None and self._tts_worker.isRunning():
                self._tts_worker.stop()
        except Exception:
            pass

    def _speak(self, text):
        """启动 TTS 后台线程朗读一段文字。

        关键改进：旧实现里，如果上一次 worker 还在跑，_speak() 直接 return，
        导致"AI 回复后只读一句（上一条尾巴），第二条再读就哑火"。
        现在改为：打断旧 worker → 短暂等待旧 worker 退出 → 启动新 worker。
        主线程不调用 engine，仅设 _stop_flag（同线程才会立即响应）。
        """
        if not text:
            return
        # 如果当前 worker 还在跑：打断它，等它结束后再启动新 worker
        try:
            if self._tts_worker is not None and self._tts_worker.isRunning():
                try:
                    self._tts_worker.stop()
                except Exception:
                    pass
                # 等旧 worker 自然退出（最多 500ms 避免 UI 卡顿）
                # finished 信号也会把 _tts_worker 设为 None。
                self._tts_worker.wait(500)
        except Exception:
            pass

        # 启动新 worker
        self._tts_worker = _TTSWorker(text)
        self._tts_worker.status_signal.connect(self._on_tts_status)
        self._tts_worker.finished.connect(self._on_tts_finished)
        self.btn_tts_stop.setEnabled(True)
        self.btn_tts_stop.setStyleSheet("background-color: #DC2626; color: #FFFFFF; padding: 6px 12px;")
        self._tts_worker.start()
        self.lbl_tts_status.setText("正在朗读…")
        self.lbl_tts_status.setStyleSheet("color: #38BDF8; font-size: 11px; border: none;")

    def _on_tts_status(self, msg):
        self.lbl_tts_status.setText(msg)

    def _on_tts_finished(self):
        # 只有当前 worker 才是它自己时才清空引用，避免覆盖新 worker
        try:
            sender = self.sender()
        except Exception:
            sender = None
        if sender is self._tts_worker:
            self._tts_worker = None
            self.btn_tts_stop.setEnabled(False)
            self.btn_tts_stop.setStyleSheet("background-color: #475569; color: #94A3B8; padding: 6px 12px;")
            msg = (self.lbl_tts_status.text() or "").strip()
            if msg == "正在朗读…":
                self.lbl_tts_status.setText("朗读已结束")
                self.lbl_tts_status.setStyleSheet("color: #64748B; font-size: 11px; border: none;")

    def _on_ai_done(self, answer):
        try:
            last = self._chat_history[-1] if self._chat_history else None
            if last and last.get("role") == "assistant" and "正在为您思考" in last.get("text", ""):
                self._chat_history.pop()
                cursor = self.chat_view.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.select(cursor.SelectionType.Block)
                cursor.removeSelectedText()
                cursor.deleteChar()
        except Exception:
            pass
        self._append_chat("assistant", answer)
        self._last_assistant_text = answer
        try:
            if getattr(self, "chk_tts", None) and self.chk_tts.isChecked():
                self._speak(answer)
        except Exception:
            pass

    def _on_ai_finished(self):
        self.btn_send.setEnabled(True)
        self.txt_input.setEnabled(True)
        self.txt_input.setFocus()
        self._ai_worker = None


# ==================== Kimi AI 配置 ====================
# API Key 读取顺序：1) 环境变量 KIMI_API_KEY  2) 同目录 config_kimi.txt（仅含 key 的纯文本文件）
# config_kimi.txt 内容示例（无引号、无空格，仅一行 key）：
#   sk-fSjkBoXTA5x0gR3qzjmEIAvMB7CFY2dhXTe1u5dGvLrk1c9t

def _load_kimi_key():
    key = os.environ.get("KIMI_API_KEY", "").strip()
    if key:
        return key
    cfg_path = os.path.join(os.path.dirname(__file__), "config_kimi.txt")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


_KIMI_API_KEY = _load_kimi_key()
_KIMI_BASE_URL = "https://api.moonshot.cn/v1"
_KIMI_MODEL = "kimi-k2.6"


def _kimi_chat(messages, api_key=None):
    """调用月之暗面 Kimi 大模型，返回回复文本；失败返回 None。"""
    key = api_key or _KIMI_API_KEY
    if not key:
        return None
    try:
        import urllib.request, json
        url = f"{_KIMI_BASE_URL}/chat/completions"
        payload = json.dumps({
            "model": _KIMI_MODEL,
            "messages": messages,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _ollama_chat(messages, model_name=None):
    """调用本地 Ollama 大模型，返回回复文本；失败返回 None。"""
    AISmartDialog._ensure_config()
    model = model_name or AISmartDialog._local_model
    url = f"{AISmartDialog._local_url}/api/chat"
    try:
        import urllib.request, json
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "")
    except Exception:
        return None


def _build_system_prompt(emotion_cn=None, user_name=None):
    """根据检测到的情绪动态生成 system prompt，让 AI 语气调整。"""
    base = (
        "你是一位贴心的 AI 看护助手，专门为老年用户及其家属提供健康、"
        "饮食、作息、情绪、就医等方面的陪伴式问答。"
    )
    if user_name:
        base += f"对方称呼「{user_name}」，请自然使用。"

    base += "每条回答控制在 150 字以内，分段清晰，语气温暖耐心。"

    if emotion_cn:
        emotion_tone = {
            "高兴": "用户当前情绪是「高兴」，请保持分享式的愉悦语气，可适当称赞与共情。",
            "悲伤": "用户当前情绪是「悲伤」，请温和共情、给予鼓励，先安抚再给建议。",
            "愤怒": "用户当前情绪是「愤怒」，请保持克制与倾听，先表达理解再平和地回应。",
            "恐惧": "用户当前情绪是「恐惧」，请给予安全感，先确认安全再给出具体、可操作的步骤。",
            "惊讶": "用户当前情绪是「惊讶」，请用平缓、解释性的语言帮助其理清事件。",
            "厌恶": "用户当前情绪是「厌恶」，请尊重其感受，避免重复触发点，转向积极话题。",
            "平静": "用户当前情绪是「平静」，请用平和、专业的语气给出实用建议。",
            "困惑": "用户当前情绪是「困惑」，请用最直白、举例的方式解释，避免术语。",
            "积极": "用户当前情绪是「积极」，可以热情互动并提供延伸建议。",
            "消极": "用户当前情绪是「消极」，请先共情并给予安慰，再适度引导。",
            "中性": "用户当前情绪稳定，请用平和自然的语气回答。",
        }
        base += "\n" + emotion_tone.get(emotion_cn, f"用户当前情绪是「{emotion_cn}」，请相应地调整语气。")

    base += "如涉及医疗建议，请提醒用户咨询专业医生，避免过度诊断。"
    return base


# ==================== 文本情绪分析（无外部依赖） ====================

_TEXT_EMOTION_KEYWORDS = {
    "高兴": ["开心", "高兴", "快乐", "哈哈", "舒服", "幸福", "满意", "不错", "太好了", "好棒"],
    "悲伤": ["难过", "伤心", "悲伤", "失望", "沮丧", "哭", "郁闷", "失落", "孤独", "想哭"],
    "愤怒": ["生气", "愤怒", "气死", "讨厌", "烦死", "凭什么", "混蛋", "恼火", "不爽"],
    "恐惧": ["害怕", "恐惧", "吓人", "恐慌", "担心", "焦虑", "紧张", "不安", "惊恐"],
    "惊讶": ["惊讶", "居然", "竟然", "没想到", "哇", "不可思议", "太意外"],
    "厌恶": ["恶心", "厌恶", "反感", "嫌弃", "讨厌", "不行"],
    "平静": ["还好", "一般", "平常", "没事", "正常", "习惯"],
    "困惑": ["不懂", "不明白", "为什么", "怎么会", "什么意思", "糊涂"],
}

NEGATION_WORDS = {"不", "没", "别", "无", "非", "未", "否"}


def _analyze_text_emotion(text):
    """从文本中识别简单情绪，返回 (emotion_cn, score)，score∈[0,1]。"""
    if not text:
        return None, 0.0
    text_lower = text
    scores = {emo: 0 for emo in _TEXT_EMOTION_KEYWORDS}
    for emo, kws in _TEXT_EMOTION_KEYWORDS.items():
        for kw in kws:
            if kw in text_lower:
                idx = text_lower.find(kw)
                pre = text_lower[max(0, idx - 1):idx]
                if pre in NEGATION_WORDS:
                    continue
                scores[emo] += 1
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return None, 0.0
    total = sum(scores.values()) or 1
    return best, min(1.0, scores[best] / total)


def _decide_fused_emotion(visual_emotion_cn, text_emotion_cn, text_score):
    """情绪融合: 视觉 + 文本, 文本 score 低时优先视觉。"""
    if not text_emotion_cn or text_score < 0.4:
        return visual_emotion_cn or "中性"
    if not visual_emotion_cn or visual_emotion_cn == "--":
        return text_emotion_cn
    same = {visual_emotion_cn, text_emotion_cn}
    if len(same) == 1:
        return visual_emotion_cn
    soft = {
        "悲伤", "恐惧", "愤怒", "困惑", "厌恶",
        "高兴", "平静", "惊讶",
    }
    if visual_emotion_cn in soft and text_emotion_cn in soft:
        return text_emotion_cn
    return visual_emotion_cn


# ==================== AI 问答（支持情绪融合 + Kimi 大模型 + 本地兜底） ====================

def answer_question(question, history=None, visual_emotion_cn=None, text_emotion_cn=None,
                   text_score=0.0, user_name=None, model_mode="kimi"):
    """AI 问答的统一入口：mode="kimi" 调云端 Kimi，mode="local" 调本地 Ollama，
    均失败时回退到本地规则模板。
    visual_emotion_cn: 来自人脸识别（视觉情绪）
    text_emotion_cn:   来自文本分析
    两者融合后决定 system prompt 语气。
    """
    q = (question or "").strip()
    if not q:
        return "您可以再说清楚一些，我会尽力帮助您。"

    fused = _decide_fused_emotion(visual_emotion_cn, text_emotion_cn, text_score)

    messages = [{"role": "system", "content": _build_system_prompt(emotion_cn=fused, user_name=user_name)}]
    if history:
        for h in history:
            role = "user" if h.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": h.get("text", "")})
    messages.append({"role": "user", "content": q})

    # 本地模式优先调用 Ollama
    if model_mode == "local":
        reply = _ollama_chat(messages)
        if reply and reply.strip():
            return reply.strip()

    # 云端模式调 Kimi
    if model_mode == "kimi" and _KIMI_API_KEY:
        reply = _kimi_chat(messages)
        if reply:
            return reply.strip()

    rules = [
        (["你好", "您好", "嗨"], {
            "高兴": "看到您这么开心，我就放心啦！继续保持好心情哦。",
            "悲伤": "您好呀，不管今天心情如何，我都在这里陪着您。",
            "愤怒": "您好，先深呼吸一下，慢慢说，我在听。",
            "恐惧": "您好，放轻松，我在这里陪着您。",
            "平静": "您好呀，今天感觉怎么样？",
        }, "您好呀！我是您的 AI 看护助手，今天感觉怎么样？"),
        (["天气"], None, "今天天气晴朗，气温 18~26℃，适合老人出门散步，记得带件薄外套哦。"),
        (["血压", "高压"], None, "血压建议每天定时测量并记录，保持情绪平稳、避免用力起身。"),
        (["血糖"], None, "餐后血糖建议控制在合理范围内，少食多餐、避免甜食与精制米面。"),
        (["失眠", "睡不着", "睡眠"], None, "睡前避免看手机，可以温水泡脚、做几节深呼吸。"),
        (["吃药", "用药", "药"], None, "建议用分药盒按早中晚分装，避免漏服或重复服用。"),
        (["摔倒", "跌倒"], None, "如不慎跌倒，请先确认有无疼痛再缓慢起身；持续不适立即联系家属或拨打 120。"),
        (["无聊", "闷"], None, "可以听听老歌、看看戏曲，或者和老朋友通个电话，让心情亮起来。"),
        (["吃饭", "饮食"], None, "建议少油少盐、每天保证一杯奶、一个鸡蛋、适量蔬菜与优质蛋白。"),
        (["运动", "锻炼"], None, "饭后半小时散步 15~20 分钟，做几节简单的伸展运动就很好。"),
        (["医生", "看病"], None, "如有不适，建议先联系家庭医生；急症请立即拨打 120。"),
    ]
    for keywords, tone_map, default in rules:
        for kw in keywords:
            if kw in q:
                if tone_map and fused in tone_map:
                    return tone_map[fused]
                return default

    fallback = (
        f"我已经记下您的问题：「{q}」。"
    )
    if fused == "悲伤":
        fallback += "先试着深呼吸三次，遇到任何事都可以跟我说。"
    elif fused == "恐惧":
        fallback += "您现在是安全的，有任何担心都可以告诉我。"
    elif fused == "愤怒":
        fallback += "我理解您的感受，我们可以先冷静一下再聊。"
    elif fused == "高兴":
        fallback += "听到您心情这么好，我也替您开心。"
    else:
        fallback += "目前本地规则模板能覆盖的问题有限，如果配置了 Kimi API Key 会给您更贴心的回答哦。"

    return fallback


__all__ = [
    "LoginDialog", "SettingsDialog", "HistoryDialog", "HealthDashboardDialog",
    "EmotionDetectionDialog", "AISmartDialog", "get_emotion_advice", "answer_question",
]