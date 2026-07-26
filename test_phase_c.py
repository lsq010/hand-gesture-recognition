# test_phase_c.py
# 验证多线程下 YOLO-World 是否能在不影响 MediaPipe 手势 FPS 的前提下，
# 准确识别出「药瓶/水杯/手机」等开放词汇目标。
#
# 运行：python test_phase_c.py  （首次运行会自动下载 yolov8s-world.pt 权重）

import cv2
import time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from vision_engine import VisionEngine
from object_detector import ObjectDetector


# 内联中文绘制工具：OpenCV cv2.putText 只支持 ASCII，画中文会变问号。
# 临时内联以避免依赖尚未落地的 core/text_draw.py。
_FONT = None


def _get_font(size: int = 22):
    """尝试加载一个支持中文的系统字体；失败则退回默认位图（仍可能画不出中文）。"""
    global _FONT
    if _FONT is not None:
        return _FONT
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
        r"C:\Windows\Fonts\simhei.ttf",      # 黑体
        r"C:\Windows\Fonts\msyhbd.ttc",     # 微软雅黑 Bold
        "/System/Library/Fonts/PingFang.ttc",  # macOS
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux
    ]
    for path in candidates:
        try:
            _FONT = ImageFont.truetype(path, size)
            print(f">>> 中文字体加载成功: {path}")
            return _FONT
        except Exception:
            continue
    print(">>> 警告: 未找到中文字体，将回退到 PIL 默认（中文可能显示为方块）")
    _FONT = ImageFont.load_default()
    return _FONT


def draw_chinese_text(img_bgr, text, pos, color_bgr=(0, 165, 255), size=22):
    """
    在 BGR 帧上绘制中文（用 PIL）。
    :param img_bgr:  OpenCV BGR 图像
    :param text:    要绘制的字符串
    :param pos:     (x, y) 起点
    :param color_bgr: BGR 颜色元组
    :param size:    字号
    """
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil_img)
    font = _get_font(size)
    # PIL 用 RGB 颜色
    color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
    draw.text(pos, text, font=font, fill=color_rgb)
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def main():
    engine = VisionEngine(camera_index=0)
    # 第一次初始化会下载/加载 yolo-world 权重（主线程阻塞一次，属正常）
    detector = ObjectDetector(model_path="yolov8s-world.pt")

    print(">>> Phase C 测试启动：请在镜头前出示 手机 / 水杯 / 药瓶 / 药盒。按 Q 退出。")

    prev_time = time.time()
    fps = 0.0

    while True:
        frame, res = engine.process_frame()
        if frame is None:
            break

        # 1. 喂帧给 YOLO 后台线程（非阻塞，仅 copy 最新一帧）
        detector.update_frame(frame)

        # 2. 读取当前最新的识别结果（随时可取，不等待后台）
        objects = detector.get_display_objects()  # 用中文显示

        # 计算主画面 FPS（验证是否因 YOLO 后台而卡顿）
        curr_time = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / (curr_time - prev_time + 1e-5))
        prev_time = curr_time

        # 3. 画面渲染
        info_hand = f"Hand L: {res['left_gesture']} | R: {res['right_gesture']}"
        info_obj_zh = f"检测到: {', '.join(objects) if objects else '无'}"
        info_obj_en = f"YOLO Objects: {', '.join(detector.get_detected_objects()) if detector.get_detected_objects() else 'None'}"
        info_fps = f"Main Pipeline FPS: {fps:.1f}"

        # 纯英文/数字的走 cv2.putText（更快）
        cv2.putText(frame, info_hand, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, info_obj_en, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        cv2.putText(frame, info_fps, (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        # 中文走 PIL（中文字体在 cv2.putText 下会变 ????）
        frame = draw_chinese_text(frame, info_obj_zh, (20, 155),
                                  color_bgr=(0, 165, 255), size=22)

        cv2.imshow("Phase C - Object Detection & Threading Test", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    detector.stop()
    engine.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
