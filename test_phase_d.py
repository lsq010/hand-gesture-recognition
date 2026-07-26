# test_phase_d.py
# 验证多模态数据输入 -> Kimi LLM 翻译 -> Edge-TTS 播报全链路。
#
# 运行：python test_phase_d.py
#   - 已设 MOONSHOT_API_KEY：真实调用 Kimi K2.6 / moonshot-v1-8k
#   - 未设 / 占位符：自动走本地规则兜底（不联网、不报错）

import os

from asr_tts import TTSManager
from llm_client import KimiLLMClient


def main():
    print(">>> Phase D 测试启动...")

    llm = KimiLLMClient()
    tts = TTSManager()

    if not llm.is_configured():
        print(">>> 未检测到有效 MOONSHOT_API_KEY，将走【本地规则兜底】"
              "（结果来自本地拼接，非 Kimi 润色）。")

    print("\n1. 正在模拟【指向 + 药瓶 + 水杯】组合输入...")
    result = llm.translate_context(
        gestures=["指向"], objects=["药瓶", "水杯"], asr_text="帮我拿一下"
    )

    print(">>> 返回 JSON:")
    print(f"    翻译文本: {result['translated_text']}")
    print(f"    核心意图: {result['intent']}")

    # 2. 测试 Edge-TTS 播报（需联网；失败仅打印异常不影响主流程）
    print("\n2. 正在通过 Edge-TTS 播报返回文本...")
    # block=True：阻塞等 TTS 播完再往下走，避免主线程提前 exit
    # 导致后台 asyncio 抛 "cannot schedule new futures after shutdown"
    tts.speak(result["translated_text"], block=True)

    print("\n✅ Phase D 基础调用测试完毕！")


if __name__ == "__main__":
    main()
