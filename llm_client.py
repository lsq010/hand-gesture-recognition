# llm_client.py
# 阶段 D 第一步：智能翻译与双向无障碍

import json
import os
from openai import OpenAI


class KimiLLMClient:
  _PLACEHOLDER_FRAGMENTS = (
      "your_key",
      "your-key",
      "xxxx",
      "placeholder",
      "sk-xxxx",
      "sk-your_key",
      "123456",
      "test",
      "none",
      "null",
  )

  def __init__(
      self,
      api_key=None,
      base_url="https://api.moonshot.cn/v1",
      model="moonshot-v1-8k",  # 👈 改回 Moonshot API 官方标准模型 ID
  ):
    """初始化 Kimi LLM 客户端。"""
    self.api_key = api_key or os.getenv("MOONSHOT_API_KEY", "")
    self.base_url = base_url
    self.model = model

    self.client = OpenAI(
        api_key=self.api_key or "placeholder",
        base_url=base_url,
    )

    self.system_prompt = (
        "你是一个专门为无障碍交流设计的智能手语/意图翻译助手。\n"
        "你会收到来自用户的多模态断续输入，包括：\n"
        "1. 识别到的手势词（静态手势/动态轨迹）\n"
        "2. 视觉感知的周围物品（YOLO 识别结果）\n"
        "3. 用户/对方的语音听写文本（ASR 结果）\n\n"
        "你的任务是：\n"
        "1. 将这些零碎的组合整合为一句通顺、自然、符合人类表达习惯的中文句子。\n"
        "2. 判断用户的核心意图（如：求助、表达需求、日常打招呼、询问等）。\n"
        "以 JSON 格式输出，必须包含以下两个字段：\n"
        '{"translated_text": "润色后的自然语言", "intent": "意图标签"}'
    )

  def is_configured(self):
    """Key 是否为有效（非空且非占位符）。"""
    k = (self.api_key or "").strip().lower()
    if not k:
      return False
    return not any(frag in k for frag in self._PLACEHOLDER_FRAGMENTS)

  def _rule_fallback(self, gestures, objects, asr_text):
    """离线规则兜底。"""
    parts = []
    if gestures:
      g = ", ".join(gestures) if isinstance(gestures, list) else str(gestures)
      parts.append(f"做了「{g}」手势")
    if objects:
      o = ", ".join(objects) if isinstance(objects, list) else str(objects)
      parts.append(f"指向/周围有「{o}」")
    if asr_text and asr_text.strip() and asr_text.strip() != "无":
      parts.append(f"并说「{asr_text.strip()}」")

    if not parts:
      return {
          "translated_text": "（暂无可翻译的输入）",
          "intent": "Unknown",
      }

    text = "用户" + "，".join(parts) + "。"
    hint = asr_text or ""
    if any(w in hint for w in ("帮", "拿", "给", "吃", "喝", "找", "开", "关")):
      intent = "求助需求"
    elif any(w in hint for w in ("你好", "您好", "早上", "晚上", "谢谢")):
      intent = "日常打招呼"
    else:
      intent = "表达需求"
    return {
        "translated_text": text,
        "intent": intent,
    }

  def translate_context(
      self, gestures=None, objects=None, asr_text="", timeout=10
  ):
    """组装上下文并请求 Kimi API。"""
    if not self.is_configured():
      fallback = self._rule_fallback(gestures, objects, asr_text)
      return {
          "translated_text": (
              "（未配置 MOONSHOT_API_KEY，已走本地规则兜底）"
              + fallback["translated_text"]
          ),
          "intent": fallback["intent"],
      }

    gesture_str = (
        ", ".join(gestures)
        if isinstance(gestures, list)
        else str(gestures or "无")
    )
    object_str = (
        ", ".join(objects) if isinstance(objects, list) else str(objects or "无")
    )
    asr_str = asr_text.strip() if asr_text else "无"

    user_input = (
        f"【手势输入】: {gesture_str}\n"
        f"【感知物品】: {object_str}\n"
        f"【语音辅助】: {asr_str}\n"
        "请整合为一句通顺的话并输出 JSON。"
    )

    try:
      response = self.client.chat.completions.create(
          model=self.model,
          messages=[
              {"role": "system", "content": self.system_prompt},
              {"role": "user", "content": user_input},
          ],
          temperature=0.3,
          response_format={"type": "json_object"},
          timeout=timeout,
      )

      res_content = response.choices[0].message.content
      res_json = json.loads(res_content)
      return {
          "translated_text": res_json.get("translated_text", "翻译解析失败"),
          "intent": res_json.get("intent", "Unknown"),
      }

    except Exception as e:
      print(f">>> Kimi API ({self.model}) 调用异常: {e}")
      return {
          "translated_text": f"翻译服务暂不可用 ({type(e).__name__})",
          "intent": "Error",
      }