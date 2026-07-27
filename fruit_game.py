# -*- coding: utf-8 -*-
"""fruit_game.py - 小游戏平台（游戏列表 + 切水果游戏）

架构：
  - GameInfo / GAME_REGISTRY  → 游戏注册表（方便以后扩展新游戏）
  - FruitSliceController      → 游戏逻辑控制器（物理、碰撞、计分），在摄像头帧上用 cv2 绘制
  - GameHubWidget             → 右侧 Tab 里的 UI（游戏列表 + 介绍 + HUD + 控制按钮）

切水果玩法：
  - 食指指尖（MediaPipe landmark 8）在摄像头前划过水果即可切开
  - 60 秒倒计时，3 条命，切到炸弹扣命
  - 水果从底部弹射飞出，受重力下落
"""

import math
import random
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFrame, QButtonGroup, QTextBrowser,
)
from PySide6.QtCore import Qt, QObject, Signal


# ═══════════════════════════════════════════════════════════════════════
#  游戏注册表
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class GameInfo:
    """单个游戏的元信息。"""
    id: str
    name: str
    icon: str
    description: str          # 一句话介绍
    instructions: str         # 详细玩法说明（换行分隔）


GAME_REGISTRY: list[GameInfo] = [
    GameInfo(
        id="fruit_slice",
        name="切水果",
        icon="🍉",
        description="用食指在摄像头前划过水果即可切开，避开炸弹，争取最高分！右侧可选择 简单 / 普通 / 困难 / 地狱 难度。",
        instructions=(
            "1. 点击「开始游戏」后自动打开摄像头（如未打开）\n"
            "2. 在右侧选择难度：简单 / 普通 / 困难 / 地狱（炸弹越来越频繁）\n"
            "3. 伸出食指，在摄像头前移动划过水果\n"
            "4. 切到水果 +1 分，切到炸弹 -1 条命\n"
            "5. 生命用完或倒计时结束即游戏结束\n"
            "6. 难度越高，炸弹出现越早、越频繁，水果更快更多\n"
            "7. 可随时暂停 / 结束游戏"
        ),
    ),
    # ── 以后在这里添加新游戏 ──
    # GameInfo(id="xxx", name="xxx", icon="🎮", description="...", instructions="..."),
]


# ═══════════════════════════════════════════════════════════════════════
#  切水果游戏控制器
# ═══════════════════════════════════════════════════════════════════════

def _alpha_blend(frame, overlay, alpha, x=0, y=0):
    """将 overlay 以 alpha 叠加到 frame 的 (x,y) 位置。"""
    h, w = overlay.shape[:2]
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)
    if x1 >= x2 or y1 >= y2:
        return
    ox1, oy1 = x1 - x, y1 - y
    ox2, oy2 = ox1 + (x2 - x1), oy1 + (y2 - y1)
    roi = frame[y1:y2, x1:x2]
    ov = overlay[oy1:oy2, ox1:ox2]
    if overlay.shape[2] == 4:
        a = ov[:, :, 3:4].astype(np.float32) / 255.0 * alpha
        rgb = ov[:, :, :3].astype(np.float32)
        roi_f = roi.astype(np.float32)
        res = (a * rgb + (1 - a) * roi_f).astype(np.uint8)
    else:
        res = cv2.addWeighted(ov, alpha, roi, 1 - alpha, 0)
    frame[y1:y2, x1:x2] = res



def _radial_gradient_alpha(r, center_color, edge_color):
    """生成径向渐变圆形。"""
    d = r * 2 + 5
    canvas = np.zeros((d, d, 4), dtype=np.uint8)
    c = d // 2
    for y in range(d):
        for x in range(d):
            dist = math.hypot(x - c, y - c)
            if dist > r:
                continue
            t = dist / r
            t = min(1.0, t)
            b = int(center_color[0] * (1 - t) + edge_color[0] * t)
            g = int(center_color[1] * (1 - t) + edge_color[1] * t)
            rr = int(center_color[2] * (1 - t) + edge_color[2] * t)
            a = int(255 * (1 - t * 0.35))  # 边缘稍微透明
            canvas[y, x] = (b, g, rr, a)
    return canvas


#  ═══════════════════════════════════════════════════════════════════════
#  水果绘制：每种水果单独一个 draw_xxx 函数，用 cv2 画出拟真效果
#  ═══════════════════════════════════════════════════════════════════════


