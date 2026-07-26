# detector.py
'''
 AI 核心检测与线程控制模块核心功能：
 系统的核心业务与 AI 算法层，采用多线程（QThread）运行，防止界面卡顿。
 主要内容：集成 YOLOv8（目标检测人体框定位）和 MediaPipe（人体姿态骨骼关键点提取）。
通过计算躯干倾斜角（aci_hesapla）判断老人是否发生跌倒（站立/平躺/跌倒中）。
跌倒触发时：自动播放本地警报音频（pygame）、异步录制前后缓冲区视频到本地 result 目录、写入 MySQL 数据库，并通过 Webhook 实时推送卡片消息到飞书机器人。

'''
import os
import sys
import torch as _torch_module  # 必须先 import torch 才能用它的 CUDA 库
_torch_lib = os.path.join(os.path.dirname(_torch_module.__file__), 'lib')
if _torch_lib not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _torch_lib + os.pathsep + os.environ.get('PATH', '')
del _torch_lib

os.environ['YOLO_AUTOINSTALL'] = '0'  # 防止 ultralytics 自动 pip install onnxruntime CPU 版

import math
import time
import json
import urllib.request
import numpy as np
import cv2
import torch  # noqa: F401 - 已在上面作为 _torch_module 导入，此处供其他代码直接使用
from collections import deque
from ultralytics import YOLO
import mediapipe as mp
from PIL import Image, ImageDraw, ImageFont
import pygame 
import pymysql
import threading
from PyQt6.QtCore import QThread, pyqtSignal, QDateTime

