#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 邮件 + 脚本框架生成模块

支持三个 provider：
- openai    -> GPT-4o / GPT-4o-mini
- gemini    -> Gemini 1.5 Flash
- dashscope -> 阿里云百炼（通义千问 qwen-turbo / qwen-plus）

输出：
- 韩文拍摄框架（给网红看）
- 韩文 BD 邀请邮件（发给网红）
"""

import json
import os
from typing import Literal

import requests


Provider = Literal["openai", "gemini", "dashscope"]


# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------

SHOOTING_FRAMEWORK_PROMPT = """你是一位熟悉韩国 YouTube 带货内容策划的专家。

请根据以下信息，为韩国网红写一份 **35 秒 YouTube Shorts 的拍摄框架**。
要求：
1. 只给框架（创作方向 + 必须包含元素 + 参考话术），不要逐字稿。
2. 语言自然、地道，符合韩国网红口播习惯。
3. 参考话术用韩语，括号里的说明用中文。

网红信息：
- 昵称：{channel_name}
- 内容基调：{content_tone}
- 粉丝称呼习惯：{fan_call}
- 常用钩子类型：{top_hook}
- 常用 CTA 方式：{top_cta}

产品信息：
- 产品名：{product_name}
- 现价：{price}원
- 原价：{original_price}원
- 核心卖点：{selling_points}

请按以下时间段输出（每个时间段给：画面、创作方向、必须包含元素、参考话术、字幕建议）：
0-3s 钩子
3-8s 共鸣
8-20s 产品展示
20-26s 信任背书
26-31s 价格锚点
31-35s CTA
"""


EMAIL_PROMPT = """你是一位 AliExpress 韩国网红 BD 专员，需要给韩国网红发一封商务合作邀请邮件。

要求：
1. 邮件全文用 **地道、自然的韩语** 书写，语气亲切但专业，像韩国本土商务邮件。
2. 不要出现明显的中式韩语或机器翻译痕迹。
3. 邮件结构：问候 -> 自我介绍 -> 合作邀请 -> 产品/脚本说明 -> 下一步行动 -> 结尾敬语。
4. 明确提到我们为她准备了 35 秒 YouTube Shorts 的拍摄框架，她可以参考并按自己的风格发挥。
5. 提及购买链接会放在 더보기란 或 고정댓글（根据网红常用 CTA 方式选择）。
6. 字数控制在 250-350 词韩语左右。

收件人信息：
- 网红昵称：{channel_name}
- 粉丝称呼习惯：{fan_call}
- 常用 CTA 方式：{top_cta}

我方信息：
- 发件人姓名：{sender_name}
- 合作平台：AliExpress

产品信息：
- 产品名：{product_name}
- 现价：{price}원
- 原价：{original_price}원
- 核心卖点：{selling_points}

拍摄框架摘要：
{framework_summary}

