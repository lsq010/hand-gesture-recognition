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

import numpy as np
import cv2

from PySide6.QtWidgets import (
    QApplication, QWidget, QGroupBox, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem,
    QTabWidget, QDialog, QDialogButtonBox, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPixmap

# 复用原有 rec.ui 生成的界面结构
try:
    from rec import Ui_Form
except ImportError:
    Ui_Form = None

# ---- 复用前几阶段封装好的模块（单点失败不影响整体） ----
try:
    from vision_engine import VisionEngine
except ImportError:
    VisionEngine = None
try:
    from sequence_tracker import SequenceTracker
except ImportError:
    SequenceTracker = None
try:
    from object_detector import ObjectDetector
except ImportError:
    ObjectDetector = None
try:
    from llm_client import KimiLLMClient
except ImportError:
    KimiLLMClient = None
try:
    from asr_tts import ASRManager, TTSManager
except ImportError:
    ASRManager = None
    TTSManager = None
try:
    from database import (
        init_db, get_all_settings, get_setting, save_setting,
        insert_log, get_logs, get_signs, insert_sign,
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


class ChatWorker(QThread):
    """在子线程里调用 Kimi，避免阻塞 UI。"""

    done = Signal(str, str)   # translated_text, intent
    error = Signal(str)

    def __init__(self, llm, gestures, objects, text):
        super().__init__()
        self.llm = llm
        self.gestures = gestures
        self.objects = objects
        self.text = text

    def run(self):
        try:
            if self.llm is None:
                self.done.emit("（LLM 客户端未配置，请设置 MOONSHOT_API_KEY）", "Error")
                return
            res = self.llm.translate_context(
                gestures=self.gestures,
                objects=self.objects,
                asr_text=self.text,
            )
            self.done.emit(
                res.get("translated_text", ""),
                res.get("intent", "Unknown"),
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

        # === 1) 先把 rec.ui 默认塞进 rightPanelLayout 的 4 个 GroupBox 全部取出 ===
        preset_widgets = []
        while right.count():
            item = right.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                preset_widgets.append(w)

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
            "padding: 4px 10px; font-weight: bold;"
            "font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
        )
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

        # 演示预设（无摄像头时也能演示全链路）
        preset_row = QHBoxLayout()
        self.preset1Button = QPushButton("场景1: 指向+药瓶")
        self.preset2Button = QPushButton("场景2: 挥手+早上好")
        preset_row.addWidget(self.preset1Button)
        preset_row.addWidget(self.preset2Button)
        tab_chat_layout.addWidget(_wrap_in_group("🧪 演示预设", preset_row))

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

        # --- Tab 3：⚙ 系统设置（控制 / 显示 / 记录） ---
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
        self.apiKeyEdit.setPlaceholderText("粘贴 Moonshot API Key（留空则用环境变量）")
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

        # === 📜 识别历史记录（来自 logs 表） ===
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
        tab_sys_layout.addWidget(self.historyGroup)

        tab_sys_layout.addStretch(1)
        self.rightTabs.addTab(tab_sys, "⚙ 系统设置")

        right.addWidget(self.rightTabs, stretch=1)

        # 默认进入「系统设置」Tab；开摄像头时自动切到「实时监测（手势含义）」
        self.rightTabs.setCurrentIndex(2)

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

        # 4) API Key 回填到输入框（不把明文打到日志）
        saved_key = self.db_settings.get("kimi_api_key", "")
        if saved_key:
            self.apiKeyEdit.setText(saved_key)

        # 5) 初次刷新历史列表
        self._refresh_history()

    def _save_config(self):
        """把 API Key 输入框内容持久化到 settings 表。"""
        if not HAS_DB:
            self.statusBar_show("数据库模块不可用，无法保存配置")
            return
        key = self.apiKeyEdit.text().strip()
        try:
            save_setting("kimi_api_key", key, "Moonshot API Key")
            self.db_settings["kimi_api_key"] = key
            self.statusBar_show("✅ 配置已保存到数据库（下次开摄像头生效）")
        except Exception as e:  # noqa: BLE001
            self.statusBar_show(f"保存失败: {e}")

    def _refresh_history(self):
        """从 logs 表读取最近记录并填充历史表格。"""
        if not HAS_DB:
            return
        try:
            logs = get_logs(limit=200, order="DESC")
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

    # ------------------------------------------------------------------ #
    #  顶部 API Key 告警条（黄色 Alert，绝对不再遮挡数据记录按钮）
    # ------------------------------------------------------------------ #
    def _update_api_key_alert(self):
        if not hasattr(self, "apiKeyAlert"):
            return
        if self.llm is None:
            self.apiKeyAlert.setText("⚠ LLM 客户端不可用（缺少 llm_client.py）")
            self.apiKeyAlert.setVisible(True)
            return
        try:
            configured = self.llm.is_configured()
        except Exception:  # noqa: BLE001
            configured = False
        if configured:
            self.apiKeyAlert.setText(
                f"✅ Kimi 已配置：{getattr(self.llm, 'model', '')}"
            )
            self.apiKeyAlert.setStyleSheet(
                "color: #0d2b1a; background-color: #b6f0c2;"
                "border: 1px solid #2e7d32; border-radius: 4px;"
                "padding: 4px 10px; font-weight: bold;"
                "font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
            )
        else:
            self.apiKeyAlert.setText("⚠ 未配置 MOONSHOT_API_KEY，已走本地规则兜底")
            self.apiKeyAlert.setStyleSheet(
                "color: #2b2200; background-color: #ffd54a;"
                "border: 1px solid #b58900; border-radius: 4px;"
                "padding: 4px 10px; font-weight: bold;"
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
        self.preset1Button.clicked.connect(
            lambda: self.apply_preset(["指向"], ["药瓶", "水杯"], "帮我拿一下")
        )
        self.preset2Button.clicked.connect(
            lambda: self.apply_preset(["挥手/再见"], [], "早上好")
        )
    
        self.helpButton.clicked.connect(self._show_help_dialog)
    
    # ------------------------------------------------------------------ #
    #  摄像头 / 多模态启动
    # ------------------------------------------------------------------ #
    def start_camera(self):
        if self._running:
            return
        self.statusBar_show("正在初始化多模态组件…")
        try:
            if VisionEngine is not None:
                self.vision = VisionEngine(camera_index=0)
                print(">>> [A] VisionEngine 就绪")
            else:
                self.vision = None
    
            if self.vision is None:
                self.cap_fallback = cv2.VideoCapture(0)
                print(">>> [A] 使用兜底摄像头（仅画面）")
    
            if SequenceTracker is not None:
                self.tracker = SequenceTracker(max_length=35)
                print(">>> [A] SequenceTracker 就绪")
    
            if ObjectDetector is not None:
                try:
                    self.obj = ObjectDetector()
                except Exception as e:  # noqa: BLE001
                    print(f">>> [B] ObjectDetector 初始化失败: {e}")
                    self.obj = None
        except Exception as e:  # noqa: BLE001
            self.statusBar_show(f"摄像头初始化失败: {e}")
            return
    
        if KimiLLMClient is not None:
            # 优先用 settings 表里的 kimi_api_key，其次退回到环境变量
            api_key = self.db_settings.get("kimi_api_key") if HAS_DB else None
            api_key = (api_key or "").strip() or os.environ.get("MOONSHOT_API_KEY", "")
            self.llm = KimiLLMClient(api_key=api_key)
        if TTSManager is not None:
            self.tts = TTSManager()
        if ASRManager is not None:
            self.asr = ASRManager(model_size="tiny")
    
        self._update_api_key_alert()  # 顶部告警条按 LLM 状态显示/隐藏
    
        self._running = True
        self.timer.start(33)  # ~30 FPS
        self.statusBar_show("摄像头已开启 | 实时识别中")
        # 自动切到「实时监测（手势含义）」Tab，开摄像头先看手势/含义
        try:
            self.rightTabs.setCurrentIndex(1)
        except Exception:  # noqa: BLE001
            pass
    
    def stop_camera(self):
        self._running = False
        self.timer.stop()
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
        self._draw_palm_trail_and_dynamic(frame, dyn)

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
        """掌心轨迹：左手绿 / 右手橙；动态手势名浮动显示在画面顶部。"""
        if frame is None:
            return
        h, w = frame.shape[:2]

        # 1) 轨迹线：归一化坐标 → 像素坐标
        if self.tracker is not None:
            for pts, color, thick in [
                (self.tracker.left_pts, (0, 255, 0), 2),
                (self.tracker.right_pts, (255, 200, 0), 2),
            ]:
                pts_list = list(pts)
                if len(pts_list) < 2:
                    continue
                # 逐段连线（用最近 35 帧，deque maxlen）
                for i in range(1, len(pts_list)):
                    p1 = (int(pts_list[i - 1][0] * w), int(pts_list[i - 1][1] * h))
                    p2 = (int(pts_list[i][0] * w), int(pts_list[i][1] * h))
                    # 越新的线越亮：渐变 alpha
                    alpha = 0.4 + 0.6 * (i / len(pts_list))
                    c = tuple(int(v * alpha + 30 * (1 - alpha)) for v in color)
                    cv2.line(frame, p1, p2, c, thick)
                # 当前点画个小圆
                last = pts_list[-1]
                cx, cy = int(last[0] * w), int(last[1] * h)
                cv2.circle(frame, (cx, cy), 6, color, -1)
                cv2.circle(frame, (cx, cy), 8, (255, 255, 255), 1)

        # 2) 动态手势名（英文 cv2.putText 即可，中文才需要 PIL）
        l_dyn = (dyn or {}).get("left_dynamic", "None") or "None"
        r_dyn = (dyn or {}).get("right_dynamic", "None") or "None"
        text = f"Dynamic  L:{l_dyn}  R:{r_dyn}"

        # 半透明黑底便于在浅色背景上看清
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (8, 8), (8 + tw + 16, 8 + th + 16), (0, 0, 0), -1)
        cv2.rectangle(frame, (8, 8), (8 + tw + 16, 8 + th + 16), (0, 165, 255), 1)
        cv2.putText(frame, text, (16, 8 + th + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)

    # ------------------------------------------------------------------ #
    #  键盘 / 语音 与 Kimi 交流
    # ------------------------------------------------------------------ #
    def send_chat(self):
        text = self.chatInput.text().strip()
        if not text:
            return
        self.chatHistory.append(f"<b>你：</b>{_esc(text)}")
        self.chatInput.clear()
        self.sendButton.setEnabled(False)
        self.voiceButton.setEnabled(False)
    
        self._worker = ChatWorker(
            self.llm, self.current_gestures, self.current_objects, text
        )
        # 捕获发送时刻的上下文，供翻译完成后写入历史（避免完成时被新帧覆盖）
        self._pending_log_ctx = (list(self.current_gestures), list(self.current_objects))
        self._worker.done.connect(self._on_chat_done)
        self._worker.error.connect(self._on_chat_error)
        self._worker.start()
    
    def _on_chat_done(self, translated, intent):
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
        self.chatHistory.append(f"<span style='color:#ff5555;'>⚠ 错误: {_esc(msg)}</span>")
        self.sendButton.setEnabled(True)
        self.voiceButton.setEnabled(True)
        self._worker = None

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
    def apply_preset(self, gestures, objects, text):
        # 演示预设：手动设置当前生效输入（摄像头未开时不会被 _tick 覆盖）
        self.current_gestures = list(gestures)
        self.current_objects = list(objects)
        self.ui.leftGestureLabelValue.setText(gestures[0] if gestures else "未检测")
        self.envLabelValue.setText("、".join(objects) or "无")
        self.chatInput.setText(text)
        self.send_chat()
    
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
        super().closeEvent(event)
    
    def keyPressEvent(self, event):
        """全局快捷键：R=录音，1=场景1，2=场景2，Esc=关闭弹窗。"""
        k = event.key()
        if k == Qt.Key_R:
            self.start_voice_input()
            return
        if k == Qt.Key_1:
            if hasattr(self, "preset1Button"):
                self.preset1Button.click()
            return
        if k == Qt.Key_2:
            if hasattr(self, "preset2Button"):
                self.preset2Button.click()
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
      <b>Kimi / Moonshot</b>（中文润色与意图理解）、
      <b>Edge-TTS</b>（语音播报），
      把手势、指向、物体、语音转成自然语言并播报，帮助听障 / 言语障碍人士与外界交流。</p>

      <h3 style="color:#4a9eff;">⌨️ 快捷键</h3>
      <table cellspacing="6" cellpadding="4" border="0"
             style="border-collapse: collapse;">
        <tr><td><b>Space</b></td><td>在 Kimi 对话 Tab 内：发送当前输入框文字</td></tr>
        <tr><td><b>R</b></td><td>开始 4 秒录音 → ASR 听写 → 自动填入输入框并发送</td></tr>
        <tr><td><b>1 / 2</b></td><td>触发演示场景 1（指向+药瓶）/ 场景 2（挥手+早上好）</td></tr>
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
        <li><b>双手比心 (❤) 定格 1.5 秒</b>：触发一次 Kimi 润色（结合当前手势/物体/语音）</li>
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
        <li>顶部黄色 Alert：未配置 <code>MOONSHOT_API_KEY</code> 时显示，回复走本地规则兜底，不影响使用。</li>
        <li>语音按钮灰：未打开摄像头或未安装 <code>faster-whisper</code>。</li>
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


def _wrap_in_group(title, layout):
    """把一行布局包成 GroupBox，保持与原有界面一致的卡片风格。"""
    g = QGroupBox(title)
    g.setLayout(layout)
    return g


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
