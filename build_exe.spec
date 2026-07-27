# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# PyInstaller 打包配置（单文件夹 + 内置模型权重，彻底离线）
# 用法（在本机「装齐依赖」的 Python 环境下执行）：
#     pyinstaller build_exe.spec
# 产物：dist/手势无障碍交流系统/  （整个文件夹一起分发，双击其中的 exe 即可）
# -----------------------------------------------------------------------------
# 注意：yolov8s-world.pt 与 weights/clip/ 属于运行时下载的模型，默认被
# .gitignore 忽略。打包「内置」它们前，请先确保本机项目根已存在这些文件
# （首次运行 main.py 并打开「实时监测」标签页会自动下载，或手动放置）。
# 若某资源缺失，脚本会打印 [warn] 并跳过（该资源运行时将改为联网下载）。
# =============================================================================

import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# spec 所在目录即项目根（保证无论从哪运行 pyinstaller 都能定位资源）
ROOT = SPECPATH

# ---- 需要随 exe 发布的数据文件 --------------------------------------------
datas = []

def add_data(src, dst):
    """源存在才加入；缺失则告警跳过（不阻断打包）。"""
    abs_src = src if os.path.isabs(src) else os.path.join(ROOT, src)
    if os.path.exists(abs_src):
        datas.append((abs_src, dst))
    else:
        print(f"[warn] 未找到资源，已跳过（运行时需联网下载）：{abs_src}")

add_data("haar", "haar")                 # 人脸 Haar 级联（仓库内，必含）
add_data("check.png", ".")              # 复选框图标（rec.py 样式引用）
add_data("yolov8s-world.pt", ".")       # YOLO-World 权重（约 27MB）
add_data("weights", "weights")          # CLIP 文本编码器权重（首次运行自动下载）

# ---- 隐藏导入（PyInstaller 无法静态分析到的动态导入） ----------------------
hiddenimports = [
    "cv2", "numpy",
    "PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "mediapipe",
    "ultralytics", "ultralytics.models", "ultralytics.nn", "ultralytics.cfg",
    "faster_whisper", "ctranslate2", "onnxruntime", "tokenizers",
    "openai", "edge_tts", "pygame", "sounddevice", "sqlite3",
]
# 递归收集这些易漏的子模块（MediaPipe / ultralytics 尤其需要）
for _mod in ("mediapipe", "ultralytics", "faster_whisper", "ctranslate2"):
    hiddenimports += collect_submodules(_mod)

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,          # 单文件夹：二进制放 coll 目录，exe 引用之
    name="手势无障碍交流系统",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # GUI 程序：不弹黑色控制台窗口
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="手势无障碍交流系统",
)
