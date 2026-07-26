# sequence_tracker.py
# 动态手语 / 轨迹追踪器（Phase B）
#
# 设计目标：在不引入 LSTM/3D-CNN 的前提下，用「手掌中心滑动时间窗口」
# 实现极低 CPU 占用的动态手势识别。支持左右手独立追踪。
#
# 依赖：仅标准库 math + collections.deque
#
# 识别类别（单手）：
#   Wave        挥手/再见（水平多次方向反转）
#   Swipe_Left / Swipe_Right / Swipe_Up / Swipe_Down   单向平移
#   Circle      画圈（累计转角接近 360° 且首尾靠拢）
#   None        无显著动态（或窗口未填满）

import math
from collections import deque


class SequenceTracker:
    def __init__(self, max_length=35):
        """
        :param max_length: 滑动窗口帧数 (30-45 帧适合约 30 FPS 摄像头)
                           —— 约 1.0~1.5 秒的动态过程。
        """
        self.max_length = max_length
        # 维护左右手的掌心轨迹队列 (Point: (x, y))，x/y 均为归一化坐标 (0~1)
        self.left_pts = deque(maxlen=max_length)
        self.right_pts = deque(maxlen=max_length)

    def update(self, left_landmarks, right_landmarks):
        """
        每帧调用：传入 21 点关键点，更新手心 (取 Landmark 9 - 掌心中心 MCP)。
        无对应手时清空该侧队列（避免残留轨迹影响判定）。
        """
        if left_landmarks:
            p9 = left_landmarks[9]
            self.left_pts.append((p9.x, p9.y))
        else:
            self.left_pts.clear()

        if right_landmarks:
            p9 = right_landmarks[9]
            self.right_pts.append((p9.x, p9.y))
        else:
            self.right_pts.clear()

    @staticmethod
    def _dist(p1, p2):
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _analyze_trajectory(self, pts):
        """
        对单手的点轨迹分析：挥手 / 划动 / 画圈 / None
        坐标均为归一化 (0~1)，故阈值无量纲、与分辨率无关。

        判定顺序：Circle 先于 Wave —— 因为多圈画圈也会在 X 轴产生
        >=2 次方向反转，若先判 Wave 会把它吞掉。

        画圈判定核心用「围合面积」而非「累计转角」：水平挥手每次反转处向量夹角
        近 180°，累计转角同样巨大（与画圈相当），但挥手路径几乎不围面积(≈0)，
        而圆圈围出约 π·r² 的显著面积。两者由此干净分开。
        """
        # 窗口未填满 70% 时不判（避免极短抖动误触发）
        if len(pts) < self.max_length * 0.7:
            return "None"

        pts_list = list(pts)
        start_pt = pts_list[0]
        end_pt = pts_list[-1]

        # 1. 基础物理量计算
        net_dist = self._dist(start_pt, end_pt)   # 净位移（首尾直线距离）
        total_path_len = 0.0                       # 总路程（轨迹折线长）
        x_reversals = 0                            # X 轴方向反转次数（挥手特征）
        last_dx = 0

        for i in range(1, len(pts_list)):
            dx = pts_list[i][0] - pts_list[i - 1][0]
            dy = pts_list[i][1] - pts_list[i - 1][1]
            step_len = math.sqrt(dx ** 2 + dy ** 2)
            total_path_len += step_len

            # 统计 X 轴方向反转（过滤微小抖动，避免噪声造成误计数）
            if abs(dx) > 0.01:
                if last_dx != 0 and (dx * last_dx < 0):
                    x_reversals += 1
                last_dx = dx

        # 2. 画圈 (Circle) 优先：轨迹闭合(首尾靠近) 且 围出显著面积
        #    shoelace 多边形面积；圆圈 ≈ π·r²，水平挥手路径自重叠 ≈ 0
        area = 0.0
        n = len(pts_list)
        for i in range(n):
            x1, y1 = pts_list[i]
            x2, y2 = pts_list[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        area = abs(area) * 0.5
        if area > 0.004 and net_dist < 0.15:
            return "Circle"

        # 3. 挥手 (Wave)：水平方向反转 >= 2 次，且总路程足够大
        #    （画圈已在上一步被拦下；挥手围合面积≈0，不会误入 Circle）
        if x_reversals >= 2 and total_path_len > 0.3:
            return "Wave"

        # 4. 划动 (Swipe)：路程与净位移接近（近直线），且位移显著
        if total_path_len > 0.25 and (net_dist / total_path_len) > 0.75:
            dx_net = end_pt[0] - start_pt[0]
            dy_net = end_pt[1] - start_pt[1]

            if abs(dx_net) > abs(dy_net):
                return "Swipe_Right" if dx_net > 0 else "Swipe_Left"
            else:
                return "Swipe_Down" if dy_net > 0 else "Swipe_Up"

        return "None"

    def get_dynamic_gestures(self):
        """
        获取当前左右手的动态手语结果。
        """
        left_dyn = self._analyze_trajectory(self.left_pts)
        right_dyn = self._analyze_trajectory(self.right_pts)

        return {
            "left_dynamic": left_dyn,
            "right_dynamic": right_dyn
        }
