"""
基于 MediaPipe 的手势识别系统
功能：实时摄像头识别 -> 预设手势分类 + 手指数量 + 手势方向 + 左右手
操作：按 ESC 或 q 退出
运行：python gesture_recognition.py
"""

import os
import sys

# 屏蔽 TensorFlow / MediaPipe / Abseil 的冗余日志
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["GLOG_minloglevel"] = "3"
os.environ["MEDIAPIPE_LOG_LEVEL"] = "0"

import contextlib

@contextlib.contextmanager
def suppress_stderr():
    """临时屏蔽 C++ 层 stderr 输出（MediaPipe/TFLite 初始化警告）。"""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(devnull)

import cv2
import numpy as np
import mediapipe as mp
from PIL import Image, ImageDraw, ImageFont


# ── 中文字体 ──────────────────────────────────────────────
def _load_font(size=24):
    """加载 Windows 系统中文字体"""
    for path in [
        "C:/Windows/Fonts/msyh.ttc",   # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",  # 黑体
        "C:/Windows/Fonts/simsun.ttc",  # 宋体
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


FONT = _load_font(24)


# ── 工具函数 ──────────────────────────────────────────────

def count_fingers(hand_landmarks, handedness):
    """
    根据 21 个关键点判断伸出的手指数量。
    返回 (数量, 各手指状态列表[拇指, 食指, 中指, 无名指, 小指])。
    """
    landmarks = hand_landmarks.landmark
    fingers_up = []

    # 拇指：比较 x 坐标
    # 画面已镜像翻转，MediaPipe 标签即为用户视角
    is_right = handedness.classification[0].label == "Right"
    if is_right:
        fingers_up.append(landmarks[4].x < landmarks[3].x)
    else:
        fingers_up.append(landmarks[4].x > landmarks[3].x)

    # 其余四指：指尖 y < pip y => 伸出（画面坐标 y 向下）
    tip_pip_pairs = [(8, 6), (12, 10), (16, 14), (20, 18)]
    for tip_idx, pip_idx in tip_pip_pairs:
        fingers_up.append(landmarks[tip_idx].y < landmarks[pip_idx].y)

    return sum(fingers_up), fingers_up


def classify_gesture(hand_landmarks, fingers_up, count):
    """根据手指状态和关键点距离判断预设手势。"""
    landmarks = hand_landmarks.landmark

    def dist(a, b):
        return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5

    thumb, index, middle, ring, pinky = fingers_up
    thumb_index_dist = dist(landmarks[4], landmarks[8])
    palm_width = dist(landmarks[2], landmarks[17])

    # OK：拇指尖和食指尖靠近（成圈），其余三指伸直
    if thumb_index_dist < palm_width * 0.3 and middle and ring and pinky:
        return "OK"

    # 比心：拇指+食指指尖靠近交叉，其余三指握拢
    if (thumb and index and not middle and not ring and not pinky
            and thumb_index_dist < palm_width * 0.35):
        return "比心"

    # 打电话（Shaka）：大拇指+小指伸出，中间三指握拢
    if thumb and pinky and not index and not middle and not ring:
        return "打电话"

    # 安静：仅食指伸出，拇指搭在食指第二指节上
    if (not thumb and index and not middle and not ring and not pinky
            and dist(landmarks[4], landmarks[6]) < palm_width * 0.35):
        return "安静"

    # 握拳：0 指
    if count == 0:
        return "握拳"

    # 张开手掌 / 五指全伸
    if count == 5:
        return "张开手掌"

    # ── 单指伸出 ─────────────────────────────────
    if count == 1:
        if thumb:
            # 拇指向下 vs 点赞（朝上）
            # 拇指尖(4)在拇指IP关节(3)下方 => 朝下
            if landmarks[4].y > landmarks[3].y + 0.06:
                return "拇指向下"
            return "点赞"
        elif index:
            # 食指竖起 vs 指向（水平）
            wrist = landmarks[0]
            tip = landmarks[8]
            # 指尖相对于手腕的方向：y向上偏移多 => 竖起
            if tip.y < wrist.y - 0.08:   # 画面 y 轴向下，小 = 上
                return "食指竖起"
            return "指向"

    # 胜利 / 剪刀手：食指 + 中指
    if count == 2 and index and middle:
        return "胜利"

    # 三指：拇指 + 食指 + 中指
    if count == 3 and thumb and index and middle:
        return "三指"

    # 四指：除拇指外全伸
    if count == 4 and index and middle and ring and pinky:
        return "四指"

    return f"未知({count}指)"


def detect_direction(hand_landmarks):
    """根据手腕(0)到中指根(9)的向量判断手势方向。"""
    landmarks = hand_landmarks.landmark
    wrist = landmarks[0]
    middle_mcp = landmarks[9]
    dx = middle_mcp.x - wrist.x
    dy = middle_mcp.y - wrist.y

    if abs(dx) > abs(dy):
        if dx > 0.05:
            return "右"
        elif dx < -0.05:
            return "左"
    else:
        if dy < -0.05:
            return "上"
        elif dy > 0.05:
            return "下"
    return "正中"


# ── 手势含义映射 ──────────────────────────────────────────

GESTURE_MEANINGS = {
    "OK": "好的 / 确定 / 没问题",
    "握拳": "坚持 / 加油 / 力量 / 团结",
    "张开手掌": "停止 / 拒绝 / 稍等",
    "点赞": "赞赏 / 棒 / 同意 / 没问题 / 搞定",
    "拇指向下": "差劲 / 反对 / 不同意 / 否定",
    "指向": "指示方向 / 提示",
    "胜利": "胜利 / 和平 / 数字2",
    "食指竖起": "提示注意 / 稍等一下 / 数字1",
    "安静": "保持安静 / 闭嘴 / 保密",
    "打电话": "给我打电话 / 放松 / 酷",
    "比心": "表达爱意 / 感谢",
    "三指": "发誓 / 强调",
    "四指": "宣誓 / 保证",
}


def get_gesture_meaning(gesture_name):
    """根据手势名称返回对应含义，未知手势返回空字符串。"""
    return GESTURE_MEANINGS.get(gesture_name, "")


def draw_text_cn(img, lines):
    """用 PIL 在 OpenCV 图像上绘制中文文字（带描边）。"""
    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    y = 12
    for line in lines:
        # 白色描边
        for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2),
                        (-1, -1), (1, -1), (-1, 1), (1, 1)]:
            draw.text((15 + ox, y + oy), line, font=FONT, fill=(255, 255, 255))
        # 正文
        color = (200, 0, 0) if "未检测" in line else (0, 0, 0)
        draw.text((15, y), line, font=FONT, fill=color)
        y += 32

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