def cv2_add_chinese_text(img, text, position, font_size=20, color=(0, 255, 0)):
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    try:
        font = ImageFont.truetype("msyh.ttc", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("simhei.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    rgb_color = (color[2], color[1], color[0])
    draw.text(position, text, font=font, fill=rgb_color)
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

def aci_hesapla(omuz_merkezi, kalca_merkezi):
    dy = omuz_merkezi[1] - kalca_merkezi[1]
    dx = omuz_merkezi[0] - kalca_merkezi[0]
    aci = math.atan2(dy, dx)
    return abs(90 - np.degrees(aci))

class DetectionThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray, str, int, bool)
    log_signal = pyqtSignal(str)

    def __init__(self, source=0, settings=None):
        super().__init__()
        self.source = source
        self._device = "cpu"
        default_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/e1d06cee-2c38-4679-962a-9fccb85fd766"
        self.settings = settings if settings else {"fall_threshold": 50, "sound_enabled": True, "buffer_seconds": 10, "feishu_webhook": default_webhook}
        self.settings["feishu_webhook"] = default_webhook

        self.running = True

        self.save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result')
        os.makedirs(self.save_dir, exist_ok=True)
        self.alarm_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alarm.mp3')
        
        self.last_feishu_time = 0 

    def stop(self):
        self.running = False
        self.wait()

    def play_alarm_sound(self):
        if not self.settings.get("sound_enabled", True):
            return
        try:
            if os.path.exists(self.alarm_file):
                if not pygame.mixer.music.get_busy():
                    pygame.mixer.music.load(self.alarm_file)
                    pygame.mixer.music.play()
        except Exception as e:
            print(f"播放警报音频异常: {e}")

    def send_feishu_notification(self, video_filename):
        webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/e1d06cee-2c38-4679-962a-9fccb85fd766"
        time_str = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": " 紧急警报：智能看护系统检测到跌倒！"},
                    "template": "red"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**️ 注意：监控画面检测到老人发生跌倒行为！**\n\n"
                                       f"- **发生时间**：`{time_str}`\n"
                                       f"- **录像存档**：`{video_filename}`\n"
                                       f"- **系统状态**：已自动截取前后缓冲区视频保存至本地，并将告警事件记录成功写入 MySQL 数据库。"
                        }
                    },
                    {
                        "tag": "note",
                        "elements": [{"tag": "plain_text", "content": "请家属立刻查看监控或通过历史回访确认老人安全！"}]
                    }
                ]
            }
        }

        data = json.dumps(payload).encode('utf-8')

        try:
            req = urllib.request.Request(
                webhook_url, data=data, headers={'Content-Type': 'application/json'}, method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result.get('code') == 0 or result.get('StatusCode') == 0:
                    self.log_signal.emit("飞书机器人跌倒告警实时推送成功！")
                else:
                    self.log_signal.emit(f"飞书推送返回错误: {result}")
        except Exception as e:
            self.log_signal.emit(f"发送飞书通知异常: {e}")

    def save_alarm_to_db(self, filename):
        try:
            db = pymysql.connect(
                host='localhost', user='root', password='231006410',
                database='fall_detector_db', charset='utf8mb4'
            )
            cursor = db.cursor()
            time_str = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
            cursor.execute(
                "INSERT INTO alarm_logs (alarm_time, video_filename, status) VALUES (%s, %s, %s);",
                (time_str, filename, "未处理")
            )
            db.commit()
            cursor.close()
            db.close()
        except Exception as e:
            print(f"写入数据库告警记录失败: {e}")

    def handle_alarm_async(self, filename, buffer_frames, fps, genislik, yukseklik):
        try:
            self.play_alarm_sound()
            dusme_video_dosyasi = os.path.join(self.save_dir, filename)
            writer = cv2.VideoWriter(
                dusme_video_dosyasi, cv2.VideoWriter_fourcc(*'mp4v'), fps, (genislik, yukseklik)
            )
            while buffer_frames:
                writer.write(buffer_frames.popleft())
            
            self.current_async_writer = writer
            self.save_alarm_to_db(filename)
            self.send_feishu_notification(filename)
            self.log_signal.emit(f"️ 警报：检测到人员跌倒！已异步存入本地与MySQL、推送飞书并保存至 {filename}")
        except Exception as e:
            self.log_signal.emit(f" 异步处理告警异常: {e}")

    def run(self):
        self.log_signal.emit("正在加载 YOLOv8 & MediaPipe 模型 (已启用轻量极速与异步告警模式)...")
        try:
            try:
                import torch
                if torch.cuda.is_available():
                    self._device = "cuda:0"
                    self.log_signal.emit(f" YOLOv8 跌倒检测已启用 GPU: {torch.cuda.get_device_name(0)}")
                else:
                    self._device = "cpu"
                    self.log_signal.emit("️ YOLOv8 跌倒检测回退到 CPU")
            except ImportError:
                self._device = "cpu"
                self.log_signal.emit("️ 未安装 torch，YOLOv8 跌倒检测回退到 CPU")
            model = YOLO('yolov8n.pt')
            if self._device != "cpu":
                model.to(self._device)
        except Exception as e:
            self.log_signal.emit(f" YOLO 模型加载失败: {e}")
            return
        
        cap_source = int(self.source) if str(self.source).isdigit() else self.source
        cap = cv2.VideoCapture(cap_source)
        
        if not cap.isOpened():
            self.log_signal.emit(f" 错误：无法打开视频源 [{self.source}]！")
            return

        self.log_signal.emit(f" 成功连接视频源: {self.source}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0 or math.isnan(fps):
            fps = 30.0

        genislik = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        yukseklik = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        dusme_sayaci = 0
        dusme_video_sayisi = 0
        dusme_sonrasi_kareler = 0
        dusme_sonrasi_bekleme_suresi = 10
        dusme_video_yazici = None
        self.current_async_writer = None
        
        last_alarm_timestamp = 0
        cooldown_seconds = 1  

        buffer_sec = self.settings.get("buffer_seconds", 10)
        tampon_boyutu = int(buffer_sec * fps)
        kare_tamponu = deque(maxlen=tampon_boyutu)

        mp_cizim = mp.solutions.drawing_utils
        mp_poz = mp.solutions.pose
        fall_threshold = self.settings.get("fall_threshold", 50)

        with mp_poz.Pose(
            min_detection_confidence=0.5, min_tracking_confidence=0.5, model_complexity=0
        ) as poz:
            while self.running and cap.isOpened():
                ret, kare = cap.read()
                if not ret:
                    if not str(self.source).isdigit():
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        self.log_signal.emit("️ 摄像头读取中断或无数据。")
                        break

                current_durus = "未检测到人员"
                is_falling = False

                sonuclar = model(kare, device=self._device, verbose=False)
                for sonuc in sonuclar:
                    for bbox, sinif in zip(sonuc.boxes.xyxy, sonuc.boxes.cls):
                        if int(sinif) == 0:  #coco数据集 0--person
                            x1, y1, x2, y2 = map(int, bbox)
                            x1, y1 = max(0, x1), max(0, y1)
                            x2, y2 = min(genislik, x2), min(yukseklik, y2)
                            
                            if x2 - x1 < 10 or y2 - y1 < 10:
                                continue

                            kisi_bbox = kare[y1:y2, x1:x2].copy()
                            kisi_bbox_rgb = cv2.cvtColor(kisi_bbox, cv2.COLOR_BGR2RGB)
                            kisi_sonuclari = poz.process(kisi_bbox_rgb)

                            if kisi_sonuclari.pose_landmarks:
                                mp_cizim.draw_landmarks(
                                    kisi_bbox, kisi_sonuclari.pose_landmarks, mp_poz.POSE_CONNECTIONS
                                )

                                isaretler = kisi_sonuclari.pose_landmarks.landmark
                                h_box, w_box, _ = kisi_bbox.shape

                                omuzlar = [
                                    (isaretler[mp_poz.PoseLandmark.LEFT_SHOULDER.value].x * w_box, isaretler[mp_poz.PoseLandmark.LEFT_SHOULDER.value].y * h_box),
                                    (isaretler[mp_poz.PoseLandmark.RIGHT_SHOULDER.value].x * w_box, isaretler[mp_poz.PoseLandmark.RIGHT_SHOULDER.value].y * h_box)
                                ]
                                kalcalar = [
                                    (isaretler[mp_poz.PoseLandmark.LEFT_HIP.value].x * w_box, isaretler[mp_poz.PoseLandmark.LEFT_HIP.value].y * h_box),
                                    (isaretler[mp_poz.PoseLandmark.RIGHT_HIP.value].x * w_box, isaretler[mp_poz.PoseLandmark.RIGHT_HIP.value].y * h_box)
                                ]

                                omuz_merkezi = ((omuzlar[0][0] + omuzlar[1][0]) / 2, (omuzlar[0][1] + omuzlar[1][1]) / 2)
                                kalca_merkezi = ((kalcalar[0][0] + kalcalar[1][0]) / 2, (kalcalar[0][1] + kalcalar[1][1]) / 2)

                                torso_aci = aci_hesapla(kalca_merkezi, omuz_merkezi)
                                
                                if torso_aci < 20:
                                    current_durus = "站立 (Normal)"
                                elif torso_aci > fall_threshold:
                                    current_durus = "平躺 (Lying)"
                                else:
                                    current_durus = "跌倒中 (Falling)"

                                if current_durus == "跌倒中 (Falling)":
                                    is_falling = True
                                    dusme_sayaci += 1
                                    dusme_sonrasi_kareler = 0

                                    current_time = time.time()
                                    if 1 <= dusme_sayaci and (current_time - last_alarm_timestamp > cooldown_seconds):
                                        if dusme_video_yazici is None and self.current_async_writer is None:
                                            last_alarm_timestamp = current_time  
                                            dusme_video_sayisi += 1
                                            filename = f'dusme_{QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")}_{dusme_video_sayisi}.mp4'
                                            
                                            buffer_copy = deque(kare_tamponu)
                                            alarm_thread = threading.Thread(
                                                target=self.handle_alarm_async,
                                                args=(filename, buffer_copy, fps, genislik, yukseklik)
                                            )
                                            alarm_thread.daemon = True
                                            alarm_thread.start()
                                else:
                                    dusme_sayaci = 0

                                if current_durus == "站立 (Normal)" and (dusme_video_yazici is not None or self.current_async_writer is not None):
                                    dusme_sonrasi_kareler += 1

                            kare[y1:y2, x1:x2] = kisi_bbox

                            color = (0, 0, 255) if is_falling else (0, 255, 0)
                            cv2.rectangle(kare, (x1, y1), (x2, y2), color, 2)

                            text_pos = (x1, max(y1 - 30, 10))
                            kare = cv2_add_chinese_text(kare, current_durus, text_pos, font_size=22, color=color)

                if self.current_async_writer is not None:
                    dusme_video_yazici = self.current_async_writer
                    self.current_async_writer = None

                if dusme_video_yazici is not None:
                    dusme_video_yazici.write(kare)

                if dusme_sonrasi_kareler > dusme_sonrasi_bekleme_suresi and dusme_video_yazici is not None:
                    dusme_video_yazici.release()
                    dusme_video_yazici = None
                    self.log_signal.emit("ℹ️ 跌倒事件视频片段记录完毕。")

                kare_tamponu.append(kare.copy())
                self.change_pixmap_signal.emit(kare, current_durus, dusme_video_sayisi, is_falling)

        cap.release()
        if dusme_video_yazici is not None:
            dusme_video_yazici.release()
        self.log_signal.emit(" 视频流已关闭。")


# ==================== 情绪检测线程（基于 YOLOv11 onnx） ====================

EMOTION_CN_MAP = {
    "angry": "愤怒",
    "disgust": "厌恶",
    "fear": "恐惧",
    "fearful": "恐惧",
    "happy": "高兴",
    "sad": "悲伤",
    "surprise": "惊讶",
    "neutral": "平静",
    "calm": "平静",
    "confused": "困惑",
    "contempt": "轻蔑",
}


def _default_emotion_order():
    """默认情绪顺序（若模型本身不带 names 时兜底）。"""
    return ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]


def _resolve_emotion_device():
    """统一决策情绪模型推理设备：CUDA 可用则优先 GPU。"""
    try:
        import torch
        # 兼容 PyInstaller 冻结环境：torch 自带的 CUDA DLL 路径有时不在 PATH 里
        try:
            torch_lib = os.path.join(os.path.dirname(torch.__file__), 'lib')
            if torch_lib and os.path.isdir(torch_lib):
                cur = os.environ.get('PATH', '')
                if torch_lib not in cur:
                    os.environ['PATH'] = torch_lib + os.pathsep + cur
        except Exception:
            pass
        try:
            torch.cuda.init()
        except Exception:
            pass
        if torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            return "cuda:0", True
        else:
            try:
                reason = "未检测到可用 GPU"
                if hasattr(torch.cuda, 'is_built'):
                    if not torch.cuda.is_built():
                        reason = "当前 torch 是 CPU 版本，未编译 CUDA"
                    else:
                        reason = "torch 编译了 CUDA，但系统未检测到驱动或显卡"
            except Exception:
                reason = "未知"
            print(f"[resolve_emotion_device] CUDA 不可用: {reason}", flush=True)
    except ImportError:
        pass
    return "cpu", False


_EMOTION_DEVICE, _EMOTION_HAS_GPU = _resolve_emotion_device()


class EmotionDetectionThread(QThread):
    """独立弹窗使用的情绪检测线程，复用 qingxu/app.py 的 best.onnx 推理流程。"""
    change_pixmap_signal = pyqtSignal(np.ndarray, str, float, dict)
    log_signal = pyqtSignal(str)

    def __init__(self, model_path, source=0):
        super().__init__()
        self.model_path = model_path
        self.source = source
        self.running = True
        self._hard_stop = False
        self._device = "cpu"
        self._class_names_en = _default_emotion_order()
        self._smooth_window = deque(maxlen=15)
        self._emotion_stats = {k: 0 for k in self._class_names_en}
        # 轮询方案：子线程只把帧写到这里（加锁），主线程 QTimer 每 33ms 来取
        self._latest_frame = None
        self._latest_payload = ("--", 0.0, {})
        self._latest_frame_id = 0
        self._frame_lock = threading.Lock()

    def stop(self):
        """硬停止：释放 cap + 退出循环 + 终止线程。"""
        self._hard_stop = True
        self.running = False
        try:
            if hasattr(self, "_cap") and self._cap is not None:
                self._cap.release()
        except Exception:
            pass
        self.wait(3000)

    def pause(self):
        """软暂停：保留 cap，只退出 while，方便后续 resume()。"""
        self._hard_stop = False
        self.running = False

    def resume(self):
        """恢复读取。"""
        self._hard_stop = False
        self.running = True

    def reset_stats(self):
        self._smooth_window.clear()
        self._emotion_stats = {k: 0 for k in self._class_names_en}

    def _sync_labels_from_model(self, model):
        """从真实模型读取类别顺序，避免硬编码和真实数据集不一致。
        ultralytics 11.x: model.names 在不同 task 下可能是 dict{id:str} 或 list[str]，必须兼容。
        """
        try:
            names_raw = getattr(model, "names", None)
            if not names_raw:
                return
            names_en = []
            if isinstance(names_raw, dict):
                for k in sorted(names_raw.keys()):
                    try:
                        names_en.append(str(names_raw[k]).lower())
                    except Exception:
                        continue
            elif isinstance(names_raw, (list, tuple)):
                for n in names_raw:
                    try:
                        names_en.append(str(n).lower())
                    except Exception:
                        continue
            else:
                names_en = [str(names_raw).lower()]
            # 兜底：万一解析后为空
            if not names_en:
                names_en = _default_emotion_order()
            self._class_names_en = names_en
            self._emotion_stats = {k: 0 for k in self._class_names_en}
            self.log_signal.emit(f"情绪类别({len(self._class_names_en)}): {self._class_names_en}")
        except Exception as e:
            self.log_signal.emit(f"️ 读取模型类别名失败: {e}")

    def run(self):
        self.log_signal.emit(f" 正在加载情绪识别模型: {self.model_path}")
        try:
            is_onnx = str(self.model_path).lower().endswith(".onnx")
            try:
                import torch
                if torch.cuda.is_available():
                    self._device = "cuda:0"
                    self.log_signal.emit(f" 使用 GPU 推理: {torch.cuda.get_device_name(0)}")
                else:
                    self._device = "cpu"
                    self.log_signal.emit("️ 未检测到 CUDA，回退到 CPU 推理")
            except ImportError:
                self._device = "cpu"
                self.log_signal.emit("️ 未安装 torch，回退到 CPU 推理")
            model = YOLO(self.model_path, task="detect")
            if self._device != "cpu" and not is_onnx:
                try:
                    model.to(self._device)
                    self.log_signal.emit(f" 情绪模型已搬到 {self._device}")
                except Exception as e:
                    self.log_signal.emit(f" 情绪模型搬设备失败，回退到 CPU: {e}")
                    self._device = "cpu"
            elif is_onnx:
                # ONNX 模型让 ultralytics 自动选 provider（CPU/CUDA），不再 .to() 强制。
                # 不在首帧前访问 model.names，否则会提前创建一次 ONNX Runtime 后端，
                # 随后的 predict 又创建一次，表现为控制台重复打印 Loading。
                self.log_signal.emit(" ONNX 模型已就绪，推理时由 ultralytics 自动选择 provider")
                self._labels_synced = False
            else:
                self._sync_labels_from_model(model)
                self._labels_synced = True
        except Exception as e:
            self.log_signal.emit(f" 情绪模型加载失败: {e}")
            return

        cap_source = int(self.source) if str(self.source).isdigit() else self.source
        is_image = isinstance(cap_source, str) and os.path.splitext(cap_source)[1].lower() in {
            ".png", ".jpg", ".jpeg", ".bmp", ".webp"
        }
        cap = cv2.VideoCapture(cap_source, cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY)
        self._cap = cap
        if not cap.isOpened():
            self.log_signal.emit(f" 无法打开视频源 [{self.source}] 用于情绪检测，请检查摄像头是否被其他程序占用")
            try:
                placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, "Camera unavailable", (140, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (60, 60, 60), 2)
                self.change_pixmap_signal.emit(placeholder, "--", 0.0, {})
            except Exception:
                pass
            return
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        except Exception:
            pass
        try:
            for _ in range(8):
                cap.grab()
        except Exception:
            pass
        # 暖机：反复读帧直到拿到有效画面，最多等 5 秒
        warm_frame = None
        _t_start = time.time()
        while time.time() - _t_start < 5.0:
            try:
                if cap is None or not cap.isOpened():
                    break
                _r, _f = cap.read()
                if _r and _f is not None and isinstance(_f, np.ndarray) and _f.size > 0:
                    warm_frame = _f
                    break
            except Exception:
                pass
            time.sleep(0.05)
        try:
            if warm_frame is not None:
                self.change_pixmap_signal.emit(warm_frame, "推理中...", 0.0, {})
            else:
                black = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(black, "Camera not ready", (170, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 80, 200), 2)
                self.change_pixmap_signal.emit(black, "--", 0.0, {})
        except Exception:
            pass
        self.log_signal.emit(f" 情绪检测视频流已建立 [源={self.source}] 后端=DSHOW 暖机{'成功' if warm_frame is not None else '失败'}")

        last_emit_ts = time.time()

        while not self._hard_stop:
            while not self.running and not self._hard_stop:
                time.sleep(0.05)
            if self._hard_stop:
                break
            if cap is None or not cap.isOpened():
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
                cap = cv2.VideoCapture(cap_source, cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY)
                self._cap = cap
                if not cap.isOpened():
                    self.log_signal.emit(
                        f"⚠ 无法打开视频源 [{self.source}]，请检查摄像头是否被其他程序占用，或换一个源"
                    )
                    time.sleep(0.5)
                    continue

            ret, frame = cap.read()
            if getattr(self, "_hard_stop", False):
                break
            self._heartbeat_n = getattr(self, "_heartbeat_n", 0) + 1
            if self._heartbeat_n % 30 == 0:
                self.log_signal.emit(f"❤ 心跳 #{self._heartbeat_n} frame={frame.shape if frame is not None else None}")
            if not ret or frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                if is_image:
                    if self.running:
                        time.sleep(0.05)
                    continue
                if not str(self.source).isdigit():
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                if time.time() - last_emit_ts > 3:
                    self.log_signal.emit("⚠ 摄像头读取失败，0.3s 后重试…（可能摄像头被独占或驱动异常）")
                    last_emit_ts = time.time()
                try:
                    placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
                    cv2.putText(placeholder, "Waiting for camera...", (160, 180),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (100, 100, 100), 2)
                    self.change_pixmap_signal.emit(placeholder, "--", 0.0, {})
                except Exception:
                    pass
                time.sleep(0.3)
                continue
            last_emit_ts = time.time()

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_3d = cv2.merge([gray, gray, gray])

            # YOLO wrapper 内部自动 letterbox+normalize；直接传原始尺寸即可
            # 模型文件大小确认是 640x640 训练，letterbox 后送网络

            results = None
            _t0 = time.time()
            if getattr(self, "_hard_stop", False):
                break
            if not getattr(self, "running", False):
                continue
            try:
                results = model.predict(gray_3d, verbose=False)
            except Exception as e:
                self.log_signal.emit(f" 情绪推理异常: {type(e).__name__}: {e}")
                import traceback
                self.log_signal.emit(f" traceback: {traceback.format_exc()[:500]}")
            _dt = time.time() - _t0
            if not hasattr(self, "_first_inf_logged"):
                self._first_inf_logged = True
                self.log_signal.emit(f" 首次情绪推理耗时 {_dt*1000:.0f} ms on {self._device} 输入尺寸={gray_3d.shape}")
            elif _dt > 1.0:
                self.log_signal.emit(f" 情绪推理偏慢 {_dt*1000:.0f} ms on {self._device}")

            if results and not getattr(self, "_labels_synced", False):
                self._sync_labels_from_model(results[0])
                self._labels_synced = True

            top_label_en, top_conf, label_dist = self._extract_top_emotion(results)

            annotated = frame
            if results is not None and len(results) > 0:
                try:
                    plotted = results[0].plot()
                    if isinstance(plotted, np.ndarray) and plotted.size > 0:
                        annotated = plotted
                except Exception:
                    pass

            if top_label_en:
                self._smooth_window.append(top_label_en)
                self._emotion_stats[top_label_en] = self._emotion_stats.get(top_label_en, 0) + 1

            smooth_label_en = self._smooth_label()
            smooth_label_cn = EMOTION_CN_MAP.get(smooth_label_en or "", smooth_label_en or "--")
            self._current_emotion_cn = smooth_label_cn

            try:
                if getattr(self, "running", False) and not getattr(self, "_hard_stop", False):
                    frame_to_store = (
                        annotated.copy()
                        if isinstance(annotated, np.ndarray)
                        else np.zeros((360, 640, 3), dtype=np.uint8)
                    )
                    with self._frame_lock:
                        self._latest_frame = frame_to_store
                        self._latest_payload = (smooth_label_cn, float(top_conf), dict(label_dist))
                        self._latest_frame_id = getattr(self, "_latest_frame_id", 0) + 1
            except Exception as e:
                self.log_signal.emit(f" 写帧到缓存异常: {e}")

        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        self._cap = None
        self.log_signal.emit(" 情绪检测视频流已关闭")

    def _extract_top_emotion(self, results):
        """从 YOLOv11 分类结果中提取最高置信度的情绪标签。整段异常都会被吞，绝不抛到 UI 线程。"""
        names = self._class_names_en or _default_emotion_order()
        label_dist = {EMOTION_CN_MAP.get(k, k): 0.0 for k in names if isinstance(k, str)}
        top_label_en = None
        top_conf = 0.0

        if not results:
            return None, 0.0, label_dist

        try:
            result = results[0]
            names_map = getattr(result, "names", {}) or {}

            if hasattr(result, "boxes") and result.boxes is not None and len(result.boxes) > 0:
                boxes = result.boxes
                try:
                    confs = boxes.conf
                    if hasattr(confs, "cpu"):
                        confs = confs.cpu().numpy()
                    confs = np.asarray(confs, dtype=np.float32).flatten()
                except Exception:
                    confs = np.zeros(len(boxes), dtype=np.float32)
                try:
                    cls_ids = boxes.cls
                    if hasattr(cls_ids, "cpu"):
                        cls_ids = cls_ids.cpu().numpy()
                    cls_ids = np.asarray(cls_ids, dtype=np.int64).flatten()
                except Exception:
                    cls_ids = np.zeros(len(boxes), dtype=np.int64)

                if len(cls_ids) == 0:
                    return None, 0.0, label_dist

                best_i = int(np.argmax(confs)) if len(confs) > 0 else 0
                best_conf = float(confs[best_i]) if len(confs) > 0 else 0.0
                cls_id = int(cls_ids[best_i])
                cls_name = None
                if isinstance(names_map, dict):
                    cls_name = names_map.get(cls_id)
                elif isinstance(names_map, (list, tuple)) and 0 <= cls_id < len(names_map):
                    cls_name = names_map[cls_id]
                if cls_name is not None:
                    top_label_en = str(cls_name).lower()
                    top_conf = best_conf

                counts = {EMOTION_CN_MAP.get(k, k): 0.0 for k in names if isinstance(k, str)}
                for cn in counts.keys():
                    counts[cn] = 0.0
                total_score = 0.0
                for ci, cf in zip(cls_ids, confs):
                    name_en = None
                    if isinstance(names_map, dict):
                        name_en = names_map.get(int(ci))
                    elif isinstance(names_map, (list, tuple)) and 0 <= int(ci) < len(names_map):
                        name_en = names_map[int(ci)]
                    if name_en is None:
                        continue
                    cn = EMOTION_CN_MAP.get(str(name_en).lower(), str(name_en).lower())
                    counts[cn] = counts.get(cn, 0.0) + float(cf)
                    total_score += float(cf)
                if total_score > 0:
                    for k in list(counts.keys()):
                        counts[k] = round(counts[k] / total_score, 4)
                for k, v in counts.items():
                    label_dist[k] = v
                return top_label_en, top_conf, label_dist

            if hasattr(result, "probs") and result.probs is not None:
                try:
                    top1_idx = int(result.probs.top1)
                except Exception:
                    top1_idx = -1
                try:
                    top_conf = float(result.probs.top1conf)
                except Exception:
                    top_conf = 0.0
                if 0 <= top1_idx < len(names):
                    candidate = names[top1_idx]
                    if isinstance(candidate, str):
                        top_label_en = candidate
                try:
                    probs_arr = np.asarray(result.probs.data, dtype=np.float32)
                except Exception:
                    probs_arr = np.zeros(len(names), dtype=np.float32)
                for i, cls_en in enumerate(names):
                    if not isinstance(cls_en, str):
                        continue
                    if i < len(probs_arr):
                        try:
                            label_dist[EMOTION_CN_MAP.get(cls_en, cls_en)] = float(probs_arr[i])
                        except Exception:
                            pass
        except Exception:
            pass

        return top_label_en, top_conf, label_dist

    def _smooth_label(self):
        if not self._smooth_window:
            return None
        counts = {}
        for k in self._smooth_window:
            counts[k] = counts.get(k, 0) + 1
        return max(counts, key=counts.get)

    def get_stats_summary(self):
        total = sum(self._emotion_stats.values())
        if total == 0:
            return {}
        return {EMOTION_CN_MAP.get(k, k): round(v / total * 100, 1)
                for k, v in self._emotion_stats.items() if v > 0}

    def get_class_names(self):
        """供 UI 端读取真实类别顺序，外部 dialog 用。"""
        return [EMOTION_CN_MAP.get(k, k) for k in self._class_names_en]