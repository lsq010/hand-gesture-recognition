# asr_tts.py
# 阶段 D 第二步：集成 Edge-TTS（异步 TTS 文本转语音播报）与
# Faster-Whisper（按需 ASR 语音识别）。
#
# TTSManager：edge-tts 生成语音 → 保存为唯一临时 mp3 → pygame 播放 → 清理。
# ASRManager：faster-whisper 懒加载（CPU + INT8 量化），按文件转写。

import asyncio
import os
import tempfile
import threading
import uuid

import edge_tts
import pygame

# 初始化 pygame mixer 用于音频播放（headless 环境可能失败，已兜底）
try:
    pygame.mixer.init()
except Exception as e:  # noqa: BLE001
    print(f">>> Pygame Mixer 初始化提示: {e}")


class TTSManager:
    def __init__(self, voice="zh-CN-XiaoxiaoNeural"):
        """Edge-TTS 异步语音播报封装。"""
        self.voice = voice

    def speak(self, text, block=False):
        """
        播报接口（新线程中运行 asyncio 事件循环）。

        :param text:  要播报的文本。
        :param block: 是否阻塞当前线程直到播放结束。
                      - False（默认）：非阻塞，后台 daemon 线程播报。
                        ⚠️ 仅适合嵌入主循环（main.py）持续运行的场景。
                      - True：阻塞当前线程直到后台 daemon 线程 join。
                        ✅ 用于测试脚本 / 一次性播报，避免主线程在后台
                        TTS 还没建联 edge-tts 时提前 exit，导致 asyncio
                        抛 "cannot schedule new futures after shutdown"。
        """
        if not text or not text.strip():
            return

        def _run():
            try:
                asyncio.run(self._async_speak(text))
            except RuntimeError as e:
                # 兜底：主进程退出时 Python 销毁全局 ThreadPoolExecutor，
                # 后台 asyncio 事件循环试图提交新 future 会抛此错。
                # 在测试脚本里基本是 "时间没留够" 的信号，这里静默吞掉。
                print(f">>> TTS 后台线程随主进程退出而停止: {e}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        if block:
            t.join()

    async def _async_speak(self, text):
        # 每个请求用唯一临时文件，避免并发 speak 互相覆盖同一 mp3
        tmp_path = os.path.join(
            tempfile.gettempdir(), f"tts_{uuid.uuid4().hex}.mp3"
        )
        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(tmp_path)

            if os.path.exists(tmp_path):
                # 防止 mixer 已被外部 quit（比如测试清理时）导致 load 报错
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                pygame.mixer.music.load(tmp_path)
                pygame.mixer.music.play()
                # 异步让出事件循环：避免 pygame.time.Clock().tick 的
                # busy-wait 占 CPU，也允许期间其他 await 任务调度。
                while pygame.mixer.music.get_busy():
                    await asyncio.sleep(0.1)
                pygame.mixer.music.unload()
        except Exception as e:  # noqa: BLE001
            print(f">>> TTS 播报异常: {e}")
        finally:
            # 播放结束（或异常）后清理临时文件
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:  # noqa: BLE001
                pass


class ASRManager:
    def __init__(self, model_size="tiny"):
        """Faster-Whisper 按需语音听写封装。"""
        self.model = None
        self.model_size = model_size
        self.is_recording = False

    def _lazy_load_model(self):
        """延时加载 whisper 模型，省启动内存。"""
        if self.model is None:
            print(f">>> 正在加载 Faster-Whisper ({self.model_size})...")
            from faster_whisper import WhisperModel

            # CPU + INT8 量化，尽量榨干性能
            self.model = WhisperModel(
                self.model_size, device="cpu", compute_type="int8"
            )
            print(">>> Faster-Whisper 加载完成！")

    def transcribe_audio_file(self, audio_file_path):
        """对传入的 wav/mp3 音频文件进行识别。"""
        self._lazy_load_model()
        if not os.path.exists(audio_file_path):
            return ""

        try:
            segments, _ = self.model.transcribe(
                audio_file_path, beam_size=1, language="zh"
            )
            text = "".join([seg.text for seg in segments])
            return text.strip()
        except Exception as e:  # noqa: BLE001
            print(f">>> ASR 识别失败: {e}")
            return ""
