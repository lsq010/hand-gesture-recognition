import os
from openai import OpenAI


class KimiLLMClient:

  def __init__(
      self,
      api_key=None,
      model="kimi-latest",
  ):
    # 优先生效传入的 key；其次读环境变量；不内置任何默认 key
    # （旧版硬编码 key 已泄露到 GitHub，务必去 Moonshot 控制台撤销）
    # 清洗：去首尾空白 + 去首尾可能夹带的引号（微信/网页复制常带入 " 或 '）
    # 语义：api_key=None → 读环境变量（供脚本/test_phase_d 使用）
    #       api_key=""   → 视为"故意为空"，不读环境变量（GUI 未配置时用，避免 env 隐式绕过）
    #       api_key="sk-…" → 用传入值
    if api_key is None:
        raw = os.environ.get("MOONSHOT_API_KEY", "")
    else:
        raw = api_key
    self.api_key = raw.strip().strip('"\'').strip()

    # 候选模型列表：moonshot-v1-8k 无冷启动、响应最快，放首位；
    # kimi-latest / kimi-k3 作为备选（可能冷启动慢）。
    self.candidate_models = ["moonshot-v1-8k", "kimi-latest", "kimi-k3"]

    # 未配置时仅创建占位客户端；真正请求前 is_configured() 会拦截并走本地兜底
    self.client = OpenAI(
        api_key=self.api_key if self.api_key else "placeholder",
        base_url="https://api.moonshot.cn/v1",
    )

  def is_configured(self) -> bool:
    """检查 API Key 是否配置"""
    return bool(self.api_key and self.api_key.strip())

  def chat(self, text="", history=None) -> dict:
    """普通对话：让 Kimi 真正回答用户的问题。

    system prompt 是普通助手身份，Kimi 会直接、清晰地回答问题，
    不会把输入当作「待润色材料」改写。
    """
    text = (text or "").strip()
    if not text:
      return {"text": "（空消息）", "intent": "空"}

    if not self.is_configured():
      return {
          "text": f"（未配置 API Key，本地兜底）{text}",
          "intent": "兜底模式",
      }

    system_prompt = (
        "你是 Kimi，一个有帮助的、友善的中文 AI 助手。"
        "请直接、清晰地回答用户问题；不要把你的回答限定为对输入的改写或润色，"
        "也不要把输入当作「待润色材料」——把它当成用户真实在说的话，正常作答即可。"
    )
    msgs = [{"role": "system", "content": system_prompt}]
    if history:
      msgs.extend(history)
    msgs.append({"role": "user", "content": text})

    last_error = None
    last_status = None
    for m in self.candidate_models:
      try:
        response = self.client.chat.completions.create(
            model=m,
            messages=msgs,
            temperature=1,
            timeout=30,
        )
        text_out = response.choices[0].message.content.strip()
        return {"text": text_out, "intent": "对话"}
      except Exception as e:
        last_error = e
        status = getattr(e, "status_code", None)
        if status is None:
          resp = getattr(e, "response", None)
          status = getattr(resp, "status_code", None) if resp is not None else None
        if status:
          last_status = status
        continue

    # 与 translate_context 同样的友好错误提示（401/429 复用现有文案）
    err_text = str(last_error) if last_error else "未知错误"
    err_lc = err_text.lower()
    if (
        last_status == 401
        or "401" in err_text[:32]
        or "invalid authentication" in err_lc
        or "invalid_api_key" in err_lc
    ):
      friendly = (
          "⚠ Moonshot API Key 认证失败（401）。请到 Moonshot 控制台核对："
          "①Key 是否完整复制（无空格/换行残留）；"
          "②Key 是否被撤销/过期；"
          "③账号是否已开通 API 访问。"
          "然后回到「系统设置」重新粘贴并点「保存配置」。"
      )
      print(f">>> Kimi API 401 认证失败: {last_error}")
      return {"text": friendly, "intent": "Error"}
    if last_status == 429 or "rate limit" in err_lc or "insufficient_quota" in err_lc:
      friendly = (
          "⚠ Moonshot API 触发限流（429）或配额不足。请稍后再试，"
          "或到 Moonshot 控制台查看账户余额。"
      )
      print(f">>> Kimi API 429 限流: {last_error}")
      return {"text": friendly, "intent": "Error"}
    print(f">>> Kimi API 调用异常 (status={last_status}): {last_error}")
    return {
        "text": f"对话服务暂时不可用 ({last_error})",
        "intent": "Error",
    }

  def translate_context(
      self, gestures=None, objects=None, asr_text=""
  ) -> dict:
    """结合多模态数据生成表达"""
    gestures = gestures or []
    objects = objects or []

    if not self.is_configured():
      return {
          "translated_text": (
              f"（未配置 API Key，本地兜底）用户手势：{','.join(gestures)} |"
              f" 物品：{','.join(objects)} | 语音：{asr_text}"
          ),
          "intent": "兜底模式",
      }

    prompt = (
        f"请结合以下多模态感知数据进行无障碍语境润色，用一句通顺、自然的话表达用户的完整意图：\n"
        f"- 手势表达: {', '.join(gestures) if gestures else '无'}\n"
        f"- 周围物品/指向: {', '.join(objects) if objects else '无'}\n"
        f"- 语音听写: {asr_text if asr_text else '无'}\n"
    )

    last_error = None
    last_status = None
    # 循环尝试可用的模型名称，直到有一个成功
    for m in self.candidate_models:
      try:
        response = self.client.chat.completions.create(
            model=m,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个无障碍交流助理。请将残障人士不连贯的手势、视线物品和简短语音合成一句表达贴切自然的话。"
                        "【极其重要】请直接输出润色后的那句话本身！绝对不要包含任何前缀（如'润色后的表达：'）、Markdown格式（如**）、解释或分析说明！"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=1,
            timeout=30,
        )
        text = response.choices[0].message.content.strip()
        return {"translated_text": text, "intent": "交流需求"}
      except Exception as e:
        last_error = e
        # 提取 HTTP 状态码（openai SDK 在 SDKError 上挂 status_code / response.status_code）
        status = getattr(e, "status_code", None)
        if status is None:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None) if resp is not None else None
        if status:
            last_status = status
        continue

    # 全部候选模型都失败 → 给出针对性、可执行的提示，而不是裸露异常堆栈
    err_text = str(last_error) if last_error else "未知错误"
    err_lc = err_text.lower()
    if (
        last_status == 401
        or "401" in err_text[:32]
        or "invalid authentication" in err_lc
        or "invalid_api_key" in err_lc
    ):
        friendly = (
            "⚠ Moonshot API Key 认证失败（401）。请到 Moonshot 控制台核对："
            "①Key 是否完整复制（无空格/换行残留）；"
            "②Key 是否被撤销/过期；"
            "③账号是否已开通 API 访问。"
            "然后回到「系统设置」重新粘贴并点「保存配置」。"
        )
        print(f">>> Kimi API 401 认证失败: {last_error}")
        return {"translated_text": friendly, "intent": "Error"}
    if last_status == 429 or "rate limit" in err_lc or "insufficient_quota" in err_lc:
        friendly = (
            "⚠ Moonshot API 触发限流（429）或配额不足。请稍后再试，"
            "或到 Moonshot 控制台查看账户余额。"
        )
        print(f">>> Kimi API 429 限流: {last_error}")
        return {"translated_text": friendly, "intent": "Error"}
    print(f">>> Kimi API 调用异常 (status={last_status}): {last_error}")
    return {
        "translated_text": f"翻译服务暂时不可用 ({last_error})",
        "intent": "Error",
    }


if __name__ == "__main__":
  client = KimiLLMClient()
  print("配置状态:", client.is_configured())
