# auth.py
# 登录 / 注册 入口模块
# --------------------------------------------------------------
# 提供 AuthWindow（登录 + 注册 对话框），在 main.py 启动 MainWindow 之前弹出。
# - 密码登录：账号 + 密码（pbkdf2 加盐哈希，存于 SQLite auth.db）
# - 人脸登录 / 人脸录入：使用项目内 haar/ 目录下的 Haar 级联做人脸检测，
#   用 OpenCV LBPH 人脸识别器训练 / 预测（trainer.yml）。
# 未注册账号登录 → 提示「登录失败，请注册」；注册需录入人脸编号，保存成功 → 注册成功。

import os
import sys
import hashlib
import secrets
import sqlite3
import datetime

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QStackedWidget, QMessageBox,
    QFrame,
)

# ── 路径 ────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Haar 级联模型随仓库一起提交（haar/haarcascade_frontalface_default.xml）。
# 冻结（PyInstaller）后数据文件随 exe 发布：sys._MEIPASS 指向数据根目录
# （单文件夹 = exe 所在目录，单文件 = 临时解压目录）；未冻结则用源码目录。
if getattr(sys, "frozen", False):
    _RESOURCE_DIR = sys._MEIPASS
else:
    _RESOURCE_DIR = SCRIPT_DIR
HAAR_DIR = os.path.join(_RESOURCE_DIR, "haar")
HAAR_FACE = os.path.join(HAAR_DIR, "haarcascade_frontalface_default.xml")

AUTH_DB = os.path.join(SCRIPT_DIR, "auth.db")
FACES_DIR = os.path.join(SCRIPT_DIR, "faces")
TRAINER_PATH = os.path.join(SCRIPT_DIR, "trainer.yml")

# LBPH predict() 返回的 conf 是「距离」而非百分比：越小越像（0=完美匹配），
# 越大越不像。因此判匹配条件是 conf <= CONF_THRESHOLD。
# 70 偏严，真实人脸在换光照/角度时距离常落在 70~90，故放宽到 90 留余量。
CONF_THRESHOLD = 90.0
FACE_SIZE = (100, 100)
MIN_SAMPLES = 5         # 注册时至少采集的人脸样本数
MAX_SAMPLES = 15

os.makedirs(FACES_DIR, exist_ok=True)


