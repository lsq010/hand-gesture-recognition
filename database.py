"""database.py — 多模态智能交互系统 · 数据库管理模块

使用 Python 内置 sqlite3，数据文件为 app_data.db（与本模块同目录）。
设计三张表并提供简易 CRUD：

  - logs             : 识别日志（时间 / 手势类型 / 面部表情 / YOLO 物体 / 翻译文本）
  - sign_dictionary  : 手势轨迹·特征 ↔ 手语词汇 映射
  - settings         : Kimi API Key / TTS 语速音色 / ASR 配置等（键值对）

线程安全说明：每个 CRUD 函数各自打开并关闭独立连接，
不跨线程共享连接，可在 Thread1/2/3 中安全调用。
"""

import os
import sqlite3

# 数据库文件与 database.py 同目录，避免受运行工作目录影响
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_data.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    gesture_type      TEXT,
    facial_expression TEXT,
    yolo_object       TEXT,
    translation_text  TEXT
);

CREATE TABLE IF NOT EXISTS sign_dictionary (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    gesture_name TEXT NOT NULL,
    trajectory   TEXT,
    features     TEXT,
    sign_word    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    description TEXT
);
"""


def _connect() -> sqlite3.Connection:
    """打开一个带 Row 工厂的连接（每次调用独立连接，线程安全）。"""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """创建三张表（幂等，可重复调用）。模块导入时自动执行一次。"""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


# ── logs：识别日志 ────────────────────────────────────
def insert_log(gesture_type=None, facial_expression=None,
               yolo_object=None, translation_text=None) -> int:
    """写入一条识别日志，返回新行 id。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO logs (gesture_type, facial_expression, yolo_object, translation_text) "
            "VALUES (?, ?, ?, ?)",
            (gesture_type, facial_expression, yolo_object, translation_text),
        )
        return cur.lastrowid


def get_logs(limit=50, order="DESC") -> list:
    """读取识别日志。

    :param limit: 返回条数上限
    :param order: 'DESC' 最新在前 / 'ASC' 最早在前
    :return: 字典列表，每个元素含 id/timestamp/gesture_type/...
    """
    order = "ASC" if order.upper().startswith("A") else "DESC"
    sql = f"SELECT * FROM logs ORDER BY id {order} LIMIT ?"
    with _connect() as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(r) for r in rows]


def clear_logs() -> int:
    """清空 logs 表全部记录，返回受影响行数。

    设计目的：识别历史只在程序运行期间保留；每次关闭程序时一次性清理，
    重启后从空白开始——避免历史无限增长、隐私不外泄，也便于按会话复盘。
    """
    with _connect() as conn:
        cur = conn.execute("DELETE FROM logs")
        return cur.rowcount


# ── sign_dictionary：手势↔手语映射 ─────────────────────
def insert_sign(gesture_name, sign_word, trajectory=None, features=None) -> int:
    """新增一条手势轨迹/特征 → 手语词汇映射，返回新行 id。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO sign_dictionary (gesture_name, trajectory, features, sign_word) "
            "VALUES (?, ?, ?, ?)",
            (gesture_name, trajectory, features, sign_word),
        )
        return cur.lastrowid


def get_signs(gesture_name=None) -> list:
    """按手势名（模糊）查询映射；不传参数则返回全部。"""
    with _connect() as conn:
        if gesture_name:
            rows = conn.execute(
                "SELECT * FROM sign_dictionary WHERE gesture_name LIKE ?",
                (f"%{gesture_name}%",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM sign_dictionary").fetchall()
    return [dict(r) for r in rows]


# ── settings：配置项（键值对）──────────────────────────
def save_setting(key, value, description=None) -> None:
    """保存 / 更新一个配置项（幂等，存在则覆盖 value）。"""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, description) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value=excluded.value, "
            "description=COALESCE(excluded.description, settings.description)",
            (key, value, description),
        )


def get_setting(key, default=None):
    """读取一个配置项；不存在时返回 default。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def get_all_settings() -> dict:
    """返回全部配置为 {key: value} 字典，便于一次性加载到 UI。"""
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


# 模块导入即确保表结构存在
init_db()