def _draw_shadow(frame, cx, cy, r):
    """水果下方半透明阴影。"""
    shadow = np.zeros((r + 6, r * 2 + 10, 4), dtype=np.uint8)
    sx = r + 5
    sy = r // 2
    cv2.ellipse(shadow, (sx, sy), (r, r // 3), 0, 0, 360, (20, 20, 20, 120), -1, cv2.LINE_AA)
    # 阴影放在水果正下方（不重叠）
    _alpha_blend(frame, shadow, 1.0, cx - sx, cy + r + 5 - sy)


def _draw_watermelon(frame, cx, cy, r, rot):
    """西瓜：深绿条纹外皮 + 红瓤 + 黑籽。"""
    _draw_shadow(frame, cx, cy, r)
    # 外皮（深色）
    cv2.circle(frame, (cx, cy), r, (34, 80, 34), -1, cv2.LINE_AA)
    # 条纹（浅绿弧线）
    for i in range(-2, 3):
        cv2.ellipse(frame, (cx, cy), (r - 3, r - 3), rot + i * 25, 0, 180,
                    (80, 154, 80), 3, cv2.LINE_AA)
    # 果肉
    cv2.circle(frame, (cx, cy), r - 5, (55, 55, 220), -1, cv2.LINE_AA)
    # 籽
    for angle in [30, 90, 150, 210, 270, 330]:
        sx = int(cx + (r - 14) * math.cos(math.radians(angle + rot)))
        sy = int(cy + (r - 14) * math.sin(math.radians(angle + rot)) * 0.6)
        cv2.ellipse(frame, (sx, sy), (3, 5), angle + rot, 0, 360, (10, 10, 10), -1, cv2.LINE_AA)
    # 高光
    cv2.circle(frame, (cx - r // 4, cy - r // 4), r // 5, (90, 90, 255), -1, cv2.LINE_AA)


def _draw_orange(frame, cx, cy, r, rot):
    """橙子：橙色球 + 表皮纹理 + 小绿叶。"""
    _draw_shadow(frame, cx, cy, r)
    # 径向渐变球
    grad = _radial_gradient_alpha(r, (55, 170, 255), (20, 100, 200))
    _alpha_blend(frame, grad, 1.0, cx - r, cy - r)
    # 表皮凹点纹理
    for i in range(8):
        a = math.radians(i * 45 + rot)
        px = int(cx + (r - 6) * math.cos(a))
        py = int(cy + (r - 6) * math.sin(a))
        cv2.circle(frame, (px, py), 2, (40, 140, 220), -1, cv2.LINE_AA)
    # 茎 + 绿叶
    cv2.line(frame, (cx, cy - r), (cx - 2, cy - r - 10), (40, 80, 40), 2, cv2.LINE_AA)
    leaf = np.array([
        [cx, cy - r - 6],
        [cx + 16, cy - r - 14],
        [cx + 6, cy - r - 2],
    ], np.int32)
    cv2.fillPoly(frame, [leaf], (40, 150, 40), cv2.LINE_AA)
    # 高光
    cv2.circle(frame, (cx - r // 4, cy - r // 4), r // 5, (110, 200, 255), -1, cv2.LINE_AA)


def _draw_banana(frame, cx, cy, r, rot):
    """香蕉：黄色弯月形。"""
    _draw_shadow(frame, cx, cy, r)
    # 用两条弧线围成香蕉
    pts = []
    for t in range(0, 181, 6):
        a = math.radians(t + rot)
        rr = r - 4 + int(8 * math.sin(math.radians(t * 2)))
        px = int(cx + rr * math.cos(a))
        py = int(cy + rr * math.sin(a) * 0.55)
        pts.append((px, py))
    # 外轮廓
    pts2 = []
    for t in range(180, -1, -6):
        a = math.radians(t + rot)
        rr = r - 16 + int(8 * math.sin(math.radians(t * 2)))
        px = int(cx + rr * math.cos(a))
        py = int(cy + rr * math.sin(a) * 0.55)
        pts2.append((px, py))
    pts.extend(pts2)
    pts = np.array(pts, np.int32).reshape((-1, 1, 2))
    cv2.fillPoly(frame, [pts], (0, 230, 255), cv2.LINE_AA)
    # 深黄边
    cv2.polylines(frame, [pts], True, (0, 180, 200), 2, cv2.LINE_AA)
    # 棕色头尾
    tip1 = pts[0][0]
    tip2 = pts[len(pts) // 2][0]
    cv2.circle(frame, tuple(tip1), 5, (20, 60, 120), -1, cv2.LINE_AA)
    cv2.circle(frame, tuple(tip2), 5, (20, 60, 120), -1, cv2.LINE_AA)


def _draw_grapes(frame, cx, cy, r, rot):
    """葡萄：一串紫色小球。"""
    _draw_shadow(frame, cx, cy, r)
    base = (80, 30, 120)
    offsets = [
        (0, -r // 2), (r // 2, -r // 4), (-r // 2, -r // 4),
        (0, r // 4), (r // 3, r // 2), (-r // 3, r // 2),
        (0, r),
    ]
    for i, (ox, oy) in enumerate(offsets):
        gr = r // 2 - 1
        px, py = cx + ox, cy + oy
        # 单个葡萄球渐变
        grad = _radial_gradient_alpha(gr, (130, 60, 180), (50, 20, 90))
        _alpha_blend(frame, grad, 1.0, px - gr, py - gr)
        cv2.circle(frame, (px, py), gr, (110, 50, 150), 1, cv2.LINE_AA)
        # 高光
        cv2.circle(frame, (px - gr // 3, py - gr // 3), gr // 4, (160, 90, 210), -1, cv2.LINE_AA)
    # 茎
    cv2.line(frame, (cx, cy - r), (cx + 2, cy - r - 10), (60, 100, 60), 2, cv2.LINE_AA)


def _draw_apple(frame, cx, cy, r, rot):
    """青苹果：苹果轮廓 + 茎 + 叶。"""
    _draw_shadow(frame, cx, cy, r)
    # 苹果身体用椭圆+顶部内凹组合
    body = np.zeros((r * 2 + 8, r * 2 + 8, 4), dtype=np.uint8)
    bc = r + 4
    # 主体椭圆
    cv2.ellipse(body, (bc, bc + 2), (r - 4, r - 2), 0, 0, 360, (50, 205, 50, 255), -1, cv2.LINE_AA)
    # 顶部内凹
    cv2.ellipse(body, (bc, bc - r // 2 + 4), (r // 2, r // 4), 0, 0, 360, (40, 160, 40, 255), -1, cv2.LINE_AA)
    _alpha_blend(frame, body, 1.0, cx - bc, cy - bc)
    # 茎
    cv2.line(frame, (cx, cy - r + 4), (cx - 1, cy - r - 10), (50, 90, 50), 2, cv2.LINE_AA)
    # 叶
    leaf = np.array([
        [cx, cy - r - 6],
        [cx + 18, cy - r - 12],
        [cx + 8, cy - r - 2],
    ], np.int32)
    cv2.fillPoly(frame, [leaf], (50, 180, 50), cv2.LINE_AA)
    # 高光
    cv2.circle(frame, (cx - r // 4, cy - r // 4), r // 5, (100, 235, 100), -1, cv2.LINE_AA)


def _draw_dragonfruit(frame, cx, cy, r, rot):
    """火龙果：玫红椭圆 + 绿色鳞片。"""
    _draw_shadow(frame, cx, cy, r)
    # 椭圆身体
    cv2.ellipse(frame, (cx, cy), (r, int(r * 0.85)), rot, 0, 360, (130, 60, 220), -1, cv2.LINE_AA)
    # 绿色鳞片
    for i in range(6):
        a = math.radians(i * 60 + rot)
        sx = int(cx + (r - 6) * math.cos(a))
        sy = int(cy + (r - 6) * math.sin(a) * 0.85)
        scale = [(sx, sy), (sx + 8, sy - 6), (sx + 2, sy + 8)]
        scale = np.array(scale, np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(frame, [scale], (40, 150, 40), cv2.LINE_AA)
    # 白色高光
    cv2.circle(frame, (cx - r // 4, cy - r // 4), r // 5, (180, 120, 255), -1, cv2.LINE_AA)


def _draw_coconut(frame, cx, cy, r, rot):
    """椰子：棕色毛茸茸圆 + 三个眼。"""
    _draw_shadow(frame, cx, cy, r)
    # 主体
    cv2.circle(frame, (cx, cy), r, (40, 80, 120), -1, cv2.LINE_AA)
    # 三个眼
    for i in range(3):
        a = math.radians(i * 120 + rot + 30)
        ex = int(cx + (r // 2) * math.cos(a))
        ey = int(cy + (r // 2) * math.sin(a))
        cv2.ellipse(frame, (ex, ey), (5, 7), a * 180 / math.pi, 0, 360, (20, 40, 70), -1, cv2.LINE_AA)
    # 毛刺纹理
    for _ in range(12):
        a = math.radians(random.uniform(0, 360))
        px = int(cx + (r - 2) * math.cos(a))
        py = int(cy + (r - 2) * math.sin(a))
        cv2.line(frame, (px, py), (px - 2, py - 2), (55, 100, 140), 1, cv2.LINE_AA)
    # 高光
    cv2.circle(frame, (cx - r // 4, cy - r // 4), r // 5, (75, 120, 160), -1, cv2.LINE_AA)


# 水果粒子的代表颜色（按 kind 取）
_FRUIT_PARTICLE_COLORS = {
    "watermelon": (55, 55, 220),
    "orange": (55, 170, 255),
    "banana": (0, 230, 255),
    "grapes": (80, 30, 120),
    "apple": (50, 205, 50),
    "dragonfruit": (130, 60, 220),
    "coconut": (40, 80, 120),
}


def _get_fruit_color(kind):
    return _FRUIT_PARTICLE_COLORS.get(kind, (100, 100, 100))


FRUIT_TYPES = [
    ("watermelon", _draw_watermelon, 35, "🍉"),
    ("orange",     _draw_orange,     30, "🍊"),
    ("banana",     _draw_banana,     32, "🍌"),
    ("grapes",     _draw_grapes,     30, "🍇"),
    ("apple",      _draw_apple,      30, "🍏"),
    ("dragonfruit", _draw_dragonfruit, 32, "🐉"),
    ("coconut",    _draw_coconut,    30, "🥥"),
]

GRAVITY = 620.0           # px/s²
GAME_DURATION = 60.0      # 秒（默认，实际由难度覆盖）
MAX_LIVES = 3
TRAIL_MAXLEN = 12         # 指尖轨迹保留帧数


# ── 难度配置 ──────────────────────────────────────────────
@dataclass
class DifficultyConfig:
    """单档难度参数。难度越高：炸弹出现越早、越频繁，水果更快更多。"""
    id: str
    name: str
    icon: str
    description: str
    lives: int                      # 初始生命
    duration: float                 # 单局时长（秒）
    bomb_threshold: int             # 达到该分数后才开始出现炸弹
    bomb_prob: float                # 满足阈值后，每次生成炸弹的概率
    spawn_interval_base: float      # 基础生成间隔（秒）
    spawn_interval_min: float       # 生成间隔下限（秒）
    batch_min: int                  # 每次生成水果数量下限
    batch_max: int                  # 每次生成水果数量上限
    launch_vy_min: float            # 水果出射速度（负=向上）下限
    launch_vy_max: float            # 水果出射速度上限


DIFFICULTY_LEVELS: list[DifficultyConfig] = [
    DifficultyConfig(
        id="easy", name="简单", icon="🌱",
        description="新手友好：炸弹很少出现，节奏舒缓。",
        lives=5, duration=70, bomb_threshold=8, bomb_prob=0.08,
        spawn_interval_base=1.10, spawn_interval_min=0.70,
        batch_min=1, batch_max=2, launch_vy_min=-560, launch_vy_max=-420,
    ),
    DifficultyConfig(
        id="normal", name="普通", icon="⚔️",
        description="标准节奏：适度出现炸弹，适合日常娱乐。",
        lives=3, duration=60, bomb_threshold=5, bomb_prob=0.16,
        spawn_interval_base=1.00, spawn_interval_min=0.60,
        batch_min=1, batch_max=3, launch_vy_min=-680, launch_vy_max=-500,
    ),
    DifficultyConfig(
        id="hard", name="困难", icon="🔥",
        description="节奏更快：炸弹频繁，水果数量更多。",
        lives=3, duration=60, bomb_threshold=3, bomb_prob=0.30,
        spawn_interval_base=0.85, spawn_interval_min=0.45,
        batch_min=2, batch_max=3, launch_vy_min=-780, launch_vy_max=-580,
    ),
    DifficultyConfig(
        id="hell", name="地狱", icon="💀",
        description="极限挑战：开局即大量炸弹，稍有不慎就 Game Over！",
        lives=2, duration=60, bomb_threshold=0, bomb_prob=0.48,
        spawn_interval_base=0.70, spawn_interval_min=0.35,
        batch_min=2, batch_max=4, launch_vy_min=-880, launch_vy_max=-650,
    ),
]
DEFAULT_DIFFICULTY = "normal"


class FruitSliceController(QObject):
    """切水果游戏控制器。

    由 main.py 的 _tick 每帧调用 update_and_draw(frame, parsed, dt)，
    在摄像头帧上绘制水果、轨迹、粒子效果。
    通过 Qt Signal 向 GameHubWidget 推送 HUD 更新。
    """

    # ── 信号：通知 UI 更新 ──
    score_changed = Signal(int)
    lives_changed = Signal(int)
    time_changed = Signal(int)          # 剩余秒数
    game_over = Signal(str, int)        # (reason, final_score)
    state_changed = Signal(str)         # "idle" / "running" / "paused" / "over"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fruits: list[dict] = []
        self.particles: list[dict] = []
        self.trail: deque = deque(maxlen=TRAIL_MAXLEN)
        self.score = 0
        self.lives = MAX_LIVES
        self.time_left = GAME_DURATION
        self.is_running = False
        self.is_paused = False
        self._spawn_timer = 0.0
        self._state = "idle"
        self.difficulty = next(d for d in DIFFICULTY_LEVELS if d.id == DEFAULT_DIFFICULTY)

    # ── 游戏生命周期 ──────────────────────────────────────────

    def start(self, difficulty=None):
        """开始 / 重新开始一局。可传入 DifficultyConfig 设定难度。"""
        if difficulty is not None:
            self.difficulty = difficulty
        self.fruits.clear()
        self.particles.clear()
        self.trail.clear()
        self.score = 0
        self.lives = self.difficulty.lives
        self.time_left = self.difficulty.duration
        self.is_running = True
        self.is_paused = False
        self._spawn_timer = 0.0
        self._set_state("running")
        self.score_changed.emit(0)
        self.lives_changed.emit(self.difficulty.lives)
        self.time_changed.emit(int(self.difficulty.duration))

    def pause(self):
        """暂停 / 继续。"""
        if not self.is_running:
            return
        self.is_paused = not self.is_paused
        self._set_state("paused" if self.is_paused else "running")

    def end(self):
        """手动结束游戏。"""
        self.is_running = False
        self.is_paused = False
        self.fruits.clear()
        self.particles.clear()
        self.trail.clear()
        self._set_state("idle")

    # ── 每帧更新 + 绘制 ──────────────────────────────────────

    def update_and_draw(self, frame, parsed, dt):
        """由 _tick 调用：更新物理 + 在 frame 上绘制游戏画面。

        Args:
            frame:  OpenCV BGR 帧（已被 vision_engine 翻转过）
            parsed: vision_engine 返回的解析结果（含 left/right_landmarks）
            dt:     帧间隔（秒）
        """
        if not self.is_running:
            return

        h, w = frame.shape[:2]

        # 暂停状态：冻结画面，只画水果和暂停提示
        if self.is_paused:
            self._draw_fruits(frame)
            self._draw_trail(frame)
            self._draw_paused_overlay(frame, w, h)
            return

        # ── 倒计时 ──
        self.time_left -= dt
        if self.time_left <= 0:
            self.time_left = 0
            self.time_changed.emit(0)
            self.is_running = False
            self._draw_fruits(frame)
            self._set_state("over")
            self.game_over.emit("time_up", self.score)
            return
        self.time_changed.emit(int(self.time_left))

        # ── 生成水果（间隔随分数与难度收紧）──
        self._spawn_timer += dt
        spawn_interval = max(
            self.difficulty.spawn_interval_min,
            self.difficulty.spawn_interval_base - self.score * 0.012,
        )
        if self._spawn_timer >= spawn_interval:
            self._spawn_timer = 0.0
            self._spawn_batch(w, h)

        # ── 水果物理 ──
        survivors = []
        for f in self.fruits:
            f["vy"] += GRAVITY * dt
            f["x"] += f["vx"] * dt
            f["y"] += f["vy"] * dt
            f["rotation"] += 80 * dt
            if f["y"] > h + f["radius"] + 30:
                continue  # 掉出底部，移除
            survivors.append(f)
        self.fruits = survivors

        # ── 粒子物理 ──
        psurv = []
        for p in self.particles:
            p["vy"] += 350 * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["life"] -= dt
            if p["life"] > 0:
                psurv.append(p)
        self.particles = psurv

        # ── 指尖轨迹 + 碰撞检测 ──
        finger_tip = self._get_finger_tip(parsed, w, h)
        if finger_tip is not None:
            self.trail.append(finger_tip)
            # 检查最新轨迹段是否切到水果
            if len(self.trail) >= 2:
                prev = self.trail[-2]
                curr = self.trail[-1]
                for f in self.fruits[:]:
                    dist = _point_to_segment_dist(
                        f["x"], f["y"],
                        prev[0], prev[1],
                        curr[0], curr[1],
                    )
                    if dist < f["radius"]:
                        if f.get("is_bomb"):
                            self.lives -= 1
                            self.lives_changed.emit(self.lives)
                            self._spawn_particles(f["x"], f["y"], (30, 30, 30), 18)
                            self.fruits.remove(f)
                            if self.lives <= 0:
                                self.is_running = False
                                self._set_state("over")
                                self.game_over.emit("dead", self.score)
                                return
                        else:
                            self.score += 1
                            self.score_changed.emit(self.score)
                            self._spawn_particles(f["x"], f["y"], f["color"], 14)
                            self.fruits.remove(f)
        else:
            # 没检测到手 → 清空轨迹（避免断线后残留长线）
            self.trail.clear()

        # ── 绘制 ──
        self._draw_fruits(frame)
        self._draw_trail(frame)
        self._draw_particles(frame)

    # ── 内部方法 ──────────────────────────────────────────────

    def _set_state(self, state):
        self._state = state
        self.state_changed.emit(state)

    def _get_finger_tip(self, parsed, w, h):
        """从 parsed 中取食指指尖坐标（优先右手，其次左手）。
        返回 (px, py) 或 None。
        """
        for key in ("right_landmarks", "left_landmarks"):
            lms = parsed.get(key)
            if lms is not None and len(lms) > 8:
                tip = lms[8]  # landmark 8 = 食指指尖
                return (int(tip.x * w), int(tip.y * h))
        return None

    def _spawn_batch(self, w, h):
        d = self.difficulty
        count = random.randint(d.batch_min, d.batch_max)
        for _ in range(count):
            if self.score >= d.bomb_threshold and random.random() < d.bomb_prob:
                self._spawn_bomb(w, h)
            else:
                self._spawn_fruit(w, h)

    def _spawn_fruit(self, w, h):
        kind, draw_fn, radius, emoji = random.choice(FRUIT_TYPES)
        self.fruits.append({
            "x": random.uniform(60, w - 60),
            "y": h + radius,
            "vx": random.uniform(-100, 100),
            "vy": random.uniform(self.difficulty.launch_vy_min, self.difficulty.launch_vy_max),
            "radius": radius,
            "kind": kind,
            "draw": draw_fn,
            "emoji": emoji,
            "color": _get_fruit_color(kind),
            "rotation": 0.0,
            "is_bomb": False,
        })

    def _spawn_bomb(self, w, h):
        self.fruits.append({
            "x": random.uniform(60, w - 60),
            "y": h + 34,
            "vx": random.uniform(-80, 80),
            "vy": random.uniform(self.difficulty.launch_vy_min, self.difficulty.launch_vy_max),
            "radius": 34,
            "kind": "bomb",
            "rotation": 0.0,
            "is_bomb": True,
            "fuse_spark": 0,
        })

    def _spawn_particles(self, x, y, color, count):
        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(120, 320)
            self.particles.append({
                "x": x, "y": y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed - 100,
                "life": 0.45,
                "max_life": 0.45,
                "color": color,
                "size": random.randint(3, 8),
            })

    # ── 绘制方法（直接在 OpenCV 帧上画）──

    def _draw_fruits(self, frame):
        for f in self.fruits:
            cx, cy = int(f["x"]), int(f["y"])
            r = f["radius"]
            rot = f.get("rotation", 0.0)
            if f.get("is_bomb"):
                self._draw_bomb(frame, cx, cy, r, rot)
            else:
                draw_fn = f.get("draw")
                if draw_fn is not None:
                    draw_fn(frame, cx, cy, r, rot)

    def _draw_bomb(self, frame, cx, cy, r, rot):
        """炸弹：金属黑球 + 红色骷髅交叉骨 + 燃烧的引信 + 闪烁火花。"""
        _draw_shadow(frame, cx, cy, r)
        # 主体径向渐变（亮灰到黑）
        grad = _radial_gradient_alpha(r, (90, 90, 110), (10, 10, 10))
        _alpha_blend(frame, grad, 1.0, cx - r, cy - r)
        # 外红圈
        cv2.circle(frame, (cx, cy), r, (20, 20, 220), 2, cv2.LINE_AA)
        # 红色骷髅交叉骨（X）
        cv2.line(frame, (cx - r // 2, cy - r // 2), (cx + r // 2, cy + r // 2),
                 (20, 20, 230), 3, cv2.LINE_AA)
        cv2.line(frame, (cx + r // 2, cy - r // 2), (cx - r // 2, cy + r // 2),
                 (20, 20, 230), 3, cv2.LINE_AA)
        # 引信：弯曲棕线 + 火花
        fuse_x = cx + int(r * 0.6)
        fuse_y = cy - r - 8
        pts = np.array([
            [cx, cy - r],
            [cx + r // 2, cy - r - 5],
            [fuse_x, fuse_y],
        ], np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [pts], False, (40, 60, 100), 2, cv2.LINE_AA)
        # 闪烁火花
        spark = (0, 0, 255) if int(time.time() * 8) % 2 == 0 else (50, 120, 255)
        cv2.circle(frame, (fuse_x, fuse_y), 5, spark, -1, cv2.LINE_AA)
        cv2.circle(frame, (fuse_x, fuse_y), 8, (30, 100, 255), 1, cv2.LINE_AA)
        # 顶部金属环
        cv2.ellipse(frame, (cx, cy - r), (r // 4, r // 6), 0, 0, 360, (100, 100, 120), 2, cv2.LINE_AA)

    def _draw_trail(self, frame):
        pts = list(self.trail)
        if not pts:
            return
        if len(pts) < 2:
            cv2.circle(frame, pts[0], 6, (255, 255, 255), -1, cv2.LINE_AA)
            return

        # 1. 外发光层：用较粗、半透明青色描边
        for i in range(1, len(pts)):
            alpha = i / len(pts)
            thick = max(4, int(4 + 12 * alpha))
            b = int(220 * alpha + 35)
            g = int(255 * alpha)
            r = int(255 * alpha)
            cv2.line(frame, pts[i - 1], pts[i], (b, g, r), thick, cv2.LINE_AA)

        # 2. 核心亮线：白 → 青
        for i in range(1, len(pts)):
            alpha = i / len(pts)
            thick = max(2, int(2 + 3 * alpha))
            b = int(160 * alpha + 95)
            g = int(255 * alpha)
            r = int(255 * alpha)
            cv2.line(frame, pts[i - 1], pts[i], (b, g, r), thick, cv2.LINE_AA)

        # 3. 指尖光晕
        last = pts[-1]
        cv2.circle(frame, last, 14, (120, 220, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, last, 10, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, last, 16, (80, 180, 255), 2, cv2.LINE_AA)

    def _draw_particles(self, frame):
        for p in self.particles:
            alpha = p["life"] / p["max_life"]
            r = max(1, int(p["size"] * alpha))
            color = tuple(int(c * alpha) for c in p["color"])
            cv2.circle(frame, (int(p["x"]), int(p["y"])), r, color, -1, cv2.LINE_AA)

    def _draw_paused_overlay(self, frame, w, h):
        """暂停时画面上显示 PAUSED。"""
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        cv2.putText(frame, "PAUSED", (w // 2 - 80, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 0), 4, cv2.LINE_AA)


# ═══════════════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════════════

def _point_to_segment_dist(px, py, x1, y1, x2, y2):
    """点 (px,py) 到线段 (x1,y1)→(x2,y2) 的距离。"""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x, proj_y = x1 + t * dx, y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


# ═══════════════════════════════════════════════════════════════════════
#  游戏平台 UI Widget
# ═══════════════════════════════════════════════════════════════════════

# 深色主题样式
_STYLE = """
QListWidget {
    background-color: #1e2030;
    border: 1px solid #333;
    border-radius: 6px;
    font-size: 14px;
    padding: 4px;
}
QListWidget::item {
    padding: 8px 12px;
    border-radius: 4px;
}
QListWidget::item:selected {
    background-color: #4a9eff;
    color: white;
}
QListWidget::item:hover {
    background-color: #2a2d45;
}
QLabel#descTitle {
    font-size: 15px;
    font-weight: bold;
    color: #4a9eff;
}
QLabel#descBody {
    font-size: 13px;
    color: #ccc;
    line-height: 1.6;
}
QLabel#hudScore {
    font-size: 22px;
    font-weight: bold;
    color: #ffd700;
}
QLabel#hudLives {
    font-size: 22px;
    font-weight: bold;
    color: #ff5555;
}
QLabel#hudTime {
    font-size: 22px;
    font-weight: bold;
    color: #66ccff;
}
QPushButton#btnStart {
    background-color: #4CAF50; color: white; font-size: 15px;
    font-weight: bold; border-radius: 6px; padding: 8px 24px;
}
QPushButton#btnStart:hover { background-color: #5DBE5D; }
QPushButton#btnStart:pressed { background-color: #3D8B40; }
QPushButton#btnStart:disabled { background-color: #444; color: #888; }
QPushButton#btnPause {
    background-color: #FF9800; color: white; font-size: 15px;
    font-weight: bold; border-radius: 6px; padding: 8px 24px;
}
QPushButton#btnPause:hover { background-color: #FFA726; }
QPushButton#btnPause:pressed { background-color: #E68900; }
QPushButton#btnPause:disabled { background-color: #444; color: #888; }
QPushButton#btnEnd {
    background-color: #f44336; color: white; font-size: 15px;
    font-weight: bold; border-radius: 6px; padding: 8px 24px;
}
QPushButton#btnEnd:hover { background-color: #EF5350; }
QPushButton#btnEnd:pressed { background-color: #C62828; }
QPushButton#btnEnd:disabled { background-color: #444; color: #888; }
QPushButton#btnDiff {
    background-color: #2a2d45; color: #ccc; font-size: 13px;
    border: 1px solid #444; border-radius: 6px; padding: 6px 12px;
}
QPushButton#btnDiff:checked {
    background-color: #4a9eff; color: white; font-weight: bold;
    border: 1px solid #4a9eff;
}
QPushButton#btnDiff:hover { background-color: #353a5a; }
QPushButton#btnDiff:disabled {
    background-color: #1a1c2a; color: #555; border: 1px solid #333;
}
QFrame#hudFrame {
    background-color: #1a1c2a;
    border: 1px solid #333;
    border-radius: 8px;
}
"""


class GameHubWidget(QWidget):
    """小游戏平台 Widget：游戏列表 + 介绍 + HUD + 控制按钮。

    通过回调与主窗口通信：
      - on_start(game_id)  → 用户点「开始游戏」
      - on_pause()         → 用户点「暂停 / 继续」
      - on_end()           → 用户点「结束游戏」
    主窗口通过 update_hud_* 方法回推 HUD 数据。
    """

    # 回调属性（由 main.py 设置）
    on_start = None    # callable(game_id: str)
    on_pause = None    # callable()
    on_end = None      # callable()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_game_id = None
        self._selected_difficulty = DEFAULT_DIFFICULTY
        self._current_state = "idle"
        self._diff_buttons: dict = {}
        self._setup_ui()
        self.setStyleSheet(_STYLE)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(10)

        # ── 游戏列表 ──
        list_title = QLabel("🎮 游戏列表")
        list_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #ddd;")
        layout.addWidget(list_title)

        self.gameList = QListWidget()
        self.gameList.setFixedHeight(120)
        for gi in GAME_REGISTRY:
            item = QListWidgetItem(f"{gi.icon}  {gi.name}")
            item.setData(Qt.UserRole, gi.id)
            self.gameList.addItem(item)
        if self.gameList.count() > 0:
            self.gameList.setCurrentRow(0)
            self._selected_game_id = GAME_REGISTRY[0].id
        self.gameList.currentRowChanged.connect(self._on_game_selected)
        layout.addWidget(self.gameList)

        # ── 游戏介绍 ──
        desc_title = QLabel("📝 游戏介绍")
        desc_title.setObjectName("descTitle")
        layout.addWidget(desc_title)

        self.descLabel = QTextBrowser()
        self.descLabel.setObjectName("descBody")
        self.descLabel.setReadOnly(True)
        self.descLabel.setOpenExternalLinks(False)
        self.descLabel.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.descLabel.setMinimumHeight(100)
        self.descLabel.setMaximumHeight(260)
        self.descLabel.setStyleSheet(
            "QTextBrowser { background-color: #1a1c2a; border: 1px solid #333; "
            "border-radius: 6px; padding: 8px; font-size: 13px; color: #ccc; }\n"
            "QTextBrowser QScrollBar:vertical { background: #1a1c2a; width: 10px; "
            "border-radius: 5px; }\n"
            "QTextBrowser QScrollBar::handle:vertical { background: #4a9eff; "
            "border-radius: 5px; min-height: 30px; }\n"
            "QTextBrowser QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical "
            "{ height: 0px; }"
        )
        layout.addWidget(self.descLabel)
        self._update_description()

        # ── 难度选择 ──
        diff_title = QLabel("🔥 游戏难度（炸弹出现频率随难度递增）")
        diff_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #ddd;")
        layout.addWidget(diff_title)

        self.diffButtonGroup = QButtonGroup(self)
        diff_row = QHBoxLayout()
        diff_row.setSpacing(8)
        for d in DIFFICULTY_LEVELS:
            btn = QPushButton(f"{d.icon} {d.name}")
            btn.setObjectName("btnDiff")
            btn.setCheckable(True)
            btn.setToolTip(d.description)
            if d.id == DEFAULT_DIFFICULTY:
                btn.setChecked(True)
            btn.clicked.connect(
                lambda _checked=False, did=d.id: self._on_difficulty_selected(did)
            )
            self.diffButtonGroup.addButton(btn)
            self._diff_buttons[d.id] = btn
            diff_row.addWidget(btn)
        layout.addLayout(diff_row)

        # ── HUD（得分 / 生命 / 时间）──
        hud_frame = QFrame()
        hud_frame.setObjectName("hudFrame")
        hud_layout = QHBoxLayout(hud_frame)
        hud_layout.setContentsMargins(16, 10, 16, 10)
        hud_layout.setSpacing(8)

        hud_layout.addWidget(QLabel("得分"))
        self.hudScore = QLabel("0")
        self.hudScore.setObjectName("hudScore")
        hud_layout.addWidget(self.hudScore)

        hud_layout.addStretch(1)

        hud_layout.addWidget(QLabel("生命"))
        self.hudLives = QLabel(f"❤×{MAX_LIVES}")
        self.hudLives.setObjectName("hudLives")
        hud_layout.addWidget(self.hudLives)

        hud_layout.addStretch(1)

        hud_layout.addWidget(QLabel("时间"))
        self.hudTime = QLabel(f"{int(GAME_DURATION)}s")
        self.hudTime.setObjectName("hudTime")
        hud_layout.addWidget(self.hudTime)

        layout.addWidget(hud_frame)

        # ── 状态提示 ──
        self.statusLabel = QLabel("选择游戏后点击「开始游戏」")
        self.statusLabel.setStyleSheet("color: #888; font-size: 12px;")
        self.statusLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.statusLabel)

        # ── 控制按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.startBtn = QPushButton("🚀 开始游戏")
        self.startBtn.setObjectName("btnStart")
        self.startBtn.clicked.connect(self._on_start_clicked)

        self.pauseBtn = QPushButton("⏸ 暂停")
        self.pauseBtn.setObjectName("btnPause")
        self.pauseBtn.setEnabled(False)
        self.pauseBtn.clicked.connect(self._on_pause_clicked)

        self.endBtn = QPushButton("⏹ 结束游戏")
        self.endBtn.setObjectName("btnEnd")
        self.endBtn.setEnabled(False)
        self.endBtn.clicked.connect(self._on_end_clicked)

        btn_row.addWidget(self.startBtn)
        btn_row.addWidget(self.pauseBtn)
        btn_row.addWidget(self.endBtn)
        layout.addLayout(btn_row)

        # 用默认难度的生命/时长初始化 HUD 显示
        self._refresh_hud_defaults()

        layout.addStretch(1)

    # ── 内部事件 ──────────────────────────────────────────────

    def _on_game_selected(self, row):
        if 0 <= row < len(GAME_REGISTRY):
            self._selected_game_id = GAME_REGISTRY[row].id
            self._update_description()

    def _update_description(self):
        gid = self._selected_game_id
        gi = next((g for g in GAME_REGISTRY if g.id == gid), None)
        if gi is None:
            self.descLabel.setText("暂无游戏")
            return
        self.descLabel.setHtml(
            "<html><body style='color:#ccc;font-size:13px;'>"
            f"<b style='color:#4a9eff;font-size:15px;'>{gi.icon} {gi.name}</b><br><br>"
            f"{gi.description}<br><br>"
            f"<span style='color:#888;'>玩法说明：</span><br>"
            f"<span style='color:#aaa;white-space:pre-wrap;'>{gi.instructions}</span>"
            "</body></html>"
        )

    def _on_start_clicked(self):
        if self._selected_game_id and self.on_start:
            self.on_start(self._selected_game_id)

    def _on_pause_clicked(self):
        if self.on_pause:
            self.on_pause()

    def _on_end_clicked(self):
        if self.on_end:
            self.on_end()

    # ── 难度选择 ──────────────────────────────────────────────

    def _on_difficulty_selected(self, did):
        self._selected_difficulty = did
        cfg = self.get_difficulty()
        if self._current_state == "idle":
            self._refresh_hud_defaults()
            self.statusLabel.setText(f"难度：{cfg.name} — {cfg.description}")
            self.statusLabel.setStyleSheet("color: #888; font-size: 12px;")
        elif self._current_state == "over":
            # 已结束时也同步刷新 HUD 默认值，但保留结束提示
            self._refresh_hud_defaults()

    def get_difficulty(self):
        """返回当前选中的 DifficultyConfig（供 main.py 启动游戏时传入）。"""
        return next(d for d in DIFFICULTY_LEVELS if d.id == self._selected_difficulty)

    def _refresh_hud_defaults(self):
        """按当前所选难度刷新 HUD 的默认生命 / 时长显示（非游戏进行中时）。"""
        cfg = self.get_difficulty()
        self.hudLives.setText(f"❤×{cfg.lives}")
        self.hudTime.setText(f"{int(cfg.duration)}s")

    # ── 公开接口：由 main.py 调用更新 UI ────────────────────

    def update_score(self, score: int):
        self.hudScore.setText(str(score))

    def update_lives(self, lives: int):
        self.hudLives.setText(f"❤×{max(0, lives)}")

    def update_time(self, seconds: int):
        self.hudTime.setText(f"{max(0, seconds)}s")

    def set_game_state(self, state: str):
        """state: 'idle' / 'running' / 'paused' / 'over'"""
        self._current_state = state
        # 游戏进行中禁用难度切换，结束后恢复
        playing = state in ("running", "paused")
        for btn in self._diff_buttons.values():
            btn.setEnabled(not playing)
        if state == "running":
            self.startBtn.setEnabled(False)
            self.pauseBtn.setEnabled(True)
            self.pauseBtn.setText("⏸ 暂停")
            self.endBtn.setEnabled(True)
            self.statusLabel.setText("🎮 游戏进行中 — 在摄像头前用食指划过水果！")
            self.statusLabel.setStyleSheet("color: #4CAF50; font-size: 12px; font-weight: bold;")
        elif state == "paused":
            self.startBtn.setEnabled(False)
            self.pauseBtn.setEnabled(True)
            self.pauseBtn.setText("▶ 继续")
            self.endBtn.setEnabled(True)
            self.statusLabel.setText("⏸ 已暂停 — 点击「继续」恢复游戏")
            self.statusLabel.setStyleSheet("color: #FF9800; font-size: 12px; font-weight: bold;")
        elif state == "over":
            self.startBtn.setEnabled(True)
            self.startBtn.setText("🔄 再来一局")
            self.pauseBtn.setEnabled(False)
            self.pauseBtn.setText("⏸ 暂停")
            self.endBtn.setEnabled(False)
        else:  # idle
            self.startBtn.setEnabled(True)
            self.startBtn.setText("🚀 开始游戏")
            self.pauseBtn.setEnabled(False)
            self.pauseBtn.setText("⏸ 暂停")
            self.endBtn.setEnabled(False)
            self.statusLabel.setText("选择游戏与难度后点击「开始游戏」")
            self.statusLabel.setStyleSheet("color: #888; font-size: 12px;")
            self.hudScore.setText("0")
            self._refresh_hud_defaults()

    def show_game_over(self, reason: str, score: int):
        """游戏结束时显示结果。"""
        if reason == "dead":
            msg = f"💥 生命耗尽！最终得分: {score}"
        else:
            msg = f"⏰ 时间到！最终得分: {score}"
        self.statusLabel.setText(msg)
        self.statusLabel.setStyleSheet("color: #f44336; font-size: 14px; font-weight: bold;")
