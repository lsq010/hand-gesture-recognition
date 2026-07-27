# -*- coding: utf-8 -*-
# main.py - 阶段 E：多模态无障碍交流系统（PySide6 GUI 版）
#
# UI 界面参考原有的 rec.ui / rec.py（直接复用 Ui_Form，保持原有深色仪表盘风格），
# 并在右侧面板扩展：
#   - 📦 环境感知 (YOLO)：实时显示识别到的物品
#   - 💬 与 Kimi 对话：聊天历史 + 键盘输入框 + 发送/语音按钮
# 这样既能实时展示手势/物品，又能通过键盘输入文字与 Kimi 进行交流。

import os
import sys
import time
import threading
import tempfile
import uuid

import cv2

from PySide6.QtWidgets import (
    QApplication, QWidget, QGroupBox, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem,
    QTabWidget, QDialog, QScrollArea, QFrame, QMessageBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QTextCursor

# 复用原有 rec.ui 生成的界面结构
try:
    from rec import Ui_Form
except ImportError:
    Ui_Form = None

# ---- 重型模块延迟加载（懒加载） ----
# 程序启动只加载 PySide6 / numpy / cv2 / database 等轻量依赖，窗口秒出；
# 真正的模型（MediaPipe Hands / YOLO-World / whisper / pygame mixer）延迟到
# 「打开摄像头」时由 CameraInitWorker 后台线程首次 import + 实例化，UI 不冻结。
# 这样可把启动耗时从 ~11s 降到 ~2s。
VisionEngine = None
SequenceTracker = None
ObjectDetector = None
# llm_client 仅依赖 openai（轻量），启动时立即导入，
# 这样用户无需打开摄像头即可在「系统设置」粘贴 Key 并与 Kimi 对话。
# 其余重物（MediaPipe / YOLO-World / whisper / pygame）仍延迟到
# CameraInitWorker 后台线程首次 import，保证启动 ~2s 不卡。
try:
    from llm_client import KimiLLMClient
except Exception as _llm_err:  # noqa: BLE001
    KimiLLMClient = None
    print(f">>> [LLM] llm_client 模块不可用，Kimi 对话将关闭: {_llm_err}")

# 切水果小游戏平台（纯 Qt + cv2，无外部依赖）
try:
    from fruit_game import GameHubWidget, FruitSliceController
except Exception as _game_err:  # noqa: BLE001
    GameHubWidget = None
    FruitSliceController = None
    print(f">>> [Game] fruit_game 模块不可用: {_game_err}")
ASRManager = None
TTSManager = None
try:
    from database import (
        init_db, get_all_settings, save_setting,
        insert_log, get_logs, clear_logs, get_signs, insert_sign,
    )
    init_db()  # 幂等建表（logs / settings / sign_dictionary）
    HAS_DB = True
except Exception as _db_err:  # noqa: BLE001
    HAS_DB = False
    print(f">>> [DB] database 模块不可用，历史记录/配置持久化关闭: {_db_err}")


def _as_text(en_label, zh_name):
    """把英文标签 + 中文名拼成 '名称（含义）'；无含义时只返回名称。"""
    if not zh_name:
        return None
    m = GESTURE_MEANING.get(en_label, "")
    return f"{zh_name}（{m}）" if m else zh_name


# 手势英文标签 -> 中文（与 vision_engine / sequence_tracker 输出对齐）
GESTURE_ZH = {
    "Fist": "握拳",
    "OK": "OK/确认",
    "Pointing": "指向",
    "Num_1": "数字1",
    "Num_2": "数字2",
    "Num_3": "数字3",
    "Num_4": "数字4",
    "Num_5": "数字5",
    "Unknown": "未知",
    "None": "无",
    "ThumbUp": "点赞",
    "ThumbDown": "拇指向下",
    "FingerHeart": "比心",
    "Phone": "打电话",
    # 动态手语（SequenceTracker 输出）
    "Wave": "挥手/再见",
    "Circle": "画圈",
    "Swipe_Left": "向左划",
    "Swipe_Right": "向右划",
    "Swipe_Up": "向上划",
    "Swipe_Down": "向下划",
}

# 手势英文标签 -> 语义含义（与"之前的含义"对照表对齐）
GESTURE_MEANING = {
    "Fist": "坚持 / 加油 / 力量 / 团结",
    "OK": "好的 / 确定 / 没问题",
    "Pointing": "指示方向 / 指向某物",
    "Heart": "表达爱意 / 感谢（大）",
    "Num_1": "提示注意 / 稍等一下 / 数字1",
    "Num_2": "胜利 / 和平 / 数字2",
    "Num_3": "数字3",
    "Num_4": "数字4",
    "Num_5": "停止 / 拒绝 / 稍等",
    "ThumbUp": "赞赏 / 棒 / 同意 / 没问题 / 搞定",
    "ThumbDown": "差劲 / 反对 / 不同意 / 否定",
    "FingerHeart": "爱你 / 喜欢 / 感谢（小）",
    "Phone": "联系我 / 打电话 / 呼叫",
    "Victory": "胜利 / 和平 / 数字2",
    "OpenPalm": "停止 / 拒绝 / 稍等",
    "PointUp": "提示注意 / 稍等一下 / 数字1",
    "Shush": "保持安静 / 闭嘴 / 保密",
    "CallMe": "给我打电话 / 放松 / 酷",
    "LoveYou": "表达爱意 / 感谢",
}


def _merge_gesture(static_g, dyn_g):
    """动态手语优先于静态手势；返回中文标签或 None。"""
    if dyn_g and dyn_g != "None":
        return GESTURE_ZH.get(dyn_g, dyn_g)
    if static_g and static_g not in ("None", "Unknown"):
        return GESTURE_ZH.get(static_g, static_g)
    return None


def cv2_to_pixmap(frame, target_w, target_h):
    """把 OpenCV BGR 帧转成可缩放显示的 QPixmap。"""
    if frame is None:
        return QPixmap()
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
    pix = QPixmap.fromImage(qimg)
    tw = max(2, target_w)
    th = max(2, target_h)
    return pix.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class _KeyTestWorker(QThread):
    """在子线程里向 Moonshot 发最小请求，验证 Key 是否可用。
    - result(ok: bool, message: str)：ok=True 时 message 是模型回复；ok=False 时是错误原因。
    """

    result = Signal(bool, str)

    def __init__(self, api_key: str, parent=None):
        super().__init__(parent)
        self.api_key = api_key

    def run(self):
        try:
            if KimiLLMClient is None:
                self.result.emit(False, "llm_client 模块不可用")
                return
            client = KimiLLMClient(api_key=self.api_key)
            # 探测方式：调 models.list() 拿可用模型列表 —— 这是元数据 API，
            # 不触发聊天模型冷启动，通常 300-800ms 内返回。比 chat.completions 快 10×。
            try:
                models = client.client.models.list(timeout=8)
                n = len(models.data) if hasattr(models, "data") else 0
                self.result.emit(True, f"通过（元数据 API，可访问 {n} 个模型）")
            except Exception as e_meta:  # noqa: BLE001
                # 元数据 API 失败但仍想确认网络通：降级到一次极小聊天（用稳定的 moonshot-v1-8k）
                status = getattr(e_meta, "status_code", None)
                if status == 401 or "Invalid Authentication" in str(e_meta) or "invalid_api_key" in str(e_meta).lower():
                    self.result.emit(False, f"401 认证失败 — Key 不正确或已被撤销（{str(e_meta)[:80]}）")
                    return
                try:
                    resp = client.client.chat.completions.create(
                        model="moonshot-v1-8k",  # 比 kimi-latest 快得多，无冷启动
                        messages=[{"role": "user", "content": "ping"}],
                        temperature=0,
                        max_tokens=4,
                        timeout=8,
                    )
                    text = (resp.choices[0].message.content or "").strip() or "(空)"
                    self.result.emit(True, f"通过（聊天 API，回 \"{text[:20]}\"）")
                except Exception as e_chat:  # noqa: BLE001
                    # 把 meta + chat 两个异常合并诊断
                    msg_chat = str(e_chat)
                    st_chat = getattr(e_chat, "status_code", None) or (
                        getattr(getattr(e_chat, "response", None), "status_code", None)
                        if getattr(e_chat, "response", None) is not None else None
                    )
                    if st_chat == 401 or "Invalid Authentication" in msg_chat or "invalid_api_key" in msg_chat.lower():
                        self.result.emit(False, f"401 认证失败 — Key 不正确或已被撤销（{msg_chat[:80]}）")
                    elif st_chat == 429 or "rate limit" in msg_chat.lower() or "insufficient_quota" in msg_chat.lower():
                        self.result.emit(False, f"429 限流/配额不足（{msg_chat[:80]}）")
                    else:
                        self.result.emit(False, f"{st_chat or '网络/未知'} — {msg_chat[:160]}")
        except Exception as e:  # noqa: BLE001
            # 最外层兜底：任何未预期异常都安全返回
            self.result.emit(False, f"未预期错误：{str(e)[:160]}")


class CameraInitWorker(QThread):
    """后台线程分两阶段初始化多模态组件，避免「打开摄像头」要等最重的 YOLO-World
    加载完才出画面（之前会卡 5~8 秒）：

    - 阶段1（快速）：打开摄像头 + MediaPipe + 手势轨迹器 → cam_ready，画面立即可用；
    - 阶段2（重）：YOLO-World 物体检测 / ASR / TTS / Kimi → extras_ready，后台继续加载，
      不阻塞画面显示。用户在「物体检测/语音」就绪前就能看到手势画面并操作。
    """

    cam_ready = Signal(object, object, object)                 # vision, cap_fallback, tracker
    extras_ready = Signal(object, object, object, object)      # obj, llm, tts, asr
    failed = Signal(str)

    def __init__(self, api_key=""):
        super().__init__()
        self.api_key = api_key or ""

    def run(self):
        # 在后台线程首次导入重型依赖（启动阶段不导入，避免 ~11s 卡顿）。
        # 这些 import 失败则保持 None，下方逻辑走兜底分支。
        global VisionEngine, SequenceTracker, ObjectDetector, KimiLLMClient, TTSManager, ASRManager

        # ---- 阶段1：摄像头 + 手势（轻量，尽快出画面） ----
        try:
            from vision_engine import VisionEngine as _VE
            VisionEngine = _VE
        except Exception as e:  # noqa: BLE001
            print(f">>> [B] vision_engine 导入失败: {e}")
            VisionEngine = None
        try:
            from sequence_tracker import SequenceTracker as _ST
            SequenceTracker = _ST
        except Exception as e:  # noqa: BLE001
            SequenceTracker = None

        vision = None
        cap_fallback = None
        tracker = None
        try:
            if VisionEngine is not None:
                try:
                    vision = VisionEngine(camera_index=0)
                except Exception as e:  # noqa: BLE001
                    print(f">>> [B] VisionEngine 初始化失败: {e}")
                    vision = None
            if vision is None:
                try:
                    cap_fallback = cv2.VideoCapture(0)
                except Exception:  # noqa: BLE001
                    cap_fallback = None
            if SequenceTracker is not None:
                tracker = SequenceTracker(max_length=48, missing_grace=8)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return

        # 摄像头完全打不开（无设备/被占用）→ 直接失败，不再后台加载重物
        if vision is None and cap_fallback is None:
            self.failed.emit("无法打开摄像头（cv2.VideoCapture 失败，请检查设备/权限）")
            return

        # 立即通知主线程：摄像头已开，画面可以显示了（此时 obj/llm/tts/asr 仍为 None）
        self.cam_ready.emit(vision, cap_fallback, tracker)

        # ---- 阶段2：重组件（YOLO-World / ASR / TTS / Kimi）后台继续 ----
        obj = llm = tts = asr = None
        try:
            from object_detector import ObjectDetector as _OD
            ObjectDetector = _OD
        except Exception as e:  # noqa: BLE001
            print(f">>> [B] object_detector 导入失败: {e}")
            ObjectDetector = None
        try:
            if ObjectDetector is not None:
                obj = ObjectDetector()
        except Exception as e:  # noqa: BLE001
            print(f">>> [B] ObjectDetector 初始化失败: {e}")
            obj = None

        try:
            from llm_client import KimiLLMClient as _KL
            KimiLLMClient = _KL
        except Exception as e:  # noqa: BLE001
            KimiLLMClient = None
        try:
            if KimiLLMClient is not None and self.api_key:
                llm = KimiLLMClient(api_key=self.api_key)
        except Exception as e:  # noqa: BLE001
            print(f">>> [B] KimiLLMClient 初始化失败: {e}")
            llm = None

        try:
            from asr_tts import ASRManager as _AM, TTSManager as _TM
            ASRManager = _AM
            TTSManager = _TM
        except Exception as e:  # noqa: BLE001
            ASRManager = None
            TTSManager = None
        try:
            if TTSManager is not None:
                tts = TTSManager()
        except Exception as e:  # noqa: BLE001
            print(f">>> [B] TTSManager 初始化失败: {e}")
            tts = None
        try:
            if ASRManager is not None:
                asr = ASRManager(model_size="tiny")
        except Exception as e:  # noqa: BLE001
            print(f">>> [B] ASRManager 初始化失败: {e}")
            asr = None

        self.extras_ready.emit(obj, llm, tts, asr)


class ChatWorker(QThread):
    """在子线程里调用 Kimi 进行对话，避免阻塞 UI。

    Kimi 只做普通对话交流：直接回答用户输入的问题，
    不再做「手势+物体+语音 → 一句话」的多模态润色。
    """

    done = Signal(str, str)   # reply_text, intent
    error = Signal(str)

    def __init__(self, llm, text):
        super().__init__()
        self.llm = llm
        self.text = text

    def run(self):
        try:
            if self.llm is None:
                self.done.emit("（LLM 客户端未配置，请到「系统设置」保存 API Key）", "Error")
                return
            res = self.llm.chat(text=self.text)
            self.done.emit(
                res.get("text", ""),
                res.get("intent", "对话"),
            )
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        if Ui_Form is None:
            raise RuntimeError("rec.Ui_Form 未找到，无法加载界面")
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        # ---- 业务状态 ----
        self.vision = None
        self.obj = None
        self.tracker = None
        self.llm = None
        self.tts = None
        self.asr = None
        self.cap_fallback = None

        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)

        self.current_gestures = []
        self.current_objects = []
        self._running = False
        # 含义区是否处于"实时拼接"模式（Kimi 回复覆盖 3 秒后自动回退）
        self._chat_meaning_expire = 0.0  # time.time() 时间戳；0 表示未被 Kimi 覆盖
        self._last_tick = time.time()
        self._fps = 0.0
        self.db_settings = {}          # 从 settings 表加载的配置
        self._pending_log_ctx = None   # 发送时捕获的上下文，供完成后入库

        self._build_extra_panels()
        self._wire_controls()
        self._init_database()

        self.setWindowTitle("AI 手势识别系统 · 多模态无障碍交流")
        self.statusBar_show("系统就绪 | 点击「打开摄像头」开始")
        # 顶部 API Key 告警条在窗口打开时就显示（llm 还没初始化 → 走本地规则提示）
        self._update_api_key_alert()

    # ------------------------------------------------------------------ #
    #  界面扩展：把右侧 7 个卡片拆为 3 Tab + 顶部「帮助 / 告警」条
    # ------------------------------------------------------------------ #
    def _build_extra_panels(self):
        right = self.ui.rightPanelLayout

        # === 0) 保持 rec.ui 原有左右布局比例 ===
        # camFrame 原本是 Expanding，不能额外设置最小宽度；否则右侧提示条会把
        # 窗口最小宽度撑大，启动时出现文字挤压或控件遮盖。

        # === 1) 先把 rec.ui 默认塞进 rightPanelLayout 的 4 个 GroupBox 全部取出 ===
        taken_widgets = []
        while right.count():
            item = right.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                taken_widgets.append(w)

        # 按对象身份分桶（不依赖标题文本，避免 ui 里改了文案就对不上）
        control_g = self.ui.controlGroup
        result_g = self.ui.resultGroup
        display_g = self.ui.displayGroup
        record_g = self.ui.recordGroup

        # === 2) 顶部：❓ 帮助按钮 + API Key 告警条（不再遮挡数据记录） ===
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.helpButton = QPushButton("❓ 使用手册 / 快捷键")
        self.helpButton.setToolTip("点击查看快捷键、系统介绍、技术栈")
        self.helpButton.setCursor(Qt.PointingHandCursor)
        self.helpButton.setStyleSheet(
            "QPushButton { padding: 6px 12px; font-weight: bold; }"
        )
        top_row.addWidget(self.helpButton)

        top_row.addStretch(1)

        self.apiKeyAlert = QLabel("")
        self.apiKeyAlert.setTextFormat(Qt.PlainText)
        self.apiKeyAlert.setStyleSheet(
            "color: #2b2200; background-color: #ffd54a;"
            "border: 1px solid #b58900; border-radius: 4px;"
            "padding: 3px 4px; font-size: 11px; font-weight: bold;"
            "font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
        )
        # 固定提示条宽度，避免缺少 Key / 已配置两种状态切换时改变布局；
        # 不换行，确保完整文案不会被自身高度裁掉。
        self.apiKeyAlert.setFixedWidth(270)
        self.apiKeyAlert.setWordWrap(False)
        self.apiKeyAlert.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # 创建后立即刷新一次告警条（之前是在 _init_database 之前调用，那时标签还不存在，被 safe-return 掉了）
        self._update_api_key_alert()
        self.apiKeyAlert.setVisible(False)  # 默认隐藏，初始化 LLM 后再决定
        top_row.addWidget(self.apiKeyAlert, stretch=1)

        right.addLayout(top_row)

        # === 3) QTabWidget 三个标签页 ===
        self.rightTabs = QTabWidget()
        self.rightTabs.setDocumentMode(True)
        self.rightTabs.setStyleSheet(
            "QTabBar::tab {"
            "  padding: 8px 16px; font-weight: bold;"
            "  font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
            "}"
            "QTabBar::tab:selected {"
            "  color: #4a9eff; border-bottom: 2px solid #4a9eff;"
            "}"
        )

        # --- Tab 1：💬 Kimi 对话（演示 / 键盘 / 语音交流） ---
        tab_chat = QWidget()
        tab_chat_layout = QVBoxLayout(tab_chat)
        tab_chat_layout.setContentsMargins(4, 8, 4, 4)
        tab_chat_layout.setSpacing(8)

        # Kimi 对话组（保留旧属性，供 send_chat / voiceButton 等使用）
        self.chatGroup = QGroupBox("💬 与 Kimi 对话（键盘输入）")
        chat_layout = QVBoxLayout(self.chatGroup)

        self.chatHistory = QTextEdit()
        self.chatHistory.setReadOnly(True)
        self.chatHistory.setStyleSheet(
            "background-color: #151515; color: #f0f0f0; border: 1px solid #333;"
        )
        chat_layout.addWidget(self.chatHistory)

        input_row = QHBoxLayout()
        self.chatInput = QLineEdit()
        self.chatInput.setPlaceholderText("输入文字，回车或点「发送」与 Kimi 交流…")
        self.sendButton = QPushButton("发送")
        self.voiceButton = QPushButton("🎤 语音")
        input_row.addWidget(self.chatInput, stretch=3)
        input_row.addWidget(self.sendButton, stretch=1)
        input_row.addWidget(self.voiceButton, stretch=1)
        chat_layout.addLayout(input_row)

        tab_chat_layout.addWidget(self.chatGroup, stretch=3)

        tab_chat_layout.addStretch(1)
        self.rightTabs.addTab(tab_chat, "💬 Kimi 对话")

        # --- Tab 2：🎯 实时监测（手势 + 环境） ---
        tab_live = QWidget()
        tab_live_layout = QVBoxLayout(tab_live)
        tab_live_layout.setContentsMargins(4, 8, 4, 4)
        tab_live_layout.setSpacing(8)

        # 原实时识别结果（保持原属性，self.ui.xxx 直接可用）
        tab_live_layout.addWidget(result_g)

        # 环境感知 (YOLO) 组
        self.envGroup = QGroupBox("📦 环境感知 (YOLO)")
        env_layout = QVBoxLayout(self.envGroup)
        self.envLabelValue = QLabel("无")
        self.envLabelValue.setStyleSheet(
            "color: #4a9eff; font-weight: bold; "
            "font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
        )
        self.envLabelValue.setWordWrap(True)
        env_layout.addWidget(self.envLabelValue)
        tab_live_layout.addWidget(self.envGroup)

        tab_live_layout.addStretch(1)
        self.rightTabs.addTab(tab_live, "🎯 实时监测")

        # --- Tab 3：📜 识别历史（数据库 logs 表 · 独立一页） ---
        tab_history = QWidget()
        tab_history_layout = QVBoxLayout(tab_history)
        tab_history_layout.setContentsMargins(4, 8, 4, 4)
        tab_history_layout.setSpacing(8)

        self.historyGroup = QGroupBox("📜 识别历史记录 (数据库)")
        hist_layout = QVBoxLayout(self.historyGroup)
        self.historyTable = QTableWidget(0, 4)
        self.historyTable.setHorizontalHeaderLabels(["时间", "手势", "物体", "翻译文本"])
        self.historyTable.setStyleSheet(
            "background-color:#151515; color:#f0f0f0; gridline-color:#333;"
        )
        self.historyTable.setEditTriggers(QTableWidget.NoEditTriggers)
        self.historyTable.setSelectionBehavior(QTableWidget.SelectRows)
        self.historyTable.horizontalHeader().setStretchLastSection(True)
        # 自动滚动到底部：默认让最近一次记录可见
        sb = self.historyTable.verticalScrollBar()
        sb.setValue(sb.maximum())
        hist_layout.addWidget(self.historyTable, stretch=1)
        hist_btn_row = QHBoxLayout()
        self.refreshHistButton = QPushButton("刷新历史")
        self.refreshHistButton.clicked.connect(self._refresh_history)
        self.exportHistButton = QPushButton("导出 CSV")
        self.exportHistButton.clicked.connect(self._export_history_csv)
        hist_btn_row.addWidget(self.refreshHistButton)
        hist_btn_row.addWidget(self.exportHistButton)
        hist_btn_row.addStretch(1)
        hist_layout.addLayout(hist_btn_row)
        tab_history_layout.addWidget(self.historyGroup, stretch=1)

        self.rightTabs.addTab(tab_history, "📜 识别历史")

        # --- Tab 4：⚙ 系统设置（控制 / 显示 / 记录） ---
        tab_sys = QWidget()
        tab_sys_layout = QVBoxLayout(tab_sys)
        tab_sys_layout.setContentsMargins(4, 8, 4, 4)
        tab_sys_layout.setSpacing(8)

        tab_sys_layout.addWidget(control_g)
        tab_sys_layout.addWidget(display_g)
        tab_sys_layout.addWidget(record_g)

        # === 🔑 API 与配置（持久化到 settings 表） ===
        cfg_group = QGroupBox("🔑 API 与配置")
        cfg_layout = QVBoxLayout(cfg_group)
        cfg_layout.setSpacing(6)
        self.apiKeyEdit = QLineEdit()
        self.apiKeyEdit.setPlaceholderText("粘贴 Moonshot API Key（仅本会话有效，重启后需重新输入）")
        self.apiKeyEdit.setEchoMode(QLineEdit.Password)
        self.apiKeyEdit.setStyleSheet(
            "background-color:#151515; color:#f0f0f0; border:1px solid #333;"
        )
        cfg_layout.addWidget(self.apiKeyEdit)
        cfg_btn_row = QHBoxLayout()
        self.saveConfigButton = QPushButton("保存配置")
        self.saveConfigButton.clicked.connect(self._save_config)
        cfg_btn_row.addWidget(self.saveConfigButton)
        cfg_btn_row.addStretch(1)
        cfg_layout.addLayout(cfg_btn_row)
        tab_sys_layout.addWidget(cfg_group)

        tab_sys_layout.addStretch(1)
        self.rightTabs.addTab(tab_sys, "⚙ 系统设置")

        # ── 🎮 小游戏 Tab ──
        if GameHubWidget is not None and FruitSliceController is not None:
            self.game_hub = GameHubWidget()
            self.game_controller = FruitSliceController(parent=self)
            # 游戏按钮回调
            self.game_hub.on_start = self._on_game_start
            self.game_hub.on_pause = self._on_game_pause
            self.game_hub.on_end = self._on_game_end
            # 控制器信号 → UI 更新
            self.game_controller.score_changed.connect(self.game_hub.update_score)
            self.game_controller.lives_changed.connect(self.game_hub.update_lives)
            self.game_controller.time_changed.connect(self.game_hub.update_time)
            self.game_controller.state_changed.connect(self.game_hub.set_game_state)
            self.game_controller.game_over.connect(self._on_game_over)
            self.rightTabs.addTab(self.game_hub, "🎮 小游戏")
        else:
            tab_game = QWidget()
            tab_game_layout = QVBoxLayout(tab_game)
            tab_game_layout.addWidget(QLabel("小游戏模块加载失败，请检查 fruit_game.py"))
            self.rightTabs.addTab(tab_game, "🎮 小游戏")

        right.addWidget(self.rightTabs, stretch=1)

        # 默认进入「系统设置」Tab；开摄像头时自动切到「实时监测（手势含义）」
        self.rightTabs.setCurrentIndex(3)
        # 切到「识别历史」Tab 时，自动把表格滚到最底部，让最新一条可见
        self.rightTabs.currentChanged.connect(self._on_tab_changed)

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    #  数据库集成：启动加载配置 / 种子手势词典 / 同步显示开关
    # ------------------------------------------------------------------ #
    def _init_database(self):
        """数据库模块的启动钩子（HAS_DB 为 False 时全部降级为 no-op）。"""
        if not HAS_DB:
            return
        # 1) 读取全部配置到内存
        try:
            self.db_settings = get_all_settings()
        except Exception as e:  # noqa: BLE001
            print(f">>> [DB] 读取 settings 失败: {e}")
            self.db_settings = {}

        # 2) 手势含义词典：首次运行把硬编码默认值种入 sign_dictionary，
        #    之后以数据库为准（允许用户/后续 UI 修改含义）。
        try:
            if not get_signs():
                for en_key, meaning in GESTURE_MEANING.items():
                    insert_sign(gesture_name=en_key, sign_word=meaning)
            for row in get_signs():
                GESTURE_MEANING[row["gesture_name"]] = row["sign_word"]
        except Exception as e:  # noqa: BLE001
            print(f">>> [DB] 手势词典同步失败: {e}")

        # 3) 把已保存的显示开关应用到 UI，并让开关变化即落库
        sk = self.db_settings.get("draw_skeleton")
        if sk is not None:
            self.ui.drawSkeletonCheck.setChecked(
                sk.lower() in ("1", "true", "yes")
            )
        mk = self.db_settings.get("mirror")
        if mk is not None:
            self.ui.mirrorCheck.setChecked(mk.lower() in ("1", "true", "yes"))
        self.ui.drawSkeletonCheck.toggled.connect(
            lambda v: save_setting("draw_skeleton", "1" if v else "0", "绘制手部骨架")
        )
        self.ui.mirrorCheck.toggled.connect(
            lambda v: save_setting("mirror", "1" if v else "0", "画面镜像")
        )

        # 4) API Key 仅活在内存：每次启动清空输入框 + 清掉 DB 历史残留 + 忽略 env
        #    要求：每次打开都"干净"，必须由用户在本会话自行粘贴 Key
        self.api_key = ""
        try:
            # 把之前误持久化的 kimi_api_key 置空/删除，保证 DB 也是干净的
            save_setting("kimi_api_key", "", "Moonshot API Key（仅会话有效，重启即清空）")
            self.db_settings["kimi_api_key"] = ""
        except Exception:  # noqa: BLE001
            pass
        self.apiKeyEdit.clear()
        self.apiKeyEdit.setPlaceholderText(
            "粘贴 Moonshot API Key（仅本会话有效，重启后需重新输入）"
        )

        # 5) 初次刷新历史列表
        self._refresh_history()

    def _check_kimi_key_or_prompt(self) -> bool:
        """Kimi 交流前的 Key 自检。
        - 只有本次会话内用户在「系统设置」粘贴并保存的 self.api_key（≥ 20 字符）才算"已配置"。
        - 故意忽略环境变量 MOONSHOT_API_KEY 与数据库：保证每次启动都是干净状态，
          必须由用户自行粘贴 Key 才能跟 Kimi 对话。env 仍可供 test_phase_d 等
          直接调用 llm_client 的脚本使用。
        - 未配 self.api_key → 弹窗问用户是否去设置。
            * 选「去配置」→ 跳到「系统设置」Tab 并把焦点给到 API Key 输入框，返回 False。
            * 选「取消」→ 返回 False（不发送）。
        调用方：send_chat() 在发送按钮 / 回车 / 语音转写 → send_chat 前调用。
        """
        # 1) 只看本次会话内 self.api_key（用户在系统设置里粘贴 + 保存的 key）
        session_key = (getattr(self, "api_key", "") or "").strip().strip('"\'').strip()
        user_configured = (len(session_key) >= 20)
        if user_configured:
            return True

        # 2) 状态文案
        env_key = os.environ.get("MOONSHOT_API_KEY", "").strip().strip('"\'').strip()
        if KimiLLMClient is None:
            status = "llm_client 模块不可用"
        elif env_key:
            # 检测到环境变量残留，提醒用户去清理（GUI 不会自动放行）
            status = (
                "本次会话尚未粘贴 Moonshot Key "
                f"（检测到环境变量 MOONSHOT_API_KEY 残留，长度 {len(env_key)}，"
                "但 GUI 不读取 env；真机 PowerShell `Remove-Item Env:MOONSHOT_API_KEY` 可清理）"
            )
        else:
            status = "未配置（请到「系统设置」→「🔑 API 与配置」粘贴 Key 后点「保存配置」，重启后会失效）"

        # 3) 弹窗引导
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("未配置 Moonshot API Key")
        box.setText(
            "<h3 style='margin-top:0;'>与 Kimi 交流需要 API Key</h3>"
            f"<p>当前状态：<b style='color:#c62828;'>{_esc(status)}</b></p>"
            "<p>是否现在去「系统设置」添加？"
            "<br/><span style='color:#888; font-size:12px;'>"
            "（获取方式：登录 Moonshot 开放平台 → 控制台 → API Keys）</span></p>"
        )
        go_btn = box.addButton("去配置", QMessageBox.AcceptRole)
        cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(go_btn)
        box.exec()
        if box.clickedButton() is not go_btn:
            # 用户取消
            self.chatHistory.append(
                "<span style='color:#ff9800;'>⚠ 已取消：未配置 API Key，无法与 Kimi 交流。"
                "请到「系统设置」→「🔑 API 与配置」中粘贴 Key 后再试。</span>"
            )
            return False

        # 4) 跳转到系统设置 Tab + 焦点给输入框 + 改 placeholder 提示
        if hasattr(self, "rightTabs"):
            self.rightTabs.setCurrentIndex(3)  # 系统设置 Tab
        if hasattr(self, "apiKeyEdit"):
            self.apiKeyEdit.setPlaceholderText(
                "👉 请在这里粘贴 Moonshot API Key（sk-…），然后点「保存配置」"
            )
            self.apiKeyEdit.setFocus()
        self.statusBar_show("请在「系统设置」中粘贴 Moonshot API Key，然后点「保存配置」")
        return False

    def _save_config(self):
        """把 API Key 存到内存（self.api_key），重启即清空。
        故意不写入数据库——按用户要求，每次打开应用都是干净状态，必须自行输入 Key。

        保存前自动检测 Key 是否可用：
        - Key 为空 → 直接保存（清除配置）
        - Key 检测通过 → 保存
        - Key 检测 401 → 不保存，提示「Key 错误」
        - Key 检测其他异常 → 询问是否仍要保存
        """
        if KimiLLMClient is None:
            self.statusBar_show("llm_client 模块不可用，无法保存配置")
            return
        key = self.apiKeyEdit.text().strip().strip('"\'').strip()

        # Key 为空 → 直接清除配置
        if not key:
            self.api_key = ""
            self.llm = KimiLLMClient(api_key="")
            self._update_api_key_alert()
            self.statusBar_show("⚠ Key 已清空，Kimi 对话将关闭")
            return

        # Key 长度异常 → 提示但不保存
        if len(key) < 20:
            QMessageBox.warning(
                self,
                "Key 长度异常",
                f"当前 Key 仅 {len(key)} 个字符，正常 Moonshot Key 通常 ≥ 30 字符。\n"
                "可能是复制时被截断，或夹带了多余字符。",
            )
            return

        # 保存前先检测 Key 是否可用（复用 _KeyTestWorker 子线程）
        self._pending_save_key = key

        self.saveConfigButton.setEnabled(False)
        self._save_btn_original_text = self.saveConfigButton.text()
        self.saveConfigButton.setText("💾 检测中...")
        self.statusBar_show("正在检测 Key 是否可用，通过后自动保存...")

        self._test_kimi_thread = _KeyTestWorker(key, parent=self)
        self._test_kimi_thread.result.connect(self._on_kimi_key_tested)
        self._test_kimi_thread.finished.connect(
            lambda: (
                self.saveConfigButton.setEnabled(True),
                self.saveConfigButton.setText(getattr(self, "_save_btn_original_text", "保存配置")),
            )
        )
        self._test_kimi_thread.start()

    def _on_kimi_key_tested(self, ok: bool, message: str):
        """保存配置时子线程检测 Key 的回调。
        - ok=True  → Key 可用，存入内存，弹「✅ 保存成功」
        - ok=False + 401 → Key 错误，不保存，弹「❌ Key 错误」+ 失败原因
        - ok=False + 其他 → 网络/限流等临时问题，询问是否仍要保存
        """
        if ok:
            key = self._pending_save_key
            self.api_key = key
            self.llm = KimiLLMClient(api_key=key)
            self._update_api_key_alert()
            print(f">>> [Kimi] 已保存到当前会话，Key 长度={len(key)}")
            self.statusBar_show("✅ Key 可用，已保存到当前会话（重启后需重新输入）")
            QMessageBox.information(
                self,
                "✅ Key 可用，保存成功",
                f"Key 检测通过，已保存到当前会话！\n\n服务器返回：{message}",
            )
            return

        # 失败：判断是否 401 认证错误（Key 本身不对）
        is_auth_error = (
            "401" in message
            or "认证失败" in message
            or "invalid_api_key" in message.lower()
        )

        if is_auth_error:
            QMessageBox.critical(
                self,
                "❌ Key 错误",
                f"Key 不可用，未保存。\n\n失败原因：{message}\n\n"
                "请检查 Key 是否正确后重新输入，再点「保存配置」。",
            )
            self.statusBar_show(f"❌ Key 错误，未保存: {message}")
        else:
            # 非 401（网络/限流等临时问题）：询问是否仍要保存
            reply = QMessageBox.question(
                self,
                "Key 检测异常",
                f"Key 检测未通过，但可能是网络或限流等临时问题。\n\n"
                f"失败原因：{message}\n\n"
                "是否仍要保存此 Key？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                key = self._pending_save_key
                self.api_key = key
                self.llm = KimiLLMClient(api_key=key)
                self._update_api_key_alert()
                print(f">>> [Kimi] 已保存到当前会话（检测异常），Key 长度={len(key)}")
                self.statusBar_show("⚠ Key 已保存（检测异常，可能无法使用）")
            else:
                self.statusBar_show("❌ 已取消保存")

    def _refresh_history(self):
        """从 logs 表读取最近记录并填充历史表格。
        排序策略：ASC（最旧在表格顶部，最新一条在最后一行），
        因此表格底部永远是最近一次的识别结果。
        """
        if not HAS_DB:
            return
        try:
            logs = get_logs(limit=200, order="ASC")
        except Exception as e:  # noqa: BLE001
            print(f">>> [DB] 读取 logs 失败: {e}")
            return
        self.historyTable.setRowCount(len(logs))
        for i, log in enumerate(logs):
            self.historyTable.setItem(i, 0, QTableWidgetItem(str(log.get("timestamp", ""))))
            self.historyTable.setItem(i, 1, QTableWidgetItem(str(log.get("gesture_type") or "")))
            self.historyTable.setItem(i, 2, QTableWidgetItem(str(log.get("yolo_object") or "")))
            self.historyTable.setItem(i, 3, QTableWidgetItem(str(log.get("translation_text") or "")))
        self.historyTable.resizeColumnsToContents()
        self.historyTable.horizontalHeader().setStretchLastSection(True)
        # 滚到表格底部，让最近一次记录始终可见
        self.historyTable.scrollToBottom()

    def _export_history_csv(self):
        """把全部历史记录导出为 UTF-8-SIG CSV（Excel 友好）。"""
        if not HAS_DB:
            self.statusBar_show("数据库模块不可用，无法导出")
            return
        try:
            import csv
            logs = get_logs(limit=2000, order="ASC")
            if not logs:
                self.statusBar_show("暂无历史记录可导出")
                return
            path = os.path.join(os.getcwd(), f"history_{int(time.time())}.csv")
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["时间", "手势", "物体", "翻译文本"])
                for log in logs:
                    w.writerow([
                        log.get("timestamp", ""),
                        log.get("gesture_type") or "",
                        log.get("yolo_object") or "",
                        log.get("translation_text") or "",
                    ])
            self.statusBar_show(f"历史已导出: {path}")
        except Exception as e:  # noqa: BLE001
            self.statusBar_show(f"导出失败: {e}")

    def _on_tab_changed(self, index: int):
        """切到「📜 识别历史」Tab 时，自动把表格滚到最底部。

        这样无论之前在哪个 Tab（Kimi 对话 / 实时监测 / 系统设置），
        只要用户切到识别历史，第一眼看到的就是最近一次的记录；
        往上滚即可看到更早的历史。
        """
        try:
            if not hasattr(self, "rightTabs") or not hasattr(self, "historyTable"):
                return
            tab_text = self.rightTabs.tabText(index)
            if "识别历史" in tab_text:
                # 先刷新一次（确保看到的是最新数据），再滚到底部
                self._refresh_history()
        except Exception as e:  # noqa: BLE001
            print(f">>> [UI] 切换 Tab 时滚动到底部失败: {e}")

    # ------------------------------------------------------------------ #
    #  顶部 API Key 告警条（黄色 Alert，绝对不再遮挡数据记录按钮）
    # ------------------------------------------------------------------ #
    def _update_api_key_alert(self):
        if not hasattr(self, "apiKeyAlert"):
            return
        # 实时算一遍 key 来源（仅看本次会话的 self.api_key）
        session_key = (getattr(self, "api_key", "") or "").strip().strip('"\'').strip()
        try:
            configured = bool(self.llm) and self.llm.is_configured()
        except Exception:  # noqa: BLE001
            configured = False
        # 来源推断（GUI 不再读 env/db）
        if session_key:
            src = f"session({session_key[:4]}…{session_key[-4:]}, len={len(session_key)})"
        else:
            src = "未配置"
        if configured:
            self.apiKeyAlert.setText(
                "✅ Kimi 已配置"
            )
            self.apiKeyAlert.setStyleSheet(
                "color: #0d2b1a; background-color: #b6f0c2;"
                "border: 1px solid #2e7d32; border-radius: 4px;"
                "padding: 3px 4px; font-size: 11px; font-weight: bold;"
                "font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
            )
        else:
            # 未配置：无论 self.llm 是 None 还是空 key，都统一显示「缺少 Moonshot API Key」
            self.apiKeyAlert.setText("⚠ 缺少 Moonshot API Key")
            self.apiKeyAlert.setStyleSheet(
                "color: #2b2200; background-color: #ffd54a;"
                "border: 1px solid #b58900; border-radius: 4px;"
                "padding: 3px 4px; font-size: 11px; font-weight: bold;"
                "font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
            )
        self.apiKeyAlert.setVisible(True)

    # ------------------------------------------------------------------ #
    #  ❓ 帮助 / 使用手册 弹窗
    # ------------------------------------------------------------------ #
    def _show_help_dialog(self):
        dlg = HelpDialog(self)
        dlg.exec()

    def _wire_controls(self):
        self.ui.openCamButton.clicked.connect(self.start_camera)
        self.ui.closeCamButton.clicked.connect(self.stop_camera)
        self.ui.screenshotButton.clicked.connect(self.save_screenshot)
        self.ui.saveButton.setEnabled(True)
        self.ui.saveButton.clicked.connect(self.save_screenshot)
        self.ui.exportButton.clicked.connect(self.export_chat)
    
        self.sendButton.clicked.connect(self.send_chat)
        self.chatInput.returnPressed.connect(self.send_chat)
        self.voiceButton.clicked.connect(self.start_voice_input)

        self.helpButton.clicked.connect(self._show_help_dialog)
    
    # ------------------------------------------------------------------ #
    #  摄像头 / 多模态启动
    # ------------------------------------------------------------------ #
    def start_camera(self):
        if self._running or getattr(self, "_init_running", False):
            return
        self._init_running = True
        # 立即反馈，避免用户以为程序卡死；UI 不再被初始化阻塞
        self.ui.openCamButton.setEnabled(False)
        self.ui.closeCamButton.setEnabled(True)
        self.statusBar_show("正在打开摄像头…（手势识别即将可用，物体检测/语音后台加载中）")
        # 读取本次会话内的 Key（仅本会话有效，不读 env/db），交给后台线程
        session_key = (getattr(self, "api_key", "") or "").strip().strip('"\'').strip()
        final_key = session_key if len(session_key) >= 20 else ""
        self._init_worker = CameraInitWorker(api_key=final_key)
        self._init_worker.cam_ready.connect(self._on_camera_ready)
        self._init_worker.extras_ready.connect(self._on_extras_ready)
        self._init_worker.failed.connect(self._on_camera_init_failed)
        self._init_worker.start()  # 后台加载，UI 立刻恢复响应

    def _on_camera_ready(self, vision, cap_fallback, tracker):
        """阶段1完成：摄像头 + 手势引擎已就绪，立即启动画面（物体检测/语音仍在后台加载）。"""
        self._init_running = False
        self.vision = vision
        self.cap_fallback = cap_fallback
        self.tracker = tracker

        self._running = True
        self.timer.start(33)  # ~30 FPS
        self.statusBar_show("摄像头已开启 | 手势识别中（物体检测/语音后台加载中…）")

        # 若用户是从「小游戏」触发开摄像头，开好后立即开始游戏并切到游戏 Tab；
        # 普通「打开摄像头」不自动跳转，留在当前 Tab，由用户自行选择查看哪个页面。
        pending = getattr(self, "_pending_game", None)
        if pending:
            self._pending_game = None
            gc = getattr(self, "game_controller", None)
            if gc is not None:
                gc.start(self.game_hub.get_difficulty())
            try:
                self.rightTabs.setCurrentIndex(self.rightTabs.count() - 1)
            except Exception:  # noqa: BLE001
                pass

    def _on_extras_ready(self, obj, llm, tts, asr):
        """阶段2完成：YOLO 物体检测 / ASR / TTS / Kimi 全部就绪，挂到主窗口启用。

        边界：若用户在加载期间已关闭摄像头（self._running 为 False 或摄像头已释放），
        则直接释放这些刚创建的组件，不挂到主窗口，避免「幽灵」后台线程继续跑。
        """
        if not self._running or self.vision is None:
            if obj is not None:
                try:
                    obj.stop()
                except Exception:  # noqa: BLE001
                    pass
            return
        self.obj = obj
        # 仅当后台确实创建了 LLM 客户端时才覆盖；避免用户在开摄像头前
        # 已自行配置 Key 创建的 self.llm 被 None 清掉。
        if llm is not None:
            self.llm = llm
        self.tts = tts
        self.asr = asr
        self._update_api_key_alert()  # 顶部告警条按 LLM 状态显示/隐藏
        self.statusBar_show("摄像头已开启 | 全部组件就绪")

    def _on_camera_init_failed(self, msg):
        self._init_running = False
        self.statusBar_show(f"摄像头初始化失败: {msg}")
        self.ui.openCamButton.setEnabled(True)
        self.ui.closeCamButton.setEnabled(False)

    # ------------------------------------------------------------------ #
    #  小游戏：切水果
    # ------------------------------------------------------------------ #
    def _on_game_start(self, game_id: str):
        """用户点「开始游戏」。如果摄像头没开，先自动打开。"""
        if game_id != "fruit_slice":
            return
        if not self._running:
            # 摄像头未开 → 先打开，标记待启动游戏
            self._pending_game = game_id
            self.game_hub.statusLabel.setText("⏳ 正在打开摄像头，请稍候...")
            self.game_hub.statusLabel.setStyleSheet(
                "color: #FF9800; font-size: 12px; font-weight: bold;"
            )
            self.start_camera()
            return
        # 摄像头已开 → 直接开始
        self.game_controller.start(self.game_hub.get_difficulty())

    def _on_game_pause(self):
        """暂停 / 继续。"""
        self.game_controller.pause()

    def _on_game_end(self):
        """手动结束游戏。"""
        self.game_controller.end()

    def _on_game_over(self, reason: str, score: int):
        """游戏自然结束（时间到 / 生命耗尽）。"""
        self.game_hub.show_game_over(reason, score)

    def stop_camera(self):
        self._running = False
        self.timer.stop()
        # 游戏进行中关闭摄像头 → 强制结束游戏，避免状态卡在 running
        gc = getattr(self, "game_controller", None)
        if gc is not None and gc.is_running:
            gc.end()
        if self.obj is not None:
            try:
                self.obj.stop()
            except Exception:  # noqa: BLE001
                pass
            self.obj = None
        if self.vision is not None:
            try:
                self.vision.release()
            except Exception:  # noqa: BLE001
                pass
            self.vision = None
        if self.cap_fallback is not None:
            self.cap_fallback.release()
            self.cap_fallback = None
        self.statusBar_show("摄像头已关闭")
        # 恢复按钮状态，允许用户再次打开摄像头
        if hasattr(self.ui, "openCamButton"):
            self.ui.openCamButton.setEnabled(True)
        if hasattr(self.ui, "closeCamButton"):
            self.ui.closeCamButton.setEnabled(False)
        # 关闭后把实时监测面板恢复成「初始黑屏」状态（不留最后一帧）
        self._clear_live_panel()

    def _clear_live_panel(self):
        """摄像头关闭后：左侧画面回纯黑 + 右侧标签回到初始占位 + 业务状态清空。"""
        # 1) 左侧 camLabel：填一张纯黑 QPixmap，与初始未启动时的黑色背景一致
        w = max(self.ui.camLabel.width(), 320)
        h = max(self.ui.camLabel.height(), 240)
        black = QPixmap(w, h)
        black.fill(Qt.black)
        self.ui.camLabel.setPixmap(black)
        self.ui.camLabel.setText("")
        # 2) 左右手势/手指数/方向标签
        for prefix in ("left", "right"):
            getattr(self.ui, f"{prefix}GestureLabelValue").setText("未检测")
            getattr(self.ui, f"{prefix}FingerLabelValue").setText("— / 5")
            getattr(self.ui, f"{prefix}DirectionLabelValue").setText("—")
        # 3) 手势含义 + 环境物体
        if hasattr(self.ui, "meaningLabelValue"):
            self.ui.meaningLabelValue.setText("等待识别...")
        if hasattr(self.ui, "envLabelValue"):
            self.ui.envLabelValue.setText("无")
        # 4) 业务状态清空（避免下次开摄像头时残留上下文污染 send_chat）
        self.current_gestures = []
        self.current_objects = []
        self._pending_log_ctx = None
        # 5) 掌心轨迹清空（SequenceTracker 暴露 deque；防止首帧误判 Wave/Circle）
        if self.tracker is not None:
            self.tracker.left_pts.clear()
            self.tracker.right_pts.clear()
    
    # ------------------------------------------------------------------ #
    #  主循环（QTimer 驱动，运行在 UI 主线程）
    # ------------------------------------------------------------------ #
    def _tick(self):
        if not self._running:
            return
    
        frame = None
        parsed = {}
        if self.vision is not None:
            # 游戏模式下自动隐藏手部骨骼线；非游戏模式按用户设置开关决定
            in_game = hasattr(self, "game_controller") and self.game_controller.is_running
            self.vision.draw_skeleton = self.ui.drawSkeletonCheck.isChecked() and not in_game
            frame, parsed = self.vision.process_frame()
        elif self.cap_fallback is not None:
            ret, f = self.cap_fallback.read()
            if ret:
                frame = cv2.flip(f, 1)
                parsed = {
                    "left_gesture": "None", "right_gesture": "None",
                    "is_heart": False,
                    "left_landmarks": None, "right_landmarks": None,
                }
    
        if frame is None:
            return
    
        # 镜像开关
        if not self.ui.mirrorCheck.isChecked():
            frame = cv2.flip(frame, 1)
    
        # 动态 + 静态手势合并
        if self.tracker is not None:
            self.tracker.update(
                parsed.get("left_landmarks"),
                parsed.get("right_landmarks"),
            )
            dyn = self.tracker.get_dynamic_gestures()
        else:
            dyn = {"left_dynamic": "None", "right_dynamic": "None"}
    
        g_left = _merge_gesture(parsed.get("left_gesture"), dyn["left_dynamic"])
        g_right = _merge_gesture(parsed.get("right_gesture"), dyn["right_dynamic"])
        live = [g for g in (g_left, g_right) if g]
        if parsed.get("is_heart"):
            live.append("比心")
        self.current_gestures = live
    
        # 物品感知
        if self.obj is not None:
            self.obj.update_frame(frame)
            self.current_objects = self.obj.get_display_objects()
        else:
            self.current_objects = []
    
        # ---- 回填右侧控件 ----
        self.ui.leftGestureLabelValue.setText(g_left or "未检测")
        self.ui.rightGestureLabelValue.setText(g_right or "未检测")

        # 手指数（未检测到的手显示 —）
        lf = parsed.get("left_fingers", 0)
        rf = parsed.get("right_fingers", 0)
        l_has = parsed.get("left_landmarks") is not None
        r_has = parsed.get("right_landmarks") is not None
        self.ui.leftFingerLabelValue.setText(
            f"{lf} / 5" if l_has else "— / 5"
        )
        self.ui.rightFingerLabelValue.setText(
            f"{rf} / 5" if r_has else "— / 5"
        )

        # 方向（↑/↓/←/→/·，未检测到的手显示 —）
        self.ui.leftDirectionLabelValue.setText(
            parsed.get("left_direction", "·") if l_has else "—"
        )
        self.ui.rightDirectionLabelValue.setText(
            parsed.get("right_direction", "·") if r_has else "—"
        )

        self.envLabelValue.setText("、".join(self.current_objects) or "无")

        # ---- 含义区：实时拼接（左:手势 指头数 方向 / 右:...）----
        # Kimi 回复后会被覆盖 3 秒（见 _on_chat_done）
        # 含义区：名称（语义含义）；动态手语优先用其英文标签查含义
        l_en = dyn["left_dynamic"] if dyn.get("left_dynamic") not in (None, "None") else parsed.get("left_gesture")
        r_en = dyn["right_dynamic"] if dyn.get("right_dynamic") not in (None, "None") else parsed.get("right_gesture")
        left_text = _as_text(l_en, g_left)
        right_text = _as_text(r_en, g_right)
        live_meaning = self._build_live_meaning(
            left_text, right_text, self.current_objects, parsed.get("is_heart")
        )
        if self._should_use_live_meaning():
            self.ui.meaningLabelValue.setText(live_meaning)

        # ---- Phase B 恢复：掌心轨迹线 + 动态手势名 ----
        # 游戏进行中：不画手掌/手指轨迹线，只保留切水果的「食指指尖轨迹」
        # （由 game_controller.update_and_draw 绘制），满足「只显示食指最上方画出的线条」。
        if not (hasattr(self, "game_controller") and self.game_controller.is_running):
            self._draw_palm_trail_and_dynamic(frame, dyn)

        # ---- 小游戏：切水果在摄像头画面上叠加 ----
        if hasattr(self, "game_controller") and self.game_controller.is_running:
            # 用真实帧间隔（限幅），避免首帧 _fps=0 时 dt=1s 把倒计时瞬间扣掉 1 秒
            real_dt = time.time() - self._last_tick
            dt = min(max(real_dt, 0.0), 0.1)
            self.game_controller.update_and_draw(frame, parsed, dt)

        # ---- 左侧画面 ----
        pix = cv2_to_pixmap(frame, self.ui.camLabel.width(), self.ui.camLabel.height())
        self.ui.camLabel.setPixmap(pix)

        # ---- FPS ----
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        if dt > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)
        self.statusBar_show(f"实时识别中 | FPS: {self._fps:.1f}")

    # ------------------------------------------------------------------ #
    #  Phase B 辅助：在 frame 上叠加掌心轨迹线 + 动态手势名
    # ------------------------------------------------------------------ #
    def _draw_palm_trail_and_dynamic(self, frame, dyn):
        """掌心轨迹：颜色随动态手势变化（画圈=青 / 挥手=黄 / 滑动=紫 / 无=灰）；
        动态手势名浮动显示在画面顶部。"""
        if frame is None:
            return
        h, w = frame.shape[:2]

        # 动态手势 → 轨迹颜色映射，让「画圈 / 挥手」在画面上肉眼可区分
        def _dyn_color(d):
            if d == "Circle":
                return (255, 255, 0)        # 青色（画圈）
            if d == "Wave":
                return (0, 255, 255)        # 黄色（挥手）
            if d and d.startswith("Swipe"):
                return (255, 0, 255)        # 紫色（滑动）
            return (120, 120, 120)          # 灰色（无动态）

        # 提前取出左右动态标签，供轨迹着色使用
        l_dyn = (dyn or {}).get("left_dynamic", "None") or "None"
        r_dyn = (dyn or {}).get("right_dynamic", "None") or "None"

        # 1) 轨迹线：归一化坐标 → 像素坐标
        if self.tracker is not None:
            for pts, color, thick in [
                (self.tracker.left_pts, _dyn_color(l_dyn), 3),
                (self.tracker.right_pts, _dyn_color(r_dyn), 3),
            ]:
                pts_list = list(pts)
                if len(pts_list) < 2:
                    continue
                # 逐段连线（用最近 max_length 帧，deque maxlen）。
                # 相邻点跳变过大视为「断笔」（手曾离开/漏检又被检出），不连直线，
                # 避免从画面一端拉一条长线穿越；手回来后的后续点会正常接回。
                max_jump2 = 0.18 * 0.18  # 归一化距离平方阈值
                for i in range(1, len(pts_list)):
                    a = pts_list[i - 1]
                    b = pts_list[i]
                    dx = b[0] - a[0]
                    dy = b[1] - a[1]
                    if dx * dx + dy * dy > max_jump2:
                        continue  # 缺口不连直线
                    p1 = (int(a[0] * w), int(a[1] * h))
                    p2 = (int(b[0] * w), int(b[1] * h))
                    # 越新的线越亮、越老的越淡（尾部自然消退，避免长痕赖着）
                    alpha = 0.3 + 0.7 * (i / len(pts_list))
                    c = tuple(int(v * alpha + 30 * (1 - alpha)) for v in color)
                    cv2.line(frame, p1, p2, c, thick)
                # 当前点画个小圆
                last = pts_list[-1]
                cx, cy = int(last[0] * w), int(last[1] * h)
                cv2.circle(frame, (cx, cy), 6, color, -1)
                cv2.circle(frame, (cx, cy), 8, (255, 255, 255), 1)

        # 2) 左上角动态手势提示已移除，避免数字/编号与画面内容重叠。
        # 动态结果继续通过右侧「实时监测」面板显示。

    # ------------------------------------------------------------------ #
    #  键盘 / 语音 与 Kimi 交流
    # ------------------------------------------------------------------ #
    def send_chat(self):
        text = self.chatInput.text().strip()
        if not text:
            return
        # === 守卫：未配置有效 Kimi Key 时引导去设置页 ===
        if not self._check_kimi_key_or_prompt():
            return
        self.chatHistory.append(f"<b>你：</b>{_esc(text)}")
        self.chatHistory.append(
            "<div style='color:#888; font-size:13px; margin:4px 0;'>"
            "<span style='font-size:16px;'>🤔</span> <i>Kimi 正在思考…</i>"
            "</div>"
        )
        thinking_cursor = QTextCursor(self.chatHistory.document())
        thinking_cursor.movePosition(QTextCursor.End)
        self._thinking_block = thinking_cursor.block()
        self.chatInput.clear()
        self.sendButton.setEnabled(False)
        self.voiceButton.setEnabled(False)

        self._worker = ChatWorker(self.llm, text)
        # 捕获发送时刻的上下文，供翻译完成后写入历史（避免完成时被新帧覆盖）
        self._pending_log_ctx = (list(self.current_gestures), list(self.current_objects))
        self._worker.done.connect(self._on_chat_done)
        self._worker.error.connect(self._on_chat_error)
        self._worker.start()
    
    def _on_chat_done(self, translated, intent):
        self._remove_chat_thinking()
        self.chatHistory.append(
            f"<b>助手：</b>{_esc(translated)} "
            f"<span style='color:#ffd700;'>[意图: {_esc(intent)}]</span>"
        )
        self.chatHistory.append("")  # 空行分隔
        self.ui.meaningLabelValue.setText(translated or "—")
        # Kimi 回复期间覆盖含义区，3 秒后自动回退到实时拼接
        self._chat_meaning_expire = time.time() + 3.0
        self.sendButton.setEnabled(True)
        self.voiceButton.setEnabled(True)
        if self.tts is not None and translated:
            self.tts.speak(translated, block=False)
        # 写入识别历史（数据库 logs 表）
        if HAS_DB and self._pending_log_ctx is not None:
            g_list, o_list = self._pending_log_ctx
            try:
                insert_log(
                    gesture_type="、".join(g_list) if g_list else "无",
                    yolo_object="、".join(o_list) if o_list else "无",
                    translation_text=translated or "",
                )
                QTimer.singleShot(0, self._refresh_history)
            except Exception as e:  # noqa: BLE001
                print(f">>> [DB] 写入 logs 失败: {e}")
            self._pending_log_ctx = None
        self._worker = None

    def _on_chat_error(self, msg):
        self._remove_chat_thinking()
        self.chatHistory.append(f"<span style='color:#ff5555;'>⚠ 错误: {_esc(msg)}</span>")
        self.sendButton.setEnabled(True)
        self.voiceButton.setEnabled(True)
        self._worker = None

    def _remove_chat_thinking(self):
        """移除聊天历史里的 'Kimi 正在思考…' 占位提示。"""
        block = getattr(self, "_thinking_block", None)
        if block is not None and block.isValid():
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
        self._thinking_block = None

    # ------------------------------------------------------------------ #
    #  含义区：实时拼接 + Kimi 覆盖 3 秒后回退
    # ------------------------------------------------------------------ #
    def _should_use_live_meaning(self):
        """含义区是否应显示"实时拼接"——Kimi 回复后 3 秒内仍显示润色结果。"""
        if self._chat_meaning_expire <= 0:
            return True
        return time.time() > self._chat_meaning_expire

    @staticmethod
    def _build_live_meaning(left_text, right_text, objects, heart):
        """把识别到的手势拼成中文含义（含语义）：左手：握拳（坚持/加油） ｜ 右手：… ｜ 比心（…）。"""
        parts = []
        if left_text:
            parts.append(f"左手：{left_text}")
        if right_text:
            parts.append(f"右手：{right_text}")
        if heart:
            parts.append("比心（表达爱意 / 感谢（大））")
        if not parts:
            return "等待识别..."
        if objects:
            parts.append("场景：" + "、".join(objects))
        return " ｜ ".join(parts)

    def start_voice_input(self):
        if self.asr is None:
            self.chatHistory.append(
                "<span style='color:#ff5555;'>⚠ ASR 未初始化（未开摄像头或 faster-whisper 缺失）</span>"
            )
            return
        self.voiceButton.setEnabled(False)
        self.statusBar_show("录音中… 请清晰说话（4 秒）")
        threading.Thread(target=self._record_and_transcribe, daemon=True).start()
    
    def _record_and_transcribe(self):
        try:
            import sounddevice as sd
            import wave
    
            fs = 16000
            data = sd.rec(int(4 * fs), samplerate=fs, channels=1, dtype="int16")
            sd.wait()
            wav_path = os.path.join(tempfile.gettempdir(), f"asr_{uuid.uuid4().hex}.wav")
            with wave.open(wav_path, "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(fs)
                f.writeframes(data.tobytes())
            text = self.asr.transcribe_audio_file(wav_path)
            if text:
                QTimer.singleShot(0, lambda: self.chatInput.setText(text))
                QTimer.singleShot(50, self.send_chat)
            else:
                QTimer.singleShot(0, lambda: self.statusBar_show("未识别到语音"))
        except Exception as e:  # noqa: BLE001
            print(f">>> 语音输入异常: {e}")
            QTimer.singleShot(0, lambda: self.statusBar_show(f"语音输入失败: {e}"))
        finally:
            QTimer.singleShot(0, lambda: self.voiceButton.setEnabled(True))
    
    # ------------------------------------------------------------------ #
    #  数据记录
    # ------------------------------------------------------------------ #
    def save_screenshot(self):
        if self.ui.camLabel.pixmap() is None:
            self.statusBar_show("暂无画面可截图")
            return
        path = os.path.join(os.getcwd(), f"snapshot_{int(time.time())}.png")
        self.ui.camLabel.pixmap().save(path)
        self.statusBar_show(f"截图已保存: {path}")
    
    def export_chat(self):
        path = os.path.join(os.getcwd(), f"chat_log_{int(time.time())}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.chatHistory.toPlainText())
            self.statusBar_show(f"对话记录已导出: {path}")
        except Exception as e:  # noqa: BLE001
            self.statusBar_show(f"导出失败: {e}")
    
    # ------------------------------------------------------------------ #
    def statusBar_show(self, text):
        self.ui.statusBar.setText(f"状态栏：{text}")
    
    def closeEvent(self, event):
        self.stop_camera()
        # 断开初始化线程信号，避免程序退出后回调已半销毁的对象
        if getattr(self, "_init_worker", None) is not None:
            try:
                self._init_worker.cam_ready.disconnect()
                self._init_worker.extras_ready.disconnect()
                self._init_worker.failed.disconnect()
            except Exception:  # noqa: BLE001
                pass
        # 关闭程序时清空识别历史（logs 表）：
        #   - 历史只在本会话内可见
        #   - 重启后从空白开始，避免无限累积 / 隐私外泄
        if HAS_DB:
            try:
                n = clear_logs()
                if n > 0:
                    print(f">>> [DB] 关闭程序，已清空 {n} 条识别历史")
            except Exception as e:  # noqa: BLE001
                print(f">>> [DB] 清空 logs 失败: {e}")
        super().closeEvent(event)
    
    def keyPressEvent(self, event):
        """全局快捷键：R=录音，Esc=关闭弹窗。"""
        k = event.key()
        if k == Qt.Key_R:
            self.start_voice_input()
            return
        if k == Qt.Key_Escape:
            # 若有模态弹窗，由 Qt 自己关闭；否则透传给父类
            if self.isActiveWindow():
                return
        super().keyPressEvent(event)


# ================================================================== #
#  ❓ 使用手册 / 快捷键说明 模态弹窗
# ================================================================== #
class HelpDialog(QDialog):
    """使用手册 / 快捷键说明 模态弹窗。"""

    HELP_HTML = """
    <div style="font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
                font-size: 13px; color: #f0f0f0; line-height: 1.6;">
      <h3 style="color:#4a9eff; margin-top:0;">📖 系统介绍</h3>
      <p>AI 手势识别系统 · 多模态无障碍交流终端。<br>
      通过 <b>摄像头</b> + <b>语音</b> + <b>键盘</b> 三种通道，
      借助 <b>MediaPipe</b>（静态/动态手势）、<b>YOLO-World</b>（开放词汇物品）、
      <b>Kimi / Moonshot</b>（对话与意图理解）、
      <b>Edge-TTS</b>（语音播报），
      把手势、指向、物体、语音转成自然语言并播报，帮助听障 / 言语障碍人士与外界交流。</p>

      <h3 style="color:#4a9eff;">⌨️ 快捷键</h3>
      <table cellspacing="6" cellpadding="4" border="0"
             style="border-collapse: collapse;">
        <tr><td><b>Space</b></td><td>在 Kimi 对话 Tab 内：发送当前输入框文字</td></tr>
        <tr><td><b>R</b></td><td>开始 4 秒录音 → ASR 听写 → 自动填入输入框并发送</td></tr>
        <tr><td><b>Esc</b></td><td>关闭弹窗 / 退出程序</td></tr>
      </table>

      <h3 style="color:#4a9eff;">📖 手势含义字典</h3>
      <table cellspacing="3" cellpadding="3" border="1" style="border-color:#444; width:100%; font-size:12px;">
        <tr style="color:#4a9eff;"><th>手势</th><th>名称</th><th>含义</th></tr>
        <tr><td>👍</td><td>点赞</td><td>赞赏 / 棒 / 同意 / 没问题 / 搞定</td></tr>
        <tr><td>👎</td><td>拇指向下</td><td>差劲 / 反对 / 不同意 / 否定</td></tr>
        <tr><td>👌</td><td>OK</td><td>好的 / 确定 / 没问题</td></tr>
        <tr><td>✌️</td><td>胜利</td><td>胜利 / 和平 / 数字2</td></tr>
        <tr><td>🖐️</td><td>张开手掌</td><td>停止 / 拒绝 / 稍等</td></tr>
        <tr><td>☝️</td><td>食指竖起</td><td>提示注意 / 稍等一下 / 数字1</td></tr>
        <tr><td>🤫</td><td>安静</td><td>保持安静 / 闭嘴 / 保密</td></tr>
        <tr><td>🤙</td><td>打电话</td><td>联系我 / 打电话 / 呼叫</td></tr>
        <tr><td>🫰</td><td>比心</td><td>爱你 / 喜欢 / 感谢（小）</td></tr>
        <tr><td>✊</td><td>握拳</td><td>坚持 / 加油 / 力量 / 团结</td></tr>
        <tr><td>🫶</td><td>双手比心</td><td>表达爱意 / 感谢（大）</td></tr>
      </table>
      <p style="color:#aaa; font-size:11px;">（注：👌=OK、✌️=数字2、🖐️=数字5、☝️=数字1 在系统中以数字/OK 形式识别并附带上述语义；👍/👎 由拇指朝向识别；🫰 比心=拇指尖与食指尖靠拢成小环；🤙 打电话=仅拇指+小指伸直；🫶 双手比心由双手食指尖+拇指尖靠拢判定。）</p>

      <h3 style="color:#4a9eff;">🖐 手势触发</h3>
      <ul>
        <li><b>双手比心 (❤) 定格 1.5 秒</b>：触发一次 Kimi 对话（把当前手势/物体/语音作为上下文一并发送）</li>
        <li><b>挥手 / 画圈 / 上划 / 下划 / 左划 / 右划</b>：动态手语，优先级高于静态手势</li>
        <li><b>指向</b>：手腕→食指尖射线，结合 YOLO 框选命中物体</li>
      </ul>

      <h3 style="color:#4a9eff;">🧩 技术栈</h3>
      <ul>
        <li>OpenCV（采集/画框）· MediaPipe Hands · Ultralytics YOLO-World</li>
        <li>Faster-Whisper（本地 ASR）· edge-tts（云端 TTS）· pygame 播放</li>
        <li>Kimi / Moonshot OpenAI 兼容 API（结构化文本模式）</li>
        <li>PySide6（GUI）· SQLite（历史/设置/手势字典）</li>
      </ul>

      <h3 style="color:#4a9eff;">❓ 常见问题</h3>
      <ul>
        <li>顶部黄色 Alert：本次会话尚未在「系统设置」粘贴并保存 Moonshot API Key 时显示。Key 仅存于内存、重启后失效，需重新输入。</li>
        <li>保存配置会自动检测 Key：通过才保存；若返回 401 则提示「Key 错误」并拒绝保存。</li>
        <li>语音按钮灰：未打开摄像头或未安装 <code>faster-whisper</code>。</li>
        <li>无需打开摄像头即可与 Kimi 文字对话——只要先在「系统设置」保存有效 Key。</li>
        <li>点击「❓ 使用手册」可随时再次打开本窗口。</li>
      </ul>
    </div>
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 使用手册 / 快捷键")
        self.setModal(True)
        self.resize(640, 560)
        self.setStyleSheet(
            "QDialog { background-color: #0d0d0d; color: #f0f0f0; }"
            "QPushButton {"
            "  background-color: #1a1a1a; color: #f0f0f0;"
            "  border: 2px dashed #ffffff; border-radius: 5px;"
            "  padding: 6px 18px; min-width: 90px; font-weight: bold;"
            "}"
            "QPushButton:hover { background-color: #333333; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("📖 使用手册 / 快捷键说明")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #4a9eff;"
            "border-bottom: 2px dashed #4a9eff; padding-bottom: 6px;"
        )
        root.addWidget(title)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background-color: #151515;")
        body = QLabel(self.HELP_HTML)
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setStyleSheet(
            "background-color: #151515; color: #f0f0f0; padding: 8px 4px;"
        )
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)


def _esc(text):
    """转义 HTML 特殊字符，避免聊天框渲染错乱。"""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main():
    # PyInstaller 冻结后，把工作目录切到 exe 所在目录，
    # 确保 yolov8s-world.pt / weights/clip/ / check.png 等资源（相对路径基准）能被找到。
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    app = QApplication(sys.argv)
    # 先弹出登录 / 注册入口；登录成功才进入主程序
    from auth import AuthWindow
    from PySide6.QtWidgets import QDialog
    auth = AuthWindow()
    if auth.exec() == QDialog.Accepted:
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
