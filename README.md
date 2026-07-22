# 🖐️ AI 手势识别系统

基于 MediaPipe 的实时手势识别系统，使用 PySide6 构建图形界面，支持双手同时识别、13种手势分类与手势方向检测。

## 📺 效果演示

<p align="center">
  <img src="docs/hand-gesture-recognition.gif" alt="系统运行演示" width="85%">
</p>

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| **实时识别** | 通过摄像头实时检测手势，30 FPS 流畅运行 |
| **双手检测** | 同时识别左右手，右侧面板分栏显示结果 |
| **13 种手势** | OK、握拳、张开手掌、点赞、拇指向下、指向、食指竖起、胜利、三指、四指、安静、打电话、比心 |
| **手势含义** | 每个手势配有中文含义，显示在识别面板下方 |
| **手势方向** | 检测手掌朝向（左/右/上/下/正中） |
| **手部骨架** | 可开关的 21 关键点骨架绘制 |
| **画面镜像** | 自拍视角镜像翻转 |
| **截图保存** | 截图到内存后再保存，两步操作防止误存 |
| **日志导出** | 手势变化时自动记录，支持 CSV 导出 |
| **深色 UI** | 白色虚线边框 + 深色主题的现代化界面 |

## 手势一览

| 手势 | 名称 | 含义 |
|------|------|------|
| 👍 | 点赞 | 赞赏 / 棒 / 同意 / 没问题 / 搞定 |
| 👎 | 拇指向下 | 差劲 / 反对 / 不同意 / 否定 |
| 👌 | OK | 好的 / 确定 / 没问题 |
| ✌️ | 胜利 | 胜利 / 和平 / 数字2 |
| 🖐️ | 张开手掌 | 停止 / 拒绝 / 稍等 |
| ☝️ | 食指竖起 | 提示注意 / 稍等一下 / 数字1 |
| 🤫 | 安静 | 保持安静 / 闭嘴 / 保密 |
| 🤙 | 打电话 | 给我打电话 / 放松 / 酷 |
| 🫰 | 比心 | 表达爱意 / 感谢 |
| ✊ | 握拳 | 坚持 / 加油 / 力量 / 团结 |

## 环境要求

- Python **3.9+**
- Windows / Linux / macOS（支持摄像头）

## 安装与运行

### 1. 克隆仓库

```bash
git clone https://github.com/lsq010/hand-gesture-recognition
cd hand-gesture-recognition
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

> ⚠️ **注意**：`mediapipe` 版本必须锁定 `==0.10.14`，因为新版移除了 `solutions` API，本项目依赖该 API 进行手势识别。

### 4. 运行

```bash
python main.py
```

Windows 用户也可直接双击 `run_gui.bat`。

按 **ESC** 键退出程序。

## 项目结构

```
hand-gesture-recognition/
├── docs/
├── main.py                    # 主程序（PySide6 GUI 控制器）
├── gesture_recognition.py     # 手势识别核心逻辑
├── rec.py                     # UI 代码（由 rec.ui 自动生成）
├── rec.ui                     # Qt Designer UI 源文件
├── check.png                  # 复选框蓝色对号图标
├── requirements.txt           # Python 依赖
├── setup.py                   # 包安装配置
├── run_gui.bat                # Windows 快捷启动（GUI 版）
├── run_gesture.bat            # Windows 快捷启动（终端版）
├── .gitignore                 # Git 忽略规则
├── LICENSE                    # MIT 许可证
└── README.md                  # 项目说明（本文件）
```

## 技术说明

- **手势识别**：基于 MediaPipe Hands 的 21 个手部关键点，通过指尖相对位置、指间距离、手指计数判断手势。
- **图形界面**：使用 PySide6（Qt for Python）构建，QTimer 驱动帧循环，避免 `while True` 阻塞 UI。
- **中文渲染**：PIL（Pillow）绘制中文字体到画面，解决 OpenCV `putText` 不支持中文的问题。
- **双手逻辑**：`max_num_hands=2`，根据 MediaPipe 返回的 `handedness` 分配到左右手结果栏。

## 常见问题

**Q: 运行报错 `No module named 'cv2'`？**  
A: 虚拟环境未安装依赖，执行 `pip install -r requirements.txt`。

**Q: 出现 `mediapipe has no attribute 'solutions'`？**  
A: mediapipe 版本过高，执行 `pip install mediapipe==0.10.14`。

**Q: 摄像头打开失败？**  
A: 检查摄像头是否被其他程序占用，或尝试更换 USB 端口。

## 许可证

本项目使用 [MIT License](LICENSE)。
