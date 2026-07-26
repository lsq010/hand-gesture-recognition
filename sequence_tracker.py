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

    @staticmethod
    def _polygon_area(pts):
        """shoelace 公式计算轨迹围合面积（绝对值）。"""
        n = len(pts)
        if n < 3:
            return 0.0
        s = 0.0
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            s += x1 * y2 - x2 * y1
        return abs(s) * 0.5

    def _analyze_trajectory(self, pts):
        """单手轨迹分析：画圈 / 挥手 / 划动 / None。

        核心改进：用「绕质心的累计有符号转角」区分画圈与挥手。
          - 画圈：手掌持续同方向绕圈，累计转角接近 ±360°（一圈以上），
                  轨迹明显围成一个圈（等周比 circularity 高）。
          - 挥手：手掌左右来回摆动，虽然 X 轴方向会有多次反转，
                  但整体几乎不旋转（累计转角≈0），轨迹不围面积。
        两者单靠"面积"无法干净分离（挥手带弧线也会围一点面积、
        画圈首尾若不靠拢面积条件也常不满足）；改用「转角+等周比」
        双特征后，几乎不再相互误判。

        判定顺序：Circle 先于 Wave，因为画圈时 X 轴也会有 ≥2 次方向
        反转，若先判 Wave 会把圈吞掉；而 Circle 分支要求转角大，
        挥手转角≈0 不会误入，故安全。
        """
        # 窗口未填满 70% 时不判（避免极短抖动误触发）
        if len(pts) < self.max_length * 0.7:
            return "None"

        pts_list = list(pts)
        n = len(pts_list)
        start_pt = pts_list[0]
        end_pt = pts_list[-1]

        # 1. 基础物理量
        net_dist = self._dist(start_pt, end_pt)   # 首尾直线距离
        total_path_len = 0.0                       # 总路程
        x_reversals = 0                            # X 轴方向反转次数
        last_dx = 0

        # 绕质心累计有符号转角（画圈≈±2π，挥手≈0）
        cx = sum(p[0] for p in pts_list) / n
        cy = sum(p[1] for p in pts_list) / n
        prev_angle = None
        total_turn = 0.0

        for i in range(1, n):
            dx = pts_list[i][0] - pts_list[i - 1][0]
            dy = pts_list[i][1] - pts_list[i - 1][1]
            total_path_len += math.sqrt(dx * dx + dy * dy)

            # X 轴方向反转（过滤微小抖动）
            if abs(dx) > 0.01:
                if last_dx != 0 and (dx * last_dx < 0):
                    x_reversals += 1
                last_dx = dx

            # 有符号转角（绕质心，归一化到 [-π, π]）
            ang = math.atan2(pts_list[i][1] - cy, pts_list[i][0] - cx)
            if prev_angle is not None:
                d = ang - prev_angle
                while d > math.pi:
                    d -= 2 * math.pi
                while d < -math.pi:
                    d += 2 * math.pi
                total_turn += d
            prev_angle = ang

        # 等周比：圆≈1，直线/来回≈0（与圈大小无关，比绝对面积稳定）
        area = self._polygon_area(pts_list)
        perimeter = total_path_len if total_path_len > 0 else 1e-6
        circularity = (4.0 * math.pi * area) / (perimeter * perimeter)

        # 2. 画圈（优先）：累计转角接近一圈以上，且轨迹确实围成圈
        if abs(total_turn) > 1.1 * math.pi and circularity > 0.2:
            return "Circle"

        # 3. 挥手：水平来回反转≥2 次，且总路程够大。
        #    （画圈已被上一步 circularity>0.2 拦下；挥手来回 circularity≈0，
        #      不会误入 Circle，故无需再用转角去排除。）
        if x_reversals >= 2 and total_path_len > 0.3:
            return "Wave"

        # 4. 划动：近直线平移
        if total_path_len > 0.25 and (net_dist / perimeter) > 0.75:
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
