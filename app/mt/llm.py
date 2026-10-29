"""OpenAI 兼容的 LLM 翻译客户端。

只要接口形如 POST {base}/v1/chat/completions 就能用：
DeepSeek、OpenAI、Moonshot、通义、智谱、本地 vLLM / Ollama(openai 兼容) 均可。
"""

from __future__ import annotations

import json
import re

import requests

from app.config import Config
from app.mt.base import TranslationError

_SYSTEM_PROMPT = """你是一个专业的界面文本翻译引擎。

任务：把用户给出的文本翻译成{target}。

规则：
1. 只输出译文本身，不要任何解释、前缀、引号或 Markdown 代码块。
2. 严格保留原文的换行与段落结构，一行对一行。
3. 不翻译：代码标识符、变量名、函数名、文件路径、URL、邮箱、版本号、
   快捷键组合（如 Ctrl+C、Alt+Tab）、单位符号。
4. 界面用语要简洁自然，符合{target}软件界面的习惯说法。
5. 同一段内术语保持一致；专有名词无法确定译名时保留原文。
6. 如果原文本身已经是{target}，原样返回。"""

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?|\n?```\s*$")


class LlmTranslator:
    name = "llm"

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------------
    @property
    def _headers(self) -> dict:
        key = (self.cfg.api_key or "").strip()
        if not key:
            raise TranslationError("还没有配置 API Key，请在「设置」里填写")
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _payload(self, text: str, target: str) -> dict:
        return {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT.format(target=target)},
                {"role": "user", "content": text},
            ],
            "temperature": float(self.cfg.temperature),
            "stream": False,
        }

    # ------------------------------------------------------------------
    def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> str:
        text = (text or "").strip()
        if not text:
            return ""
        if target_lang and target_lang.strip() in ("中文", "zh", "zh-CN"):
            if self._looks_chinese(text):
                return text
        elif target_lang.lower().startswith("en") and self._looks_english(text):
            return text

        try:
            url = self.cfg.endpoint()
        except ValueError as exc:
            raise TranslationError(str(exc)) from exc

        try:
            resp = requests.post(
                url,
                headers=self._headers,
                json=self._payload(text, target_lang),
                timeout=(10, int(self.cfg.timeout)),
            )
        except requests.Timeout as exc:
            raise TranslationError("翻译请求超时，请检查网络或稍后重试") from exc
        except requests.ConnectionError as exc:
            raise TranslationError("无法连接到翻译服务，请检查网络或 API 地址") from exc
        except requests.RequestException as exc:
            raise TranslationError(f"翻译请求失败：{exc}") from exc

        data = self._parse_response(resp)
        content = self._extract_content(data)
        return self._clean(content)

    # ------------------------------------------------------------------
    @staticmethod
    def _looks_chinese(text: str) -> bool:
        if not text:
            return False
        cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        letters = sum(1 for c in text if c.isalpha())
        return cjk >= 1 and cjk >= 0.15 * max(letters + cjk, 1)

    @staticmethod
    def _looks_english(text: str) -> bool:
        if not text:
            return False
        cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        total = sum(1 for c in text if c.isalpha())
        return total > 0 and cjk / max(total, 1) < 0.05

    @staticmethod
    def _parse_response(resp: requests.Response) -> dict:
        status = resp.status_code
        if status in (401, 403):
            raise TranslationError("API Key 无效或没有访问权限（401/403）")
        if status == 402:
            raise TranslationError("账户余额不足（402）")
        if status == 404:
            raise TranslationError("API 地址或模型名不存在（404），请检查设置")
        if status == 429:
            raise TranslationError("请求过于频繁或额度用尽（429），请稍后再试")
        if status >= 500:
            raise TranslationError(f"翻译服务暂时不可用（{status}）")
        if status != 200:
            detail = resp.text[:200].replace("\n", " ")
            raise TranslationError(f"翻译失败（{status}）：{detail}")

        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise TranslationError("翻译服务返回了无法解析的内容") from exc

    @staticmethod
    def _extract_content(data: dict) -> str:
        try:
            choices = data.get("choices") or []
            if not choices:
                err = (data.get("error") or {}).get("message")
                raise TranslationError(err or "翻译服务没有返回内容")
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
            if isinstance(content, list):  # 某些实现返回分段数组
                content = "".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            if not content.strip():
                raise TranslationError("翻译结果为空，请重试")
            return content
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationError("解析翻译结果失败") from exc

    @staticmethod
    def _clean(text: str) -> str:
        out = _FENCE.sub("", text.strip())
        return out.strip()