# ── 主程序 ────────────────────────────────────────────────

def main():
    mp_hands = mp.solutions.hands
    with suppress_stderr():
        hands = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("错误：无法打开摄像头")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("手势识别系统已启动，按 ESC 或 q 退出。")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("错误：无法读取摄像头画面")
            break

        # 镜像翻转（自拍视角），翻转后 MediaPipe 标签即为用户视角
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        info_lines = []

        if results.multi_hand_landmarks:
            for idx, hand_lms in enumerate(results.multi_hand_landmarks):
                handedness = results.multi_handedness[idx]
                # 画面已镜像，MediaPipe 标签直接对应用户视角
                hand_label = handedness.classification[0].label
                hand_label_cn = "右手" if hand_label == "Right" else "左手"

                count, fingers_up = count_fingers(hand_lms, handedness)
                gesture = classify_gesture(hand_lms, fingers_up, count)
                direction = detect_direction(hand_lms)

                info_lines.append(f"手{idx + 1}: {hand_label_cn}")
                info_lines.append(f"  手势: {gesture}")
                info_lines.append(f"  手指: {count}/5")
                info_lines.append(f"  方向: {direction}")
        else:
            info_lines.append("未检测到手")

        frame = draw_text_cn(frame, info_lines)
        cv2.imshow("Gesture Recognition - ESC/q to quit", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == 27 or key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    hands.close()
    print("程序已退出。")


if __name__ == "__main__":
    main()