请直接输出邮件正文，不需要主题行，不需要署名之外的格式说明。
"""


# ---------------------------------------------------------------------------
# Provider 封装
# ---------------------------------------------------------------------------

class AIEmailGenerator:
    def __init__(
        self,
        provider: Provider = "openai",
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.provider = provider
        self.api_key = api_key or os.environ.get(self._env_key(provider))
        self.model = model or self._default_model(provider)
        if not self.api_key:
            raise ValueError(f"请提供 {provider} 的 API key")

    @staticmethod
    def _env_key(provider: Provider) -> str:
        return {
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "dashscope": "DASHSCOPE_API_KEY",
        }[provider]

    @staticmethod
    def _default_model(provider: Provider) -> str:
        return {
            "openai": "gpt-4o-mini",
            "gemini": "gemini-1.5-flash",
            "dashscope": "qwen-turbo",
        }[provider]

    def _call_openai(self, prompt: str) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一位韩国 YouTube 带货内容策划和商务 BD 专家，擅长写自然地道的韩语文案和商务邮件。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.75,
            "max_tokens": 1500,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_gemini(self, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        params = {"key": self.api_key}
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "你是一位韩国 YouTube 带货内容策划和商务 BD 专家，擅长写自然地道的韩语文案和商务邮件。"},
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.75,
                "maxOutputTokens": 1500,
            },
        }
        resp = requests.post(url, params=params, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Gemini 返回异常: {json.dumps(data, ensure_ascii=False)}") from e

    def _call_dashscope(self, prompt: str) -> str:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {"role": "system", "content": "你是一位韩国 YouTube 带货内容策划和商务 BD 专家，擅长写自然地道的韩语文案和商务邮件。"},
                    {"role": "user", "content": prompt},
                ]
            },
            "parameters": {
                "temperature": 0.75,
                "max_tokens": 1500,
                "result_format": "message",
            },
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["output"]["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"DashScope 返回异常: {json.dumps(data, ensure_ascii=False)}") from e

    def generate(self, prompt: str) -> str:
        if self.provider == "openai":
            return self._call_openai(prompt)
        if self.provider == "gemini":
            return self._call_gemini(prompt)
        if self.provider == "dashscope":
            return self._call_dashscope(prompt)
        raise ValueError(f"不支持的 provider: {self.provider}")

    # -----------------------------------------------------------------------
    # 业务接口
    # -----------------------------------------------------------------------

    def generate_framework(
        self,
        channel_name: str,
        content_tone: str,
        fan_call: str,
        top_hook: str,
        top_cta: str,
        product_name: str,
        price: str,
        original_price: str,
        selling_points: list[str],
    ) -> str:
        prompt = SHOOTING_FRAMEWORK_PROMPT.format(
            channel_name=channel_name,
            content_tone=content_tone,
            fan_call=fan_call,
            top_hook=top_hook,
            top_cta=top_cta,
            product_name=product_name,
            price=price,
            original_price=original_price,
            selling_points="\n".join([f"- {sp}" for sp in selling_points]),
        )
        return self.generate(prompt)

    def generate_email(
        self,
        channel_name: str,
        fan_call: str,
        top_cta: str,
        sender_name: str,
        product_name: str,
        price: str,
        original_price: str,
        selling_points: list[str],
        framework_summary: str,
    ) -> str:
        prompt = EMAIL_PROMPT.format(
            channel_name=channel_name,
            fan_call=fan_call,
            top_cta=top_cta,
            sender_name=sender_name,
            product_name=product_name,
            price=price,
            original_price=original_price,
            selling_points="\n".join([f"- {sp}" for sp in selling_points]),
            framework_summary=framework_summary,
        )
        return self.generate(prompt)

    def generate_framework_and_email(
        self,
        dna_card: dict,
        product_info: dict,
        sender_name: str = "아이비",
    ) -> dict:
        """一站式生成框架 + 邮件"""
        channel_name = dna_card.get("channel_name", "")
        content_tone = dna_card.get("content_tone", "亲切闺蜜型")
        fan_call = dna_card.get("fan_nicknames", ["여러분"])[0]
        top_hook = max(
            dna_card.get("top_hook_patterns", {}).items(),
            key=lambda x: x[1],
        )[0] if dna_card.get("top_hook_patterns") else "价格/折扣钩子"
        top_cta = max(
            dna_card.get("top_cta_patterns", {}).items(),
            key=lambda x: x[1],
        )[0] if dna_card.get("top_cta_patterns") else "더보기란/링크 언급"

        product_name = product_info.get("name", "产品")
        price = str(product_info.get("price", "?"))
        original_price = str(product_info.get("original_price", "?"))
        selling_points = product_info.get("selling_points", [])

        framework = self.generate_framework(
            channel_name=channel_name,
            content_tone=content_tone,
            fan_call=fan_call,
            top_hook=top_hook,
            top_cta=top_cta,
            product_name=product_name,
            price=price,
            original_price=original_price,
            selling_points=selling_points,
        )

        email = self.generate_email(
            channel_name=channel_name,
            fan_call=fan_call,
            top_cta=top_cta,
            sender_name=sender_name,
            product_name=product_name,
            price=price,
            original_price=original_price,
            selling_points=selling_points,
            framework_summary=framework[:800],
        )

        return {
            "framework": framework,
            "email": email,
            "provider": self.provider,
            "model": self.model,
        }


if __name__ == "__main__":
    import os
    gen = AIEmailGenerator(provider="dashscope")
    res = gen.generate_framework_and_email(
        dna_card={
            "channel_name": "네일집착걸",
            "content_tone": "亲切闺蜜型",
            "fan_nicknames": ["여러분"],
            "top_hook_patterns": {"提问/对比钩子": 5},
            "top_cta_patterns": {"할인/쿠폰 언급": 3},
        },
        product_info={
            "name": "메이크업 브러쉬 10종 세트",
            "price": "12,900",
            "original_price": "28,900",
            "selling_points": [
                "부드러운 인조모가 피부에 자극이 적어요",
                "파우치 포함이라 여행/외출할 때 편해요",
                "초보자도 바로 쓸 수 있는 기본 구성",
            ],
        },
        sender_name="아이비",
    )
    print("=== 框架 ===")
    print(res["framework"])
    print("\n=== 邮件 ===")
    print(res["email"])
