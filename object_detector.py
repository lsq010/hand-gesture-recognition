# object_detector.py
# 环境感知：YOLO-World（开放词汇）独立后台线程检测器
#
# 设计目标（Phase C）：
#   - 精准识别「药瓶/药盒」（COCO 无细分标签，故用 YOLO-World 开放词汇）
#   - YOLO-World-S 在 CPU 上约 100~200ms/帧，绝不能阻塞主视觉线程
#   - 独立 threading.Thread + Lock：主线程「随用随取」最新结果（stale-ok）
#   - 时间节流：后台最快每 fps_interval 秒跑一次（默认 0.25s ≈ 4 FPS）
#   - 固定词汇：英文 prompts（YOLO-World 官方推荐用法，CLIP 文本编码对中文语义
#     匹配显著弱于英文，CPU 上置信度经常 0.2~0.4，需要 conf=0.2 而不是 0.35）

import threading
import time

import cv2
from ultralytics import YOLOWorld


class ObjectDetector:
    def __init__(self, model_path="yolov8s-world.pt", target_classes=None,
                 conf=0.2, infer_width=416, fps_interval=0.25):
        """
        初始化 YOLO-World 独立线程检测器。

        :param model_path:   YOLO-World 权重（yolov8s-world.pt 等），
                             首次运行会自动下载。
        :param target_classes: 开放词汇提示词列表（**英文**，见下方默认）。
        :param conf:         置信度阈值（CPU 上 YOLO-World 建议 0.15~0.25）。
        :param infer_width:  后台推理时把帧缩放到此宽度（保持比例），提速。
        :param fps_interval: 后台推理最小间隔（秒），避免吃满 CPU。
        """
        if target_classes is None:
            # 开放词汇定义（精准覆盖药瓶/药盒）。英文 prompts 在 CLIP 上语义
            # 匹配显著好于中文；Phase C 验证英文版本先跑通。
            target_classes = [
                "phone",          # 手机
                "water bottle",   # 水杯
                "pill bottle",    # 药瓶
                "pill box",       # 药盒
                "remote control", # 遥控器
            ]
        self.target_classes = target_classes
        self.conf = conf
        self.infer_width = infer_width
        self.fps_interval = fps_interval

        print(">>> 正在加载 YOLO-World 模型...")
        self.model = YOLOWorld(model_path)

        # 重要：text_model 必须在 set_classes **之前**切换，否则 CLIP 已加载完
        # 编码器后再切也未必生效（切前已对 prompt 做了缓存/初始化）。
        # 默认 mobileclip:blt 依赖 GitHub/Apple 权重（本机网络不通必失败），
        # 强制 clip:ViT-B/32 用纯 OpenAI CLIP，本机已装 openai-clip+setuptools。
        try:
            self.model.model.text_model = "clip:ViT-B/32"
        except Exception as e:
            print(f"[ObjectDetector] 提示: 未能强制 clip:ViT-B/32 ({e})，"
                  f"若后续推理报 CLIP 相关错，请先 `pip install openai-clip setuptools`")

        # 预设开放词汇提示词 (Set Prompts) —— 必须在 text_model 切完之后再调
        self.model.set_classes(self.target_classes)

        # Debug：让用户能在终端直接看到当前 text_model 是不是真的切了
        try:
            current_tm = getattr(self.model.model, "text_model", "unknown")
            print(f">>> YOLO-World 加载完毕：text_model={current_tm!r}, "
                  f"classes={self.target_classes}")
        except Exception:
            print(">>> YOLO-World 加载完毕。")

        # 中英映射：内部与 YOLO-World 通信用英文（CLIP 语义匹配更准），
        # 显示/上层（Kimi/TTS）用中文。键是 target_classes 里的英文标签。
        self._zh_map = {
            "phone":          "手机",
            "water bottle":   "水杯",
            "pill bottle":    "药瓶",
            "pill box":       "药盒",
            "remote control": "遥控器",
        }

        # 线程控制与数据共享
        self.latest_frame = None
        self.detected_objects = []
        self.lock = threading.Lock()

        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def update_frame(self, frame):
        """
        主线程每帧调用，更新最新的待检测图像帧（不阻塞）。
        只存「最新一帧」的副本；后台取走后即清空，故不会积压。
        """
        if frame is None:
            return
        with self.lock:
            self.latest_frame = frame.copy()

    def get_detected_objects(self):
        """
        主线程随时调用，获取最新的识别结果列表（去重后的类别名）。
        """
        with self.lock:
            return list(self.detected_objects)

    def get_display_objects(self):
        """
        返回中文标签列表（用于 UI/日志/Kimi 输入）。如果某个英文类没有对应
        中文映射，原样返回英文。
        """
        return [self._zh_map.get(name, name) for name in self.get_detected_objects()]

    def _worker(self):
        """
        后台线程：定期取出 latest_frame 进行检测，更新 detected_objects。
        单帧推理异常不会拖垮整个线程。
        """
        while self.running:
            start_time = time.time()
            frame_to_process = None

            with self.lock:
                if self.latest_frame is not None:
                    frame_to_process = self.latest_frame
                    # 取走一帧后置空，避免对同一帧重复计算（stale-ok 设计）
                    self.latest_frame = None

            if frame_to_process is not None:
                try:
                    # 适当降采样以加速推理（保持比例）
                    h, w = frame_to_process.shape[:2]
                    rw = self.infer_width
                    rh = int(rw * h / w)
                    resized = cv2.resize(frame_to_process, (rw, rh))

                    # 运行 YOLO-World 推理
                    results = self.model.predict(
                        resized,
                        conf=self.conf,
                        verbose=False
                    )

                    boxes = results[0].boxes
                    new_objects = []
                    if boxes is not None and len(boxes) > 0:
                        for box in boxes:
                            cls_id = int(box.cls[0])
                            # 直接映射到定标的开放词汇列表，避免依赖
                            # results[0].names 的版本差异（部分 ultralytics
                            # 版本在 set_classes 后 names 仍是 COCO 原始映射）
                            if 0 <= cls_id < len(self.target_classes):
                                cls_name = self.target_classes[cls_id]
                                if cls_name not in new_objects:
                                    new_objects.append(cls_name)

                    with self.lock:
                        self.detected_objects = new_objects
                except Exception as e:  # 单帧失败不影响后台线程持续运行
                    print(f"[ObjectDetector] 推理异常已跳过: {e}")

            # 控制后台推理频率
            elapsed = time.time() - start_time
            time.sleep(max(0.01, self.fps_interval - elapsed))

    def stop(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)
