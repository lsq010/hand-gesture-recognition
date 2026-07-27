# -*- coding: utf-8 -*-
"""delete_user.py - 删除已注册的人脸账号（按用户名）

用法：
    python delete_user.py <用户名>

示例：
    python delete_user.py alice

说明：
    1. 从 auth.db 的 users 表中删除对应用户名的一行；
    2. 删除 faces/face_<label>_<序号>.jpg 的人脸照片；
    3. 删除 trainer.yml（下次启动登录窗口会自动重新训练）。
"""

import glob
import os
import sqlite3
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_DB = os.path.join(SCRIPT_DIR, "auth.db")
FACES_DIR = os.path.join(SCRIPT_DIR, "faces")
TRAINER_PATH = os.path.join(SCRIPT_DIR, "trainer.yml")


def main():
    if len(sys.argv) < 2:
        print("用法: python delete_user.py <用户名>")
        print("示例: python delete_user.py alice")
        sys.exit(1)

    username = sys.argv[1].strip()
    if not username:
        print("错误：用户名不能为空。")
        sys.exit(1)

    if not os.path.exists(AUTH_DB):
        print("未找到 auth.db，当前没有任何注册账号。")
        sys.exit(1)

    conn = sqlite3.connect(AUTH_DB)
    cur = conn.cursor()
    cur.execute("SELECT face_label FROM users WHERE username = ?", (username,))
    row = cur.fetchone()

    if row is None:
        print(f"未找到用户 '{username}'。")
        conn.close()
        sys.exit(1)

    label = int(row[0])
    image_pattern = os.path.join(FACES_DIR, f"face_{label}_*.jpg")
    images = glob.glob(image_pattern)

    print(f"\n将删除用户: {username}  (face_label = {label})")
    print(f"  数据库行: users 表中 1 条")
    print(f"  人脸图片: {len(images)} 张")
    for p in images:
        print(f"    - {os.path.basename(p)}")
    if os.path.exists(TRAINER_PATH):
        print(f"  trainer.yml: 将删除，下次启动自动重建")
    else:
        print(f"  trainer.yml: 不存在，无需处理")

    ans = input("\n确认删除？(y/N): ").strip().lower()
    if ans not in ("y", "yes"):
        print("已取消，未做任何删除。")
        conn.close()
        sys.exit(0)

    # 删除数据库行
    cur.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    print(f"已从 auth.db 删除用户 '{username}'。")

    # 删除人脸图片
    for p in images:
        os.remove(p)
        print(f"已删除 {os.path.basename(p)}")

    # 删除识别模型，让它下次启动自动重训
    if os.path.exists(TRAINER_PATH):
        os.remove(TRAINER_PATH)
        print("已删除 trainer.yml，下次运行 python main.py 时会自动重新训练。")

    print(f"\n用户 '{username}' 已彻底删除。")


if __name__ == "__main__":
    main()
