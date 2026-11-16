"""AI-LiNK 云端接口客户端。

只实现本项目需要的四个接口：令牌续期、设备信息、设备状态、指令下发。
签名规则与 AI家智控 H5/App 保持一致，已针对 L1PB33-SA/S9 实测。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    ENCODE_SALT,
    HTTP_TIMEOUT,
    PATH_DEVICE_INFO,
    PATH_DEVICE_STATUS,
    PATH_INVOKE,
    PATH_LAST_TOKEN,
    SIGN_SECRET,
    TOKEN_REFRESH_MARGIN,
)

_LOGGER = logging.getLogger(__name__)


class AilinkError(Exception):
    """接口调用失败。"""


class AilinkAuthError(AilinkError):
    """令牌失效或签名校验失败。"""


class AilinkConnectionError(AilinkError):
    """网络不可达或服务异常。"""


def token_expires_at(token: str) -> int:
    """解析 JWT 的 exp 字段，解析失败返回 0。"""
    try:
        payload = token.split(".")[1]
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(decoded.decode("utf-8"))
        return int(data.get("exp", 0))
    except (IndexError, ValueError, KeyError, json.JSONDecodeError):
        return 0


class AilinkApi:
    """封装 AI-LiNK 云端的签名请求与设备控制。"""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_id: str,
        family_id: str,
        device_id: str,
        access_token: str,
        mobile: str = "",
        device_model: str = "",
    ) -> None:
        self._session = session
        self.user_id = user_id
        self.family_id = family_id
        self.device_id = device_id
        self.mobile = mobile
        self.device_model = device_model
        self._access_token = access_token

    @property
    def access_token(self) -> str:
        """当前使用的访问令牌。"""
        return self._access_token

    def set_access_token(self, token: str) -> None:
        """替换访问令牌。"""
        self._access_token = str(token)

    def _encode(self) -> str:
        """设备级 encode：md5(deviceId + familyId + userId + 盐)。"""
        raw = f"{self.device_id}{self.family_id}{self.user_id}{ENCODE_SALT}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _signed_headers(self, body_text: str) -> dict[str, str]:
        """按官方规则生成签名头。"""
        md5data = hashlib.md5(body_text.encode("utf-8")).hexdigest()
        timestamp = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())
        sign = hashlib.md5(
            f"{md5data}{timestamp}{nonce}{SIGN_SECRET}".encode("utf-8")
        ).hexdigest()
        return {
            "userid": self.user_id,
            "familyid": self.family_id,
            "source": "IOS",
            "version": "V1.0.1",
            "accept": "application/json",
            "content-type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self._access_token}",
            "md5data": md5data,
            "timestamp": timestamp,
            "nonce": nonce,
            "sign": sign,
            "traceid": f"{timestamp}-{uuid.uuid4().hex[:5]}-0-02",
        }

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        signed: bool = True,
        user_id: str = "",
    ) -> dict[str, Any]:
        """发送 JSON 请求并统一处理网络与业务错误。"""
        body_text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if signed:
            headers = self._signed_headers(body_text)
        else:
            headers = {
                "userid": user_id or self.user_id,
                "source": "IOS",
                "version": "V1.0.1",
                "accept": "application/json",
                "content-type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {self._access_token}",
            }

        try:
            async with self._session.post(
                f"{API_BASE}{path}",
                data=body_text.encode("utf-8"),
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
            ) as response:
                status = response.status
                text = await response.text()
        except asyncio.TimeoutError as err:
            raise AilinkConnectionError(f"请求超时: {path}") from err
        except aiohttp.ClientError as err:
            raise AilinkConnectionError(f"网络错误: {err}") from err

        if status in (401, 403):
            raise AilinkAuthError(f"认证失败: HTTP {status}")
        if status != 200:
            raise AilinkError(f"HTTP {status}: {text[:200]}")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise AilinkError(f"响应不是合法 JSON: {text[:200]}") from err

        business_status = str(data.get("status"))
        if business_status == "200":
            return data
        if business_status in {"401", "403", "999999"}:
            raise AilinkAuthError(
                f"认证失败: status={business_status} msg={data.get('msg')}"
            )
        raise AilinkError(
            f"接口返回失败: status={business_status} msg={data.get('msg')}"
        )

    async def async_refresh_token(self) -> str:
        """用 getLastToken 换新令牌，并更新内存中的令牌。"""
        data = await self._post_json(
            PATH_LAST_TOKEN,
            {"token": f"Bearer {self._access_token}"},
            signed=False,
            user_id=self.user_id,
        )
        info = data.get("info") or {}
        new_token = info.get("token")
        if not new_token:
            _LOGGER.warning(
                "令牌续期未返回新令牌，继续使用旧令牌: status=%s msg=%s",
                data.get("status"),
                data.get("msg"),
            )
            return self._access_token
        self._access_token = str(new_token)
        return self._access_token

    async def async_ensure_token(self) -> str:
        """令牌快过期时自动续期，返回可用令牌。"""
        expires_at = token_expires_at(self._access_token)
        if expires_at <= int(time.time()) + TOKEN_REFRESH_MARGIN:
            await self.async_refresh_token()
        return self._access_token

    async def async_get_device_info(self) -> dict[str, Any]:
        """查询设备基础信息，用于配置流程校验。"""
        data = await self._post_json(
            PATH_DEVICE_INFO,
            {
                "userId": self.user_id,
                "familyId": self.family_id,
                "deviceId": self.device_id,
                "encode": self._encode(),
            },
        )
        info = data.get("info")
        if not isinstance(info, dict):
            raise AilinkError("设备信息响应缺少 info")
        return info

    async def async_get_output_data(self) -> dict[str, Any]:
        """查询设备状态并返回 outputData。"""
        data = await self._post_json(
            PATH_DEVICE_STATUS,
            {
                "userId": self.user_id,
                "familyId": self.family_id,
                "deviceId": self.device_id,
                "encode": self._encode(),
            },
        )
        info = data.get("info") or {}
        entity = info.get("appDeviceStatusInfoEntity") or {}
        raw = entity.get("statusInfo")
        if not isinstance(raw, str):
            raise AilinkError("状态响应缺少 statusInfo")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as err:
            raise AilinkError(f"statusInfo 解析失败: {err}") from err

        events = parsed.get("events") or []
        if isinstance(events, list):
            for event in events:
                if isinstance(event, dict) and event.get("identifier") == "post":
                    output = event.get("outputData")
                    if isinstance(output, dict):
                        return output
        output = parsed.get("outputData")
        if isinstance(output, dict):
            return output
        raise AilinkError("状态响应中没有 outputData")

    async def async_set_cruise(self, enabled: bool) -> None:
        """开启或关闭热水循环。"""
        service = {
            "profile": {
                "deviceId": self.device_id,
                "productType": "24",
                "deviceType": self.device_model,
            },
            "service": {
                "identifier": "SetCruiseOnOff",
                "invokeChannel": "0",
                "inputData": {"CommandValue": "1" if enabled else "0"},
            },
        }
        payload = {
            "userId": self.user_id,
            "familyId": self.family_id,
            "deviceId": self.device_id,
            "commandSource": 1,
            "appSource": 2,
            "payLoad": json.dumps(service, separators=(",", ":"), ensure_ascii=False),
        }
        if self.mobile:
            payload["currUserMobile"] = self.mobile
        await self._post_json(PATH_INVOKE, payload)


def is_cruise_running(output: dict[str, Any]) -> bool:
    """根据设备上报判断循环是否在运行。"""
    def number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    if number(output.get("perWork")) == 1:
        return True
    if number(output.get("preWork")) == 1:
        return True
    return number(output.get("waterPumpSpeed")) > 0
