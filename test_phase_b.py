# test_phase_b.py
# Phase B 验证脚本：动态手语与轨迹追踪（需真实摄像头）
#
# 运行：python test_phase_b.py
# 退出：按 Q
#
# 画面说明：
#   - 绿色轨迹线 = 左手掌心移动路径
#   - 蓝色(橙)轨迹线 = 右手掌心移动路径
#   - 顶部文字实时显示 静态手势(左/右) 与 动态手语(左/右)

import cv2
from vision_engine import VisionEngine
from sequence_tracker import SequenceTracker


def main():
    engine = VisionEngine(camera_index=0)
    tracker = SequenceTracker(max_length=35)

    print(">>> Phase B 测试启动：请在镜头前尝试 [挥手 / 左右划动 / 上下划动 / 画圈]。按 Q 退出。")

    while True:
        frame, res = engine.process_frame()
        if frame is None:
            print("[!] 摄像头读取失败或未检测到画面，已退出。")
            break

        # 1. 更新轨迹队列
        tracker.update(res["left_landmarks"], res["right_landmarks"])
        dyn_res = tracker.get_dynamic_gestures()

        # 2. 在画面上绘制轨迹线 (绿色: 左手, 橙蓝: 右手)
        h, w, _ = frame.shape
        for pts, color in [(tracker.left_pts, (0, 255, 0)),
                           (tracker.right_pts, (255, 200, 0))]:
            pts_list = list(pts)
            for i in range(1, len(pts_list)):
                p1 = (int(pts_list[i - 1][0] * w), int(pts_list[i - 1][1] * h))
                p2 = (int(pts_list[i][0] * w), int(pts_list[i][1] * h))
                cv2.line(frame, p1, p2, color, 2)

        # 3. 显示结果
        info_static = f"Static -> L: {res['left_gesture']} | R: {res['right_gesture']}"
        info_dynamic = f"Dynamic -> L: {dyn_res['left_dynamic']} | R: {dyn_res['right_dynamic']}"

        cv2.putText(frame, info_static, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, info_dynamic, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

        cv2.imshow("Phase B - Dynamic Gestures & Trajectory", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    engine.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
