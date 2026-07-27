# vision_engine.py
# 极速手部感知引擎（Phase A：纯 MediaPipe Hands + 静态手势分类）
#
# 设计目标：只做手部，彻底移除 Haar 人脸 / FER 表情 / 几何头姿，
# 因此 CPU 占用极低，适合轻薄本（i5-1240P 等无独显机型）。
#
# 依赖：opencv-python, mediapipe
# 性能：model_complexity=0（Lite 手模型）榨干 CPU 性能；
#       双手检测；每帧推理（仅 Hands，足够快，YOLO 接入时再加节流）。

import platform

import cv2
import mediapipe as mp
from gesture_classifier import GestureClassifier


class VisionEngine:
    def __init__(self, camera_index=0):
        # Windows 上用 CAP_DSHOW 后端打开摄像头，比默认 Media Foundation 快很多
        # （首帧延迟从数秒降到数百毫秒），直接解决「打开摄像头很慢」。
        if platform.system() == "Windows":
            try:
                self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
            except Exception:  # noqa: BLE001
                self.cap = cv2.VideoCapture(camera_index)
        else:
            self.cap = cv2.VideoCapture(camera_index)

        # 初始化 MediaPipe Hands (补上 model_complexity=0 榨干 CPU 性能)
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,          # 极速模式，大幅降低 CPU 占用
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,  # 调低：快速画圆/挥手时减少漏检，避免轨迹断笔
        )
        self.mp_draw = mp.solutions.drawing_utils
        self.classifier = GestureClassifier()
        self.draw_skeleton = True  # 主程序可在游戏模式置 False，自动隐藏手部骨骼

    def process_frame(self):
        """
        抓取一帧，运行 MediaPipe Hands，返回处理后的画面与手势结果
        """
        ret, frame = self.cap.read()
        if not ret:
            return None, {}

        # 镜像翻转，符合用户视觉习惯
        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb_frame)

        parsed_results = {
            "left_gesture": "None",
            "right_gesture": "None",
            "is_heart": False,
            "left_landmarks": None,
            "right_landmarks": None,
            "left_fingers": 0,
            "right_fingers": 0,
            "left_direction": "·",
            "right_direction": "·",
        }

        left_lms, right_lms = None, None

        if results.multi_hand_landmarks and results.multi_handedness:
            for hand_lms, handedness in zip(results.multi_hand_landmarks, results.multi_handedness):
                # 绘制手部骨骼（游戏中主程序会置 draw_skeleton=False 自动隐藏）
                if self.draw_skeleton:
                    self.mp_draw.draw_landmarks(frame, hand_lms, self.mp_hands.HAND_CONNECTIONS)

                # MediaPipe 的左右手标签 (由于图像已翻转，需注意对应)
                hand_label = handedness.classification[0].label  # "Left" 或 "Right"
                gesture = self.classifier.classify_hand(hand_lms.landmark)
                finger_count = self.classifier.count_extended_fingers(hand_lms.landmark)
                direction = self.classifier.finger_direction(hand_lms.landmark)

                if hand_label == "Left":
                    left_lms = hand_lms.landmark
                    parsed_results["left_gesture"] = gesture
                    parsed_results["left_landmarks"] = left_lms
                    parsed_results["left_fingers"] = finger_count
                    parsed_results["left_direction"] = direction
                else:
                    right_lms = hand_lms.landmark
                    parsed_results["right_gesture"] = gesture
                    parsed_results["right_landmarks"] = right_lms
                    parsed_results["right_fingers"] = finger_count
                    parsed_results["right_direction"] = direction

            # 校验双手比心
            if left_lms and right_lms:
                parsed_results["is_heart"] = self.classifier.check_heart_gesture(left_lms, right_lms)

        return frame, parsed_results

    def release(self):
        self.cap.release()
        self.hands.close()
