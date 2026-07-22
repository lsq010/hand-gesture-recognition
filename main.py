"""
手势识别系统 - GUI 版主程序（双手识别）
将 MediaPipe 手势识别与 PySide6 UI 界面结合
运行:python main.py
"""

import cv2
import os
import sys
import time
import csv


# 确保能找到同目录下的 rec.py 和 gesture_recognition.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入手势识别核心函数（会连带导入 cv2 / mediapipe / PIL 等）
from gesture_recognition import (
    count_fingers,
    classify_gesture,
    detect_direction,
    get_gesture_meaning,
    suppress_stderr,
)


import mediapipe as mp
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QFileDialog,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap

from rec import Ui_Form


class GestureApp(QWidget):
    """手势识别系统主窗口"""

    def __init__(self):
        super().__init__()
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        # ── MediaPipe Hands 初始化 ──
        with suppress_stderr():
            self.mp_hands = mp.solutions.hands
            self.hands = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.6,
                min_tracking_confidence=0.5,
            )
        self.mp_draw = mp.solutions.drawing_utils

        # ── 摄像头 & 定时器 ──
        self.cap = None
        self.running = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._process_frame)

        # ── FPS 计算 ──
        self._prev_time = 0.0
        self._fps = 0

        # ── 日志数据 ──
        self._log_data: list[dict] = []
        self._last_left_gesture = ""
        self._last_right_gesture = ""

        # ── 截图缓存 ──
        self._last_screenshot = None   # BGR，供保存用
        self._frozen = False            # 画面冻结标志
        self._frozen_frame = None       # 冻结帧（RGB，供显示用）

        # ── 信号连接 ──
        self.ui.openCamButton.clicked.connect(self.open_camera)
        self.ui.closeCamButton.clicked.connect(self.close_camera)
        self.ui.screenshotButton.clicked.connect(self._on_screenshot_clicked)
        self.ui.saveButton.clicked.connect(self.save_screenshot)
        self.ui.exportButton.clicked.connect(self.export_log)

        # ── 初始状态 ──
        self.ui.closeCamButton.setEnabled(False)
        self._reset_result_labels()
        self.ui.statusBar.setText("状态栏：系统就绪 | FPS: --")

    # ── 摄像头控制 ──────────────────────────────────────────

    def open_camera(self):
        """打开摄像头并启动帧处理定时器。"""
        if self.cap is not None and self.cap.isOpened():
            return

        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            self.ui.statusBar.setText("状态栏：摄像头打开失败 | FPS: --")
            QMessageBox.warning(self, "错误", "无法打开摄像头，请检查设备连接。")
            return

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self.running = True
        self._prev_time = 0.0
        self._fps = 0
        self.timer.start(33)  # ~30 FPS

        self.ui.openCamButton.setEnabled(False)
        self.ui.closeCamButton.setEnabled(True)
        self.ui.statusBar.setText("状态栏：摄像头运行中 | FPS: --")
        # 恢复按钮状态（如果之前冻结过）
        self._frozen = False
        self._frozen_frame = None
        self.ui.screenshotButton.setText("📷 截图")

    def close_camera(self):
        """关闭摄像头并停止定时器。"""
        self.running = False
        self.timer.stop()

        if self.cap is not None:
            self.cap.release()
            self.cap = None

        # 恢复画面占位
        self.ui.camLabel.clear()
        self.ui.camLabel.setText("CAM 画面展示区")
        self.ui.camLabel.setStyleSheet(
            "border: none; background-color: transparent; color: #888888;"
        )

        # 恢复结果占位
        self._reset_result_labels()

        # 重置冻结状态
        self._frozen = False
        self._frozen_frame = None
        self.ui.screenshotButton.setText("📷 截图")

        self.ui.openCamButton.setEnabled(True)
        self.ui.closeCamButton.setEnabled(False)
        self.ui.statusBar.setText("状态栏：摄像头已关闭 | FPS: --")

    # ── 结果标签重置 / 更新 ─────────────────────────────────

    def _reset_result_labels(self):
        """将左右手结果和手势含义恢复为初始占位状态。"""
        self.ui.leftGestureLabelValue.setText("未检测")
        self.ui.leftFingerLabelValue.setText("— / 5")
        self.ui.leftDirectionLabelValue.setText("—")

        self.ui.rightGestureLabelValue.setText("未检测")
        self.ui.rightFingerLabelValue.setText("— / 5")
        self.ui.rightDirectionLabelValue.setText("—")

        self.ui.meaningLabelValue.setText("等待识别...")
        self._last_left_gesture = ""
        self._last_right_gesture = ""

    def _update_hand_labels(self, side, gesture, count, direction):
        """更新指定手（"left" 或 "right"）的结果标签。"""
        if side == "left":
            self.ui.leftGestureLabelValue.setText(gesture)
            self.ui.leftFingerLabelValue.setText(f"{count} / 5")
            self.ui.leftDirectionLabelValue.setText(direction)
        else:
            self.ui.rightGestureLabelValue.setText(gesture)
            self.ui.rightFingerLabelValue.setText(f"{count} / 5")
            self.ui.rightDirectionLabelValue.setText(direction)

    def _update_meaning(self, gestures):
        """根据检测到的手势列表更新含义区域。"""
        if not gestures:
            self.ui.meaningLabelValue.setText("等待识别...")
            return

        meanings = []
        for hand_label_cn, gesture in gestures:
            meaning = get_gesture_meaning(gesture)
            if meaning:
                meanings.append(f"{hand_label_cn}「{gesture}」：{meaning}")
            else:
                meanings.append(f"{hand_label_cn}「{gesture}」")

        self.ui.meaningLabelValue.setText("  |  ".join(meanings) if meanings else "等待识别...")

    # ── 帧处理（定时器回调）──────────────────────────────────

    def _process_frame(self):
        """读取一帧 -> MediaPipe 识别 -> 绘制骨架 -> 更新 UI。"""
        if not self.running or self.cap is None:
            return

        # ── 冻结模式：持续显示冻结画面（支持窗口缩放自适应）──
        if self._frozen and self._frozen_frame is not None:
            h, w, ch = self._frozen_frame.shape
            bytes_per_line = ch * w
            q_img = QImage(
                self._frozen_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888
            ).copy()
            pixmap = QPixmap.fromImage(q_img)
            self.ui.camLabel.setText("")
            self.ui.camLabel.setStyleSheet("border: none; background-color: transparent;")
            self.ui.camLabel.setPixmap(
                pixmap.scaled(
                    self.ui.camLabel.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            return

        ret, frame = self.cap.read()
        if not ret:
            return

        # 镜像翻转（自拍视角）
        if self.ui.mirrorCheck.isChecked():
            frame = cv2.flip(frame, 1)

        # BGR -> RGB（MediaPipe 需 RGB 输入，Qt 显示也用 RGB888）
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb)

        # ── 绘制手部骨架 ──
        if self.ui.drawSkeletonCheck.isChecked() and results.multi_hand_landmarks:
            for hand_lms in results.multi_hand_landmarks:
                self.mp_draw.draw_landmarks(
                    rgb,
                    hand_lms,
                    self.mp_hands.HAND_CONNECTIONS,
                    self.mp_draw.DrawingSpec(
                        color=(0, 255, 255), thickness=2, circle_radius=4
                    ),
                    self.mp_draw.DrawingSpec(
                        color=(255, 255, 255), thickness=2
                    ),
                )

        # ── 识别结果 ──
        detected_gestures = []  # [(hand_label_cn, gesture), ...]
        found_left = False
        found_right = False

        if results.multi_hand_landmarks:
            for idx, hand_lms in enumerate(results.multi_hand_landmarks):
                handedness = results.multi_handedness[idx]
                hand_label = handedness.classification[0].label
                hand_label_cn = "右手" if hand_label == "Right" else "左手"
                side = "right" if hand_label == "Right" else "left"

                count, fingers_up = count_fingers(hand_lms, handedness)
                gesture = classify_gesture(hand_lms, fingers_up, count)
                direction = detect_direction(hand_lms)

                self._update_hand_labels(side, gesture, count, direction)
                detected_gestures.append((hand_label_cn, gesture))

                if side == "left":
                    found_left = True
                else:
                    found_right = True

                # 记录日志（手势变化时记录，避免数据爆炸）
                last_attr = f"_last_{side}_gesture"
                if gesture != getattr(self, last_attr):
                    self._log_data.append(
                        {
                            "时间": time.strftime("%H:%M:%S"),
                            "手势": gesture,
                            "手指数": count,
                            "方向": direction,
                            "手型": hand_label_cn,
                        }
                    )
                    setattr(self, last_attr, gesture)

        # 未检测到的手显示占位
        if not found_left:
            self.ui.leftGestureLabelValue.setText("未检测")
            self.ui.leftFingerLabelValue.setText("0 / 5")
            self.ui.leftDirectionLabelValue.setText("—")
            self._last_left_gesture = ""
        if not found_right:
            self.ui.rightGestureLabelValue.setText("未检测")
            self.ui.rightFingerLabelValue.setText("0 / 5")
            self.ui.rightDirectionLabelValue.setText("—")
            self._last_right_gesture = ""

        self._update_meaning(detected_gestures)

        # ── FPS 计算（基于实际帧间隔时间）──
        curr_time = time.time()
        if self._prev_time > 0:
            dt = curr_time - self._prev_time
            if dt > 0:
                instant_fps = 1.0 / dt
                if self._fps == 0:
                    self._fps = int(instant_fps)
                else:
                    # 平滑处理，避免数值剧烈跳动
                    self._fps = int(self._fps * 0.7 + instant_fps * 0.3)
        self._prev_time = curr_time

        # ── 显示画面到 camLabel ──
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        q_img = QImage(
            rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888
        ).copy()  # copy() 确保 Qt 持有数据所有权
        pixmap = QPixmap.fromImage(q_img)

        self.ui.camLabel.setText("")
        self.ui.camLabel.setStyleSheet(
            "border: none; background-color: transparent;"
        )
        self.ui.camLabel.setPixmap(
            pixmap.scaled(
                self.ui.camLabel.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        # ── 更新状态栏 ──
        self.ui.statusBar.setText(f"状态栏：运行中 | FPS: {self._fps}")

    def _on_screenshot_clicked(self):
        """截图/继续按钮切换。"""
        if self._frozen:
            self._resume_feed()
        else:
            self.take_screenshot()

    # ── 截图 & 保存 & 导出 ─────────────────────────────────

    def take_screenshot(self):
        """截取当前画面，冻结摄像头画面，按钮变为「继续」。"""
        if not self.running or self.cap is None:
            QMessageBox.warning(self, "提示", "请先打开摄像头。")
            return

        ret, frame = self.cap.read()
        if not ret:
            QMessageBox.warning(self, "错误", "无法获取画面。")
            return

        if self.ui.mirrorCheck.isChecked():
            frame = cv2.flip(frame, 1)

        # ── 如果开启手部骨架，在截图帧上绘制骨架 ──
        if self.ui.drawSkeletonCheck.isChecked():
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.hands.process(rgb)
            if results.multi_hand_landmarks:
                for hand_lms in results.multi_hand_landmarks:
                    self.mp_draw.draw_landmarks(
                        rgb,
                        hand_lms,
                        self.mp_hands.HAND_CONNECTIONS,
                        self.mp_draw.DrawingSpec(
                            color=(0, 255, 255), thickness=2, circle_radius=4
                        ),
                        self.mp_draw.DrawingSpec(
                            color=(255, 255, 255), thickness=2
                        ),
                    )
            # 保存用 BGR，显示用 RGB
            frame_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            self._last_screenshot = frame_bgr  # BGR，供保存用
            self._frozen_frame = rgb             # RGB，供显示用
        else:
            self._last_screenshot = frame.copy()  # BGR，供保存用
            self._frozen_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)  # RGB，供显示用
        self.ui.saveButton.setEnabled(True)
        self._frozen = True
        self.ui.screenshotButton.setText("⏩ 继续")

    def _resume_feed(self):
        """恢复摄像头画面，按钮变回「截图」。"""
        self._frozen = False
        self._frozen_frame = None
        self.ui.screenshotButton.setText("📷 截图")
        self.ui.statusBar.setText(f"状态栏：运行中 | FPS: {self._fps}")

    def save_screenshot(self):
        """将内存中的截图保存为图片文件，保存后保持冻结状态。"""
        if self._last_screenshot is None:
            QMessageBox.warning(self, "提示", "没有可保存的截图，请先点击「截图」。")
            return

        default_name = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        default_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), default_name
        )

        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存截图", default_path, "PNG (*.png);;JPEG (*.jpg)"
        )
        if file_path:
            cv2.imwrite(file_path, self._last_screenshot)
            self.ui.statusBar.setText(
                f"状态栏：截图已保存至 {os.path.basename(file_path)} | 画面已冻结"
            )

    def export_log(self):
        """将识别日志导出为 CSV 文件。"""
        if not self._log_data:
            QMessageBox.information(self, "提示", "暂无识别数据可导出。")
            return

        default_name = f"gesture_log_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        default_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), default_name
        )

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", default_path, "CSV (*.csv)"
        )
        if file_path:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["时间", "手势", "手指数", "方向", "手型"],
                )
                writer.writeheader()
                writer.writerows(self._log_data)
            self.ui.statusBar.setText(
                f"状态栏：日志已导出（{len(self._log_data)} 条）| FPS: {self._fps}"
            )

    # ── 键盘 & 窗口关闭 ────────────────────────────────────

    def keyPressEvent(self, event):
        """ESC 退出程序。"""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """窗口关闭时清理资源。"""
        self.close_camera()
        self.hands.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = GestureApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
