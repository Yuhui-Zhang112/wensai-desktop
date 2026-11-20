"""OpenAI-compatible DeepSeek client. The only outbound URL is the fixed API endpoint."""
import json
import sys
from typing import Protocol

import httpx

from .models import AgentConfig, ReviewError
from .scope import DESTINATION, json_text

SERVICE = "WenSai.DeepSeek"
ACCOUNT = "api_key"


def validate_key(key: str) -> str:
    """凭据格式校验：非空、ASCII、可打印、不含空白、长度受限。"""
    if (not isinstance(key, str) or not key or len(key) > 300 or not key.isascii()
            or not key.isprintable() or any(c.isspace() for c in key)):
        raise ReviewError("credential_invalid", "DeepSeek 凭据格式无效。")
    return key


class CredentialStore(Protocol):
    def read(self) -> str: ...


class SystemCredentialStore:
    def _backend(self):
        try:
            if sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring
                return WinVaultKeyring()
            if sys.platform == "darwin":
                from keyring.backends.macOS import Keyring
                return Keyring()
            if sys.platform.startswith("linux"):
                from keyring.backends.SecretService import Keyring
                return Keyring()
        except Exception as exc:
            raise ReviewError("credential_manager_unavailable", "无法访问系统密钥管理器。") from exc
        raise ReviewError("credential_manager_unavailable", "此系统没有受支持的系统密钥管理器。")

    def read(self):
        try:
            key = self._backend().get_password(SERVICE, ACCOUNT)
        except ReviewError:
            raise
        except Exception as exc:
            raise ReviewError("credential_manager_unavailable", "无法读取系统密钥管理器，请先解锁系统凭据。") from exc
        if not key:
            raise ReviewError("credential_missing", "系统密钥管理器尚未配置 DeepSeek 测试凭据。")
        return key

    def delete(self):
        """移除已保存的凭据；不存在时视为成功。"""
        try:
            self._backend().delete_password(SERVICE, ACCOUNT)
        except Exception:
            pass

    def write(self, key):
        validate_key(key)
        try:
            self._backend().set_password(SERVICE, ACCOUNT, key)
        except ReviewError:
            raise
        except Exception as exc:
            raise ReviewError("credential_write_failed", "无法保存到系统密钥管理器。") from exc


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, config: AgentConfig, *, credentials: CredentialStore | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.model = config.model
        self._credentials = credentials if credentials is not None else SystemCredentialStore()
        self._transport = transport

    @staticmethod
    def _check_status(status):
        if status == 200:
            return
        if status in {401, 403}:
            error = ("provider_auth", "DeepSeek 拒绝了凭据，请核对系统密钥和模型权限。", False)
        elif status == 402:
            error = ("provider_quota", "DeepSeek 账户余额不足或额度不可用。", False)
        elif status == 429:
            error = ("provider_rate_limit", "DeepSeek 限流，请稍后重试。", True)
        elif status in {408, 504}:
            error = ("provider_timeout", "DeepSeek 请求超时。", True)
        elif 500 <= status < 600:
            error = ("provider_unavailable", "DeepSeek 服务暂不可用。", True)
        else:
            error = ("provider_rejected", "DeepSeek 拒绝了本次请求，请核对模型配置。", False)
        raise ReviewError(error[0], error[1], retriable=error[2], http_status=status)

    async def complete(self, chunk, *, image_bytes=None):
        # Reading the OS store happens after scope validation by the runner.
        key = self._credentials.read()
        if not isinstance(key, str) or not key or len(key) > 300 or not key.isascii() or not key.isprintable() or any(c.isspace() for c in key):
            raise ReviewError("credential_invalid", "系统密钥管理器中的凭据格式无效。")
        if chunk.image and self.model != "deepseek-flash":
            raise ReviewError("model_no_vision", "当前模型不支持图片。请切换为 deepseek-flash 或仅确认文本。")
        body = {"model": self.model, "messages": chunk.messages(image_bytes), "max_tokens": self.config.max_output_tokens,
                "temperature": self.config.temperature, "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"}, "stream": False}
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json", "Accept-Encoding": "identity"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self.config.timeout_seconds,
                                         follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", DESTINATION, json=body, headers=headers) as response:
                    self._check_status(response.status_code)
                    raw = bytearray()
                    async for part in response.aiter_bytes():
                        raw.extend(part)
                        if len(raw) > self.config.max_response_bytes:
                            raise ReviewError("response_too_large", "DeepSeek 响应超过大小上限。", retriable=True, http_status=200)
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ReviewError("provider_timeout", "DeepSeek 请求超时。", retriable=True) from exc
        except httpx.HTTPError as exc:
            raise ReviewError("provider_network", "无法连接 DeepSeek，请检查网络。", retriable=True) from exc
        try:
            choice = json.loads(raw)["choices"][0]
            message = choice["message"]
            content = message.get("content")
            reason = choice.get("finish_reason")
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            raise ReviewError("provider_bad_response", "DeepSeek 返回了无法读取的响应。", retriable=True, http_status=200) from exc
        if reason == "length":
            raise ReviewError("output_truncated", "DeepSeek 输出达到长度上限，请缩小材料范围或调高输出上限。", retriable=True, http_status=200)
        if reason != "stop" or message.get("tool_calls"):
            raise ReviewError("provider_incomplete", "DeepSeek 未返回完整评审文本。", retriable=True, http_status=200)
        if not isinstance(content, str) or not content.strip():
            raise ReviewError("empty_output", "DeepSeek 返回空评审，请重试。", retriable=True, http_status=200)
        return content


MOCK_MATCHES = {
    "academic-paper-review": ("所有实验只测量一次", "methodology", 0, "invalidates", "增加独立重复测量，报告均值、波动和对照条件。"),
    "competition-proposal-review": ("预算总额为3000元，未列分项", "budget", 0, "weakens", "按采购项列出数量、单价、合计与估算依据。"),
    "ppt-defense-review": ("答辩限时5分钟，本页计划讲6分钟", "pacing", 0, "weakens", "将本页口述压缩到45秒，为验证结果和问答预留时间。"),
}


class MockProvider:
    name, model = "mock", "wensai-mock-v1"

    async def complete(self, chunk, *, image_bytes=None):
        phrase, criterion, standard, impact, suggestion = MOCK_MATCHES[chunk.skill_id]
        results = {"dimensions": [], "issues": []}
        for span in chunk.fragments:
            if phrase not in span.text:
                continue
            evidence = {"ref": span.ref, "quote": phrase}
            results["dimensions"].append({"criterion": criterion, "score": 3, "rationale": "任务 C 的固定教学样例命中。",
                                          "evidence": [evidence]})
            results["issues"].append({"criterion": criterion, "standard_index": standard, "impact": impact,
                                      "evidence": evidence, "suggestion": suggestion})
            break
        return json_text(results)
