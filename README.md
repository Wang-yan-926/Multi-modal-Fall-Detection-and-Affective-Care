# AI-Vision-Guardian: Multi-modal Fall Detection and Affective Care

> **AI-Vision-Guardian: Multi-modal Fall Detection and Affective Care** — a desktop elderly-care system combining **YOLOv8 + MediaPipe Pose + PyQt6 + MySQL** with **YOLOv11 facial emotion recognition**, **Vosk offline speech recognition**, **Kimi LLM** and **pyttsx3 / SAPI5 Chinese TTS**.
>
> 适用于智慧养老、智能安防、毕业设计等场景；检测结果不应作为医疗诊断或唯一安全决策依据。

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4)
![Python](https://img.shields.io/badge/python-3.8%E2%80%933.11-3776ab)
![License](https://img.shields.io/badge/license-MIT-green)
![Stack](https://img.shields.io/badge/stack-PyQt6%20%7C%20Ultralytics%20%7C%20MediaPipe%20%7C%20MySQL-orange)

---

## ✨ 功能特性

### 🛡️ 核心检测（`deidao/`）
| 能力 | 说明 |
| --- | --- |
| YOLOv8 实时人员检测 | COCO `person` 类，画定位框 |
| MediaPipe Pose 关键点 | 双肩、双髋中点计算**躯干倾角** |
| 三段式姿态识别 | 站立 `< 35°` / 跌倒中 35°~70° / 平躺 `> 70°`（阈值可在设置中调） |
| 前置缓冲区录像 | 跌倒告警自动拼接 N 秒前置视频，存盘至 `result/` |
| MySQL 历史回放 | `alarm_logs` 表可追溯，含家属处理意见 |
| 飞书机器人推送 | 交互卡片实时同步给值班家属 |
| 双角色系统 | 管理员运维端（`root`）/ 家属亲情看护端（`family`） |
| 健康指标大屏 | 心率/血氧/血压/步数/体温/电量（演示数据，可对接硬件） |
| 中文字体自适应 | `msyh.ttc` / `simhei.ttf` 自动回退 |

### 💬 语音 & AI（`deidao/dialogs.py`）
| 能力 | 说明 |
| --- | --- |
| **情绪识别弹窗** | YOLOv11 face model 实时识别 `高兴/悲伤/愤怒/惊讶/中性/恐惧`，可据此调出 AI 诊断建议 |
| **AI 智能问答** | 打字 + 麦克风（Vosk 离线 / Google 在线）双输入 |
| **Kimi 大模型** | 通过环境变量或 `config_kimi.txt` 注入 API Key，自动回退到本地规则模板 |
| **pyttsx3 中文 TTS** | 一次性 init → 用 → 销毁（避免 SAPI5 engine 复用哑火）；逐句可中断，停止按钮 100~300ms 收声 |

### 🧰 工程工具
| 能力 | 说明 |
| --- | --- |
| `tests/manual_diagnosis_smoke.py` | 离屏烟雾测试：弹 `EmotionDetectionDialog` 不弹真实窗口 |
| `tests/stop_all_tts.py` | 紧急停止所有 `pyttsx3` 朗读（TTS 死锁兜底） |
| 模块化拆分 | `main.py / ui_layout.py / dialogs.py / detector.py / database.py` 单一职责 |

---

## 🖼️ 项目结构

```text
AI-Vision-Guardian/
├── deidao/                       # 跌倒检测主系统
│   ├── main.py                   # PyQt6 主程序入口
│   ├── ui_layout.py              # One Dark 风格主界面
│   ├── dialogs.py                # 6 类弹窗 + TTS / 语音 / AI 多线程
│   ├── detector.py               # YOLOv8+MediaPipe 检测线程
│   └── database.py               # MySQL 初始化
├── qingxu/                       # 情绪识别子模块
│   ├── app.py                    # YOLOv11 face emotion 单机 demo
│   └── best.onnx                 # 训练好的情绪识别权重（需自行放置）
├── model/
│   └── vosk-model-small-cn-0.22/ # Vosk 中文模型（首次使用需下载，见下文）
├── tests/                        # 烟雾测试 & 工具
├── video/                        # 示例视频（不入库）
├── result/                       # 告警片段（运行时生成）
├── yolov8n.pt                    # YOLOv8 Nano 权重（需放置）
├── alarm.mp3                     # 告警音频（可替换）
├── requirements.txt              # 一键依赖安装
├── .env.example                  # 环境变量样例（KIMI_API_KEY 等）
├── LICENSE                       # MIT
└── README.md                     # 本说明
```

---

## 🧩 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│  PyQt6 主窗口 (deidao/main.py)                                  │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐             │
│  │ 检测线程     │  │ 情绪识别弹窗  │  │ AI 智能问答   │             │
│  │ (detector)  │  │ (YOLOv11)    │  │ (Vosk+SR)   │             │
│  │ YOLO+Pose   │  │              │  │ + Kimi LLM  │             │
│  └─────┬───────┘  └──────┬───────┘  └──────┬──────┘             │
│        │ 告警事件        │ 情绪           │ AI 回复               │
│        ↓                ↓                ↓                      │
│  ┌──────────────────────────────────────────────────┐           │
│  │ result/xxx.mp4 + MySQL alarm_logs + 飞书 webhook │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  TTS 引擎：pyttsx3 + SAPI5（中文音色）                           │
│   - 每个 worker init → 用 → 销毁（一次性生命周期）                │
│   - 句间可中断，100~300ms 收声                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ 环境要求

| 项 | 要求 |
| --- | --- |
| OS | Windows 10 / 11（SAPI5 仅 Windows，原生支持中文 TTS） |
| Python | 3.8 ~ 3.11 |
| MySQL | 5.7+ / 8.x，本地 `localhost:3306`（若无需数据库可禁用） |
| 硬件 | 摄像头 / 麦克风 / 扬声器（可选） |
| GPU | 可选；CPU 也能跑（建议 RTX 1650 以上） |

---

## 🚀 快速开始

### 1. 克隆与虚拟环境

```bash
git clone https://github.com/<your-username>/AI-Vision-Guardian.git
cd AI-Vision-Guardian

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux（如跨平台调试）
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 下载大文件（不进 Git）

| 文件 | 来源 | 放置位置 |
| --- | --- | --- |
| `yolov8n.pt` | [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) | 项目根目录 |
| `vosk-model-small-cn-0.22` | [Vosk Models](https://alphacephei.com/vosk/models) | `model/vosk-model-small-cn-0.22/` |
| `best.onnx`（情绪识别） | 自训 / 教师模型导出 | `qingxu/best.onnx` |
| `msyh.ttc` 或 `simhei.ttf` | Windows 系统字体 / 自行放置 | 项目根目录 |

> Ultralytics 缺权重时通常会自动下载；Vosk 与 YOLOv11 需手动放置。

### 3. 配置环境变量

```bash
copy .env.example .env
# 编辑 .env，填入 Kimi Key（可选；无 Key 自动回退本地模板）
# KIMI_API_KEY=sk-...
```

也可以把 Key 放进 `deidao/config_kimi.txt`（一行一 key，无空格）。

### 4. （可选）准备 MySQL

启动本地 MySQL，首次运行会自动创建 `fall_detector_db` 数据库与默认账号：

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `root` | `231006410` | 管理员 |
| `family` | `123456` | 家属 |

> 默认密码**仅供本地演示**，正式部署请改用 `os.environ` 注入或加密配置。

### 5. 启动应用

```bash
# 跌倒检测主系统
cd deidao && python main.py

# 情绪识别独立 demo
cd qingxu && python app.py

# 离屏烟雾测试（无需摄像头）
python tests/manual_diagnosis_smoke.py

# TTS 紧急停止（万一朗读卡死）
python tests/stop_all_tts.py
```

---

## 🧪 使用说明

### 管理员运维端

1. 用 `root` 登录
2. 左侧选**摄像头**或**导入视频**
3. 点**启动检测**，观察右侧实时姿态、告警卡片与日志
4. **系统设置**：调节躯干倾角阈值、声音告警、录制前置缓冲、飞书 Webhook
5. **历史片段**：在程序内查看 / 打开 `result/` 目录

### 家属亲情看护端

1. 用 `family` 登录
2. 实时监测可用，但部分参数被锁定
3. **飞书音视频通话**：一键调起飞书客户端
4. **健康大屏**：心率/血氧/血压/步数/体温/电量
5. **历史片段**：可填写处理备注并标记"已处理"

### 情绪识别弹窗（任意角色可用）

1. 启动后调用 YOLOv11 摄像头实时识别情绪
2. 稳定 ≥ 1.5 秒后点 **AI 智能诊断**
3. 系统自动调 Kimi（无 Key 走本地模板）生成关怀建议
4. 自动用 pyttsx3 中文 TTS 朗读（可在 `🔊 语音朗读建议` 复选框关闭）
5. **取消诊断** / **停止朗读** 按钮 100~300ms 内收声

### AI 智能问答

| 输入方式 | 默认引擎 |
| --- | --- |
| 打字 | 直接发送 |
| 麦克风 | Vosk 离线（`model/vosk-model-small-cn-0.22/`） |

回复**默认自动朗读**（`AI 回复自动语音播报` 复选框开启时），可点 `停止朗读` 立刻打断。

---

## 📐 告警与 TTS 链路

```
跌倒检测线程
  └─ "跌倒中" 连续 N 帧
      ├─ 播放 alarm.mp3
      ├─ 写入 result/xxx.mp4（含前置缓冲区）
      ├─ INSERT INTO alarm_logs
      └─ POST 飞书 webhook 交互卡片
                  ↓
        EmotionDetectionDialog._speak_async()
                  ↓
        pyttsx3.init (sapi5) → say/iterate → stop → endLoop → del
        (每个 worker 一次性 init→销毁，SAPI5 不允许 engine 复用)
                  ↓
        主线程点击取消 → set _stop_flag → 100~300ms 内 engine.stop() 收声
```

---

## 🧷 TTS 工程要点

经过实际踩坑，本项目 TTS worker 遵循以下硬性约束（详见 `deidao/dialogs.py`）：

1. **SAPI5 backend 不允许 engine 复用**：第二次 `engine.say()` 经常哑火。每个 worker 一次性 init → 用 → `del`。
2. **绝对不能用 `engine.runAndWait()` 硬阻塞**：那样按"停止"也要等当前句放完。改用 `startLoop(False) + iterate()`，句间轮询 `_stop_flag`，命中即 `engine.stop()`。
3. **绝不在主线程 touch engine**：sapi5 是 apartment-threaded COM，跨 apartment 调用会触发 marshalling 死锁。
4. **主线程只设标志位 `self._stop_flag = True`**，所有 stop/endLoop/del 都在 worker 自己的线程里同步完成。

---

## 🛠️ 常见问题

| 现象 | 排查 |
| --- | --- |
| 主程序启动即 "导入 PyQt6 失败" | `pip install --upgrade PyQt6` |
| 第一次朗读 OK，第二次无声 | 已修复，确保拉到最新 `dialogs.py` |
| AI 弹窗不朗读 | 看 `lbl_tts_status` 状态栏：显示 `TTS 不可用: ...` 则按错误处理 |
| 点"停止朗读"按钮像没生效 | 已用 `startLoop+iterate`，延迟 100~300ms；如仍卡死 → `python tests/stop_all_tts.py` |
| MySQL 连不上 | 检查 `localhost:3306` 服务，确认账号密码与 `.env` |
| Vosk 识别没反应 | 确认 `model/vosk-model-small-cn-0.22/` 存在且为完整解压目录 |
| Kimi 不回复 | 没 Key 自动回退本地规则模板；想看云端回复请配 `KIMI_API_KEY` |
| `torch_cuda.dll 找不到 cudart` | `main.py` 已自动注入 `torch/lib` 到 PATH；保持最新代码即可 |

---

## 🧭 后续可扩展方向

- **硬件联动**：通过 MQTT / TCP 接入智能手环、毫米波雷达
- **多摄像头 / 多人**：将检测逻辑并发化，扩展至 N 路视频
- **云端数据库**：MySQL → 阿里云 / 腾讯云 RDS，支持跨地域家属查看
- **模型升级**：YOLOv8 Pose、RTMPose 等端到姿态估计
- **语音对讲**：集成 WebRTC，跌倒后自动外呼家属
- **本地 LLM**：在 `answer_question()` 接入 Qwen2 / ChatGLM3，不再依赖网络

---

## 🤝 贡献

欢迎 PR / Issue：

1. Fork → 新建分支 (`git checkout -b feature/xxx`)
2. 提交 (`git commit -m "feat: ..."`)
3. 推送 (`git push origin feature/xxx`)
4. 发起 Pull Request

代码风格：PEP 8；关键模块（`dialogs.py` / `detector.py`）请跑 `pytest tests/`。

---

## 📄 许可证

本项目基于 **MIT License** 发布，详见 [LICENSE](LICENSE)。

> ⚠️ 项目内含明文 MySQL / 飞书 Webhook / Kimi Key 占位，**仅供学习演示**。
> 正式部署请使用环境变量 / 密钥管理服务（如 HashiCorp Vault）。
