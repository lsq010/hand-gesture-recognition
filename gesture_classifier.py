# gesture_classifier.py
# 纯几何静态手势分类器（不依赖深度学习，CPU 占用极低）
# 输入：MediaPipe Hands 的 21 个归一化关键点（landmarks[i].x / .y）
# 输出：静态手势字符串 Fist / OK / Pointing / Num_1~5 / ThumbUp / ThumbDown
#                       / FingerHeart(比心) / Phone(打电话) / Unknown
#
# 关键点约定（MediaPipe Hands）：
#   0 = 手腕(Wrist)
#   4/8/12/16/20 = 五指指尖(Thumb/Index/Middle/Ring/Pinky)
#   5/9/13/17     = 对应掌指关节(MCP)
#
# 伸直判断：指尖到手腕距离 > 对应 MCP 到手腕距离 * 1.1
# Num_1 vs Pointing（方案 B）：仅食指伸时，按食指相对竖直方向的夹角区分
#   - 食指基本朝正上方(夹角 < 35°) → 数字 1
#   - 食指偏向侧方/下方(夹角 >= 35°) → 指向(物体/方向)

import math


class GestureClassifier:
    def __init__(self):
        pass

    @staticmethod
    def _dist(p1, p2):
        """计算两点间的欧氏距离 (x, y)"""
        return math.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2)

    def _is_finger_extended(self, landmarks, tip_idx, mcp_idx, wrist_idx=0):
        """判断手指是否伸直：指尖到手腕距离 > MCP到手腕距离"""
        d_tip = self._dist(landmarks[tip_idx], landmarks[wrist_idx])
        d_mcp = self._dist(landmarks[mcp_idx], landmarks[wrist_idx])
        return d_tip > d_mcp * 1.1

    def classify_hand(self, landmarks):
        """
        输入: MediaPipe 的 21 个手部关键点列表
        输出: 静态手势字符串 (Fist, OK, Pointing, Num_1~5, ThumbUp, ThumbDown,
              FingerHeart, Phone, Unknown)
        """
        if not landmarks or len(landmarks) < 21:
            return "Unknown"

        # 1. 检查四指伸直状态 (食指, 中指, 无名指, 小指)
        index_ext = self._is_finger_extended(landmarks, 8, 5)
        middle_ext = self._is_finger_extended(landmarks, 12, 9)
        ring_ext = self._is_finger_extended(landmarks, 16, 13)
        pinky_ext = self._is_finger_extended(landmarks, 20, 17)

        # 拇指特判 (4号尖到17号小指根部的距离)
        thumb_ext = self._dist(landmarks[4], landmarks[17]) > self._dist(landmarks[2], landmarks[17])

        # 2. 特殊手势判定
        # OK 手势：食指尖 (8) 与 拇指尖 (4) 贴合，中/无/小指伸直
        d_thumb_index = self._dist(landmarks[4], landmarks[8])
        d_ref = self._dist(landmarks[0], landmarks[9])  # 手掌参考基准长度
        if d_thumb_index < d_ref * 0.2 and middle_ext and ring_ext:
            return "OK"

        # 比心 (🫰 FingerHeart)：拇指尖与食指尖靠拢成小环；拇指需伸开(排除握拳)，
        # 且不构成 OK(中/无同时伸)
        if d_thumb_index < d_ref * 0.25 and thumb_ext and not (middle_ext and ring_ext):
            return "FingerHeart"

        # 打电话 (🤙 Phone / CallMe)：仅拇指 + 小指伸直，食/中/无指弯曲
        if thumb_ext and pinky_ext and not index_ext and not middle_ext and not ring_ext:
            return "Phone"

        # 握拳 (Fist)：五指全部弯曲
        if not any([thumb_ext, index_ext, middle_ext, ring_ext, pinky_ext]):
            return "Fist"

        # 只有食指伸直的情况：区分「数字 1」与「指向 Pointing」(方案 B)
        if index_ext and not middle_ext and not ring_ext and not pinky_ext and not thumb_ext:
            wrist = landmarks[0]
            index_tip = landmarks[8]

            # 计算食指向量 (dx, dy)，注意图像坐标系中 y 轴朝下
            dx = index_tip.x - wrist.x
            dy = index_tip.y - wrist.y  # dy < 0 表示指尖在手腕上方

            # 计算食指与垂直向上方向(-Y轴)的夹角 (弧度 -> 角度)
            # Math.atan2(dx, -dy) 给出相对于正上方的偏移角
            angle_from_vertical = math.degrees(math.atan2(abs(dx), -dy))

            # 如果食指基本朝正上方 (夹角小于 35 度)，判定为「数字 1」；否则为「指向」
            if dy < 0 and angle_from_vertical < 35:
                return "Num_1"
            else:
                return "Pointing"

        # 数字识别 (2 ~ 5)
        ext_count = sum([index_ext, middle_ext, ring_ext, pinky_ext])
        if ext_count > 1:
            if thumb_ext:
                ext_count += 1
            return f"Num_{ext_count}"

        # 只有拇指伸直：按拇指朝向区分 点赞(ThumbUp) / 拇指向下(ThumbDown)
        if thumb_ext and not any([index_ext, middle_ext, ring_ext, pinky_ext]):
            wrist = landmarks[0]
            thumb_tip = landmarks[4]
            dy = thumb_tip.y - wrist.y  # 图像 y 朝下：dy<0 指尖在手腕上方
            if dy > 0.05:
                return "ThumbDown"
            return "ThumbUp"

        return "Unknown"

    def check_heart_gesture(self, left_landmarks, right_landmarks):
        """
        双手比心判定：左食指尖(8)靠拢右食指尖(8)，左拇指尖(4)靠拢右拇指尖(4)
        """
        if not left_landmarks or not right_landmarks:
            return False

        d_ref = self._dist(left_landmarks[0], left_landmarks[9])
        d_index = self._dist(left_landmarks[8], right_landmarks[8])
        d_thumb = self._dist(left_landmarks[4], right_landmarks[4])

        if d_index < d_ref * 0.35 and d_thumb < d_ref * 0.35:
            return True
        return False

    def count_extended_fingers(self, landmarks):
        """返回 0-5：伸直的手指总数（拇指 + 食指 + 中指 + 无名指 + 小指）。"""
        if not landmarks or len(landmarks) < 21:
            return 0
        thumb_ext = self._dist(landmarks[4], landmarks[17]) > \
                    self._dist(landmarks[2], landmarks[17])
        index_ext = self._is_finger_extended(landmarks, 8, 5)
        middle_ext = self._is_finger_extended(landmarks, 12, 9)
        ring_ext = self._is_finger_extended(landmarks, 16, 13)
        pinky_ext = self._is_finger_extended(landmarks, 20, 17)
        return sum([thumb_ext, index_ext, middle_ext, ring_ext, pinky_ext])

    def finger_direction(self, landmarks):
        """根据食指尖相对手腕的方向，返回 ↑/↓/←/→/· （5 态）。
        - 输入 None 或非法关键点 → '·'（中心/无方向）
        - 判定阈值：归一化坐标 0.10（任一方向超过阈值即生效）
        """
        if not landmarks or len(landmarks) < 9:
            return "·"
        wrist = landmarks[0]
        tip = landmarks[8]
        dx = tip.x - wrist.x
        dy = tip.y - wrist.y  # 图像坐标 y 朝下：dy<0 才是"上"
        thr = 0.10
        # 主轴方向判定
        if abs(dy) >= abs(dx):
            return "↑" if dy < -thr else ("↓" if dy > thr else "·")
        else:
            return "←" if dx < -thr else ("→" if dx > thr else "·")
