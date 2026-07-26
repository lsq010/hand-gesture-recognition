# test_phase_a.py
# Phase A 验证脚本：观察骨骼绘制 + 终端打印的静态手势识别结果。
# 用法：python test_phase_a.py  （按 Q 退出）

import cv2
from vision_engine import VisionEngine


def main():
    engine = VisionEngine(camera_index=0)
    print(">>> Phase A 测试启动：请在镜头前展示 握拳 / OK / 指向 / 数字1-5 / 双手比心。按 Q 退出。")

    while True:
        frame, res = engine.process_frame()
        if frame is None:
            print("[test_phase_a] 摄像头读取失败（检查 camera_index / 权限 / 是否被占用）。")
            break

        # 在画面上实时显示识别结果
        info_str = f"L: {res['left_gesture']} | R: {res['right_gesture']} | Heart: {res['is_heart']}"
        cv2.putText(frame, info_str, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        cv2.imshow("Phase A - Hands & Static Gestures", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    engine.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