# ── 账号数据库 ──────────────────────────────────────────────────
class AuthDB:
    """SQLite 存储账号：用户名（唯一）、密码哈希（加盐）、人脸编号。"""

    def __init__(self, path=AUTH_DB):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   username TEXT UNIQUE NOT NULL,
                   pw_hash TEXT NOT NULL,
                   salt TEXT NOT NULL,
                   face_label INTEGER UNIQUE,
                   created_at TEXT NOT NULL
               )"""
        )
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    @staticmethod
    def hash_password(password, salt=None):
        if salt is None:
            salt = secrets.token_hex(16)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt), 100_000,
        )
        return dk.hex(), salt

    def user_exists(self, username):
        cur = self.conn.execute(
            "SELECT 1 FROM users WHERE username=?", (username,)
        )
        return cur.fetchone() is not None

    def face_label_exists(self, label):
        cur = self.conn.execute(
            "SELECT 1 FROM users WHERE face_label=?", (int(label),)
        )
        return cur.fetchone() is not None

    def add_user(self, username, password, face_label):
        pw_hash, salt = self.hash_password(password)
        self.conn.execute(
            "INSERT INTO users (username, pw_hash, salt, face_label, created_at) "
            "VALUES (?,?,?,?,?)",
            (username, pw_hash, salt, int(face_label),
             datetime.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def verify(self, username, password):
        """返回 ('ok',) / ('no_user',) / ('wrong_pw',)。"""
        cur = self.conn.execute(
            "SELECT pw_hash, salt FROM users WHERE username=?", (username,)
        )
        row = cur.fetchone()
        if row is None:
            return ("no_user",)
        pw_hash, salt = row
        test_hash, _ = self.hash_password(password, salt)
        if test_hash == pw_hash:
            return ("ok",)
        return ("wrong_pw",)

    def get_by_face_label(self, label):
        cur = self.conn.execute(
            "SELECT username FROM users WHERE face_label=?", (int(label),)
        )
        row = cur.fetchone()
        return row[0] if row else None


# ── 人脸引擎（Haar 检测 + LBPH 识别）─────────────────────────────
class FaceEngine:
    def __init__(self):
        if not os.path.exists(HAAR_FACE):
            raise FileNotFoundError(f"未找到 Haar 模型：{HAAR_FACE}")
        self.haar = cv2.CascadeClassifier(HAAR_FACE)
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        self.trained = False
        if os.path.exists(TRAINER_PATH):
            try:
                self.recognizer.read(TRAINER_PATH)
                self.trained = True
            except Exception:
                self.trained = False

    def detect(self, gray):
        """返回检测到的人脸矩形列表 [(x,y,w,h), ...]。"""
        faces = self.haar.detectMultiScale(
            gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60)
        )
        return list(faces)

    @staticmethod
    def _preprocess(gray):
        """CLAHE 直方图均衡：提升 LBPH 在不同光照 / 姿态下的鲁棒性。
        训练和识别必须都使用同一预处理，否则距离会失真。"""
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)

    def train_all(self):
        """用 faces/ 目录下所有 face_<label>_<idx>.jpg 重新训练并保存。"""
        samples, labels = [], []
        for fn in os.listdir(FACES_DIR):
            if fn.startswith("face_") and fn.endswith(".jpg"):
                try:
                    label = int(fn.split("_")[1])
                except (ValueError, IndexError):
                    continue
                img = cv2.imread(os.path.join(FACES_DIR, fn), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                samples.append(self._preprocess(img))
                labels.append(label)
        if not samples:
            return False
        self.recognizer.train(samples, np.array(labels, dtype=np.int32))
        self.recognizer.save(TRAINER_PATH)
        self.trained = True
        return True

    def predict(self, gray_face):
        """返回 (label, confidence)；未训练返回 (-1, 0)。"""
        if not self.trained:
            return -1, 0.0
        label, conf = self.recognizer.predict(gray_face)
        return int(label), float(conf)


# ── 摄像头人脸采集 / 识别对话框 ──────────────────────────────────
class FaceDialog(QDialog):
    """实时摄像头预览。
    mode='enroll'：采集多张人脸灰度图，finish 后通过 self.samples 返回。
    mode='login' ：点击识别后通过 self.result_label / self.result_user 返回。
    """

    def __init__(self, mode="enroll", db=None, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.db = db
        self.cap = None
        self.engine = None
        self.samples = []          # enroll 模式采集的灰度人脸
        self.result_label = -1     # login 模式预测编号
        self.result_user = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self.setWindowTitle("人脸录入" if mode == "enroll" else "人脸登录")
        self.setMinimumSize(380, 480)
        self._build_ui()
        self._open_camera()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        self.video = QLabel("正在打开摄像头…")
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setStyleSheet("background:#000; color:#888;")
        self.video.setFixedHeight(320)
        lay.addWidget(self.video)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#9ad; font-size:13px;")
        lay.addWidget(self.status)

        btn_row = QHBoxLayout()
        if self.mode == "enroll":
            self.captureBtn = QPushButton("拍摄一张")
            self.captureBtn.clicked.connect(self._capture)
            self.finishBtn = QPushButton("完成录入")
            self.finishBtn.setEnabled(False)
            self.finishBtn.clicked.connect(self._finish)
            btn_row.addWidget(self.captureBtn)
            btn_row.addWidget(self.finishBtn)
        else:
            self.recognizeBtn = QPushButton("开始识别")
            self.recognizeBtn.clicked.connect(self._recognize)
            btn_row.addWidget(self.recognizeBtn)
        self.cancelBtn = QPushButton("取消")
        self.cancelBtn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancelBtn)
        lay.addLayout(btn_row)

        if self.mode == "enroll":
            self.status.setText(f"已采集 0 张（至少 {MIN_SAMPLES} 张可完成）")

    def _open_camera(self):
        try:
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        except Exception:
            self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            QMessageBox.warning(self, "摄像头错误", "无法打开摄像头。")
            self.reject()
            return
        try:
            self.engine = FaceEngine()
        except FileNotFoundError as e:
            QMessageBox.warning(self, "模型缺失", str(e))
            self.reject()
            return
        self._timer.start(30)

    def _frame_to_qimg(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        return QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)

    def _tick(self):
        if self.cap is None:
            return
        ret, frame = self.cap.read()
        if not ret:
            return
        frame = cv2.flip(frame, 1)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.engine.detect(gray)
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        self.video.setPixmap(
            QPixmap.fromImage(self._frame_to_qimg(frame)).scaled(
                self.video.width(), self.video.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
        self._last_gray = gray
        self._last_faces = faces

    def _capture(self):
        if not hasattr(self, "_last_gray") or not self._last_faces:
            self.status.setText("未检测到人脸，请正对摄像头")
            self.status.setStyleSheet("color:#ff7a7a; font-size:13px;")
            return
        # 取最大人脸
        x, y, w, h = max(self._last_faces, key=lambda r: r[2] * r[3])
        face = self._last_gray[y:y + h, x:x + w]
        face = cv2.resize(face, FACE_SIZE)
        face = self.engine._preprocess(face)

        # 录入前先检查：当前人脸是否已被注册（与已有 trainer 模型匹配）
        if self.engine is not None and self.engine.trained:
            label, conf = self.engine.predict(face)
            if label != -1 and conf <= CONF_THRESHOLD:
                user = self.db.get_by_face_label(label) if self.db else None
                who = user if user else f"编号 {label}"
                self.status.setText(f"该人脸已被注册（{who}），请勿重复注册")
                self.status.setStyleSheet("color:#ff7a7a; font-size:13px;")
                return

        self.samples.append(face)
        n = len(self.samples)
        self.status.setText(f"已保存第 {n} 张")
        self.status.setStyleSheet("color:#5cdb8b; font-size:13px;")
        if n >= MIN_SAMPLES:
            self.finishBtn.setEnabled(True)

    def _finish(self):
        if len(self.samples) < MIN_SAMPLES:
            QMessageBox.warning(self, "样本不足", f"至少需 {MIN_SAMPLES} 张人脸样本。")
            return
        QMessageBox.information(self, "保存成功", "人脸样本保存成功！")
        self.accept()

    def _recognize(self):
        if not hasattr(self, "_last_gray") or not self._last_faces:
            self.status.setText("未检测到人脸")
            self.status.setStyleSheet("color:#ff7a7a; font-size:13px;")
            return
        if self.db is None:
            self.status.setText("数据库未就绪")
            self.status.setStyleSheet("color:#ff7a7a; font-size:13px;")
            return
        x, y, w, h = max(self._last_faces, key=lambda r: r[2] * r[3])
        face = self._last_gray[y:y + h, x:x + w]
        face = cv2.resize(face, FACE_SIZE)
        face = self.engine._preprocess(face)
        label, conf = self.engine.predict(face)
        if label == -1:
            self.status.setText("未找到已注册人员，请先注册")
            self.status.setStyleSheet("color:#ff7a7a; font-size:13px;")
            return
        if conf > CONF_THRESHOLD:
            self.status.setText("未匹配到已注册人员，请靠近摄像头或调整角度")
            self.status.setStyleSheet("color:#ff7a7a; font-size:13px;")
            return
        user = self.db.get_by_face_label(label)
        if user is None:
            self.status.setText("未找到对应账号")
            self.status.setStyleSheet("color:#ff7a7a; font-size:13px;")
            return
        self.result_label = label
        self.result_user = user
        self.status.setText(f"识别为 {user}，即将登录…")
        self.status.setStyleSheet("color:#5cdb8b; font-size:13px;")
        QTimer.singleShot(2000, self.accept)

    def closeEvent(self, event):
        self._timer.stop()
        if self.cap is not None:
            self.cap.release()
        super().closeEvent(event)


# ── 登录 / 注册 主窗口 ──────────────────────────────────────────
_STYLE = """
QDialog {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #181a23, stop:1 #0f1118);
    color: #e6e6e6;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
}
QFrame#card {
    background: #1a1d28;
    border: 1px solid #2a2e40;
    border-radius: 14px;
}
QLabel#title {
    font-size: 24px;
    font-weight: bold;
    color: #ffffff;
}
QLabel#sub {
    font-size: 13px;
    color: #8b92a8;
}
QLabel#fieldLabel {
    font-size: 12px;
    color: #9aa2b8;
    margin-bottom: 2px;
}
QLabel#statusOk {
    font-size: 13px;
    color: #5cdb8b;
}
QLabel#statusErr {
    font-size: 13px;
    color: #ff7a7a;
}
QLabel#statusInfo {
    font-size: 13px;
    color: #8b92a8;
}
QLineEdit {
    background: #222636;
    color: #ffffff;
    border: 1px solid #34394f;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 14px;
    min-height: 20px;
}
QLineEdit:focus {
    border: 1px solid #4a9eff;
    background: #252a3d;
}
QLineEdit::placeholder {
    color: #5c627a;
}
QPushButton {
    background: #4a9eff;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 14px;
    font-weight: bold;
    min-height: 20px;
}
QPushButton:hover { background: #3a8eee; }
QPushButton:pressed { background: #2b7ad8; }
QPushButton:disabled {
    background: #353a52;
    color: #6b7088;
}
QPushButton#tabLeft {
    background: transparent;
    color: #8b92a8;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    padding: 8px 0px;
    font-size: 15px;
    font-weight: bold;
}
QPushButton#tabLeft:checked {
    color: #4a9eff;
    border-bottom: 2px solid #4a9eff;
}
QPushButton#tabRight {
    background: transparent;
    color: #8b92a8;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    padding: 8px 0px;
    font-size: 15px;
    font-weight: bold;
}
QPushButton#tabRight:checked {
    color: #4a9eff;
    border-bottom: 2px solid #4a9eff;
}
QPushButton#secondary {
    background: transparent;
    color: #4a9eff;
    border: 1px solid #4a9eff;
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 14px;
    font-weight: bold;
}
QPushButton#secondary:hover {
    background: rgba(74, 158, 255, 0.12);
}
QFrame#sep {
    background: #2a2e40;
}
QMessageBox {
    background: #1a1d28;
}
QMessageBox QLabel {
    color: #ffffff;
    font-size: 14px;
}
QMessageBox QPushButton {
    background: #4a9eff;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 18px;
    font-size: 13px;
    font-weight: bold;
    min-width: 60px;
}
QMessageBox QPushButton:hover {
    background: #3a8eee;
}
"""


class AuthWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = AuthDB()
        # 启动时用 faces/ 重新训练：确保历史人脸也走 CLAHE 预处理，
        # 与登录时的预处理保持一致（否则新旧模型距离会失真）。无样本则跳过。
        try:
            engine = FaceEngine()
            engine.train_all()
        except Exception:
            pass
        self.setWindowTitle("AI 手势无障碍交流系统 — 登录")
        self.setMinimumSize(420, 560)
        self.setStyleSheet(_STYLE)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # 居中卡片
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setFixedWidth(400)
        self.cardLayout = QVBoxLayout(self.card)
        self.cardLayout.setContentsMargins(36, 32, 36, 36)
        self.cardLayout.setSpacing(0)

        # 标题
        title = QLabel("欢迎使用")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel("请登录或注册账号")
        sub.setObjectName("sub")
        sub.setAlignment(Qt.AlignCenter)
        self.cardLayout.addWidget(title)
        self.cardLayout.addSpacing(6)
        self.cardLayout.addWidget(sub)
        self.cardLayout.addSpacing(28)

        # 顶部切换标签
        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)
        self.loginTab = QPushButton("登录")
        self.regTab = QPushButton("注册")
        self.loginTab.setObjectName("tabLeft")
        self.regTab.setObjectName("tabRight")
        self.loginTab.setCheckable(True)
        self.regTab.setCheckable(True)
        self.loginTab.setAutoExclusive(True)
        self.regTab.setAutoExclusive(True)
        self.loginTab.clicked.connect(lambda: self._switch("login"))
        self.regTab.clicked.connect(lambda: self._switch("register"))
        tab_row.addWidget(self.loginTab)
        tab_row.addWidget(self.regTab)
        self.cardLayout.addLayout(tab_row)
        self.cardLayout.addSpacing(20)

        # 内容栈
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_login())
        self.stack.addWidget(self._build_register())
        self.cardLayout.addWidget(self.stack, 1)

        # 把卡片居中
        root.addStretch(1)
        root.addWidget(self.card, 0, Qt.AlignCenter)
        root.addStretch(1)

        self.setMinimumSize(460, 600)
        self.resize(460, 620)
        self._switch("login")

    # ---- 登录页 ----
    def _build_login(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.setAlignment(Qt.AlignTop)

        self.lg_user = QLineEdit()
        self.lg_user.setPlaceholderText("请输入账号")
        self.lg_pw = QLineEdit()
        self.lg_pw.setEchoMode(QLineEdit.Password)
        self.lg_pw.setPlaceholderText("请输入密码")

        lay.addWidget(self.lg_user)
        lay.addWidget(self.lg_pw)
        lay.addSpacing(8)

        pw_login = QPushButton("密码登录")
        pw_login.setDefault(True)
        pw_login.clicked.connect(self._on_password_login)
        lay.addWidget(pw_login)

        face_login = QPushButton("人脸登录")
        face_login.setObjectName("secondary")
        face_login.clicked.connect(self._on_face_login)
        lay.addWidget(face_login)

        self.lg_status = QLabel("")
        self.lg_status.setObjectName("statusErr")
        self.lg_status.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lg_status)
        lay.addStretch(1)
        return w

    # ---- 注册页 ----
    def _build_register(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.setAlignment(Qt.AlignTop)

        self.rg_user = QLineEdit()
        self.rg_user.setPlaceholderText("登录账号")
        self.rg_pw = QLineEdit()
        self.rg_pw.setEchoMode(QLineEdit.Password)
        self.rg_pw.setPlaceholderText("密码")
        self.rg_pw2 = QLineEdit()
        self.rg_pw2.setEchoMode(QLineEdit.Password)
        self.rg_pw2.setPlaceholderText("确认密码")
        self.rg_id = QLineEdit()
        self.rg_id.setPlaceholderText("人脸编号（数字，如 1001）")

        lay.addWidget(self.rg_user)
        lay.addWidget(self.rg_pw)
        lay.addWidget(self.rg_pw2)
        lay.addWidget(self.rg_id)
        lay.addSpacing(8)

        enroll = QPushButton("录入人脸")
        enroll.setObjectName("secondary")
        enroll.clicked.connect(self._on_enroll)
        lay.addWidget(enroll)

        self.rg_face_ok = QLabel("尚未录入人脸")
        self.rg_face_ok.setObjectName("statusInfo")
        self.rg_face_ok.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.rg_face_ok)

        reg = QPushButton("注册")
        reg.clicked.connect(self._on_register)
        lay.addWidget(reg)

        self.rg_status = QLabel("")
        self.rg_status.setObjectName("statusOk")
        self.rg_status.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.rg_status)
        lay.addStretch(1)

        self._pending_samples = None
        return w

    def _switch(self, page):
        if page == "login":
            self.stack.setCurrentIndex(0)
            self.loginTab.setChecked(True)
            self.regTab.setChecked(False)
        else:
            self.stack.setCurrentIndex(1)
            self.loginTab.setChecked(False)
            self.regTab.setChecked(True)

    # ---- 登录逻辑 ----
    def _on_password_login(self):
        user = self.lg_user.text().strip()
        pw = self.lg_pw.text()
        if not user or not pw:
            self.lg_status.setText("请填写账号和密码")
            return
        res = self.db.verify(user, pw)
        if res[0] == "no_user":
            self.lg_status.setText("登录失败，请注册")
        elif res[0] == "wrong_pw":
            self.lg_status.setText("登录失败，用户名或密码错误")
        else:
            self._login_ok(user)

    def _on_face_login(self):
        dlg = FaceDialog(mode="login", db=self.db, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.result_user:
            self._login_ok(dlg.result_user)
        else:
            # 状态已在对话框内提示；这里不额外报错避免重复
            pass

    def _login_ok(self, user):
        QMessageBox.information(self, "登录成功", f"欢迎回来，{user}！")
        self.accept()

    # ---- 注册逻辑 ----
    def _on_enroll(self):
        dlg = FaceDialog(mode="enroll", db=self.db, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._pending_samples = dlg.samples
            self.rg_face_ok.setText(f"已录入 {len(dlg.samples)} 张人脸")
            self.rg_face_ok.setObjectName("statusOk")
            self.rg_face_ok.setStyleSheet("")
        else:
            self._pending_samples = None
            self.rg_face_ok.setText("尚未录入人脸")
            self.rg_face_ok.setObjectName("statusInfo")
            self.rg_face_ok.setStyleSheet("")

    def _on_register(self):
        user = self.rg_user.text().strip()
        pw = self.rg_pw.text()
        pw2 = self.rg_pw2.text()
        id_text = self.rg_id.text().strip()

        if not user:
            self.rg_status.setObjectName("statusErr")
            self.rg_status.setText("请填写账号")
            self.rg_status.setStyleSheet("")
            return
        if not pw or pw != pw2:
            self.rg_status.setObjectName("statusErr")
            self.rg_status.setText("密码为空或两次不一致")
            self.rg_status.setStyleSheet("")
            return
        try:
            face_label = int(id_text)
        except ValueError:
            self.rg_status.setObjectName("statusErr")
            self.rg_status.setText("人脸编号必须是数字")
            self.rg_status.setStyleSheet("")
            return
        if self.db.user_exists(user):
            self.rg_status.setObjectName("statusErr")
            self.rg_status.setText("该账号已存在")
            self.rg_status.setStyleSheet("")
            return
        if self.db.face_label_exists(face_label):
            self.rg_status.setObjectName("statusErr")
            self.rg_status.setText("该人脸编号已被占用")
            self.rg_status.setStyleSheet("")
            return
        if not self._pending_samples or len(self._pending_samples) < MIN_SAMPLES:
            self.rg_status.setObjectName("statusErr")
            self.rg_status.setText("请先录入足够的人脸样本")
            self.rg_status.setStyleSheet("")
            return

        # 保存人脸图片（带编号）
        for i, face in enumerate(self._pending_samples):
            cv2.imwrite(
                os.path.join(FACES_DIR, f"face_{face_label}_{i}.jpg"), face
            )
        # 写库
        self.db.add_user(user, pw, face_label)
        # 重新训练识别器
        try:
            engine = FaceEngine()
            engine.train_all()
        except Exception as e:
            self.rg_status.setObjectName("statusErr")
            self.rg_status.setText(f"训练失败：{e}")
            self.rg_status.setStyleSheet("")
            return

        self.rg_status.setObjectName("statusOk")
        self.rg_status.setText("注册成功！请切换到登录")
        self.rg_status.setStyleSheet("font-size:14px; font-weight:bold;")
        QMessageBox.information(self, "注册成功", "注册成功！现在可以用密码或人脸登录。")
        self._switch("login")
        self.lg_user.setText(user)

    def closeEvent(self, event):
        self.db.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = AuthWindow()
    if w.exec() == QDialog.Accepted:
        print("登录成功")
    else:

        print("已取消")
