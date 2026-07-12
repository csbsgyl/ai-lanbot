from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

import aiohttp

from .commands import CommandType


class GatewayError(RuntimeError):
    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


class IDCQueryGateway:
    _QUERY_PATHS = {
        CommandType.IP: '/v1/ip/{ip}/summary',
        CommandType.PROTECTION: '/v1/ip/{ip}/protection',
        CommandType.BLOCK: '/v1/ip/{ip}/block-status',
        CommandType.TRAFFIC: '/v1/ip/{ip}/traffic',
        CommandType.BUSINESSES: '/v1/account/businesses',
        CommandType.TICKETS: '/v1/account/tickets',
        CommandType.BALANCE: '/v1/account/balance',
    }

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        verify_tls: bool,
    ):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.timeout_seconds = max(1.0, timeout_seconds)
        self.verify_tls = verify_tls

    async def verify_binding(
        self,
        *,
        group_id: str,
        user_id: str,
        member_id: str,
        verification_code: str,
        request_id: str,
    ) -> dict[str, Any]:
        payload = await self._request(
            'POST',
            '/v1/bindings/verify',
            group_id=group_id,
            user_id=user_id,
            request_id=request_id,
            json_body={
                'group_id': group_id,
                'user_id': user_id,
                'member_id': member_id,
                'verification_code': verification_code,
            },
        )
        data = payload.get('data', payload)
        return data if isinstance(data, dict) else {}

    async def unbind(
        self,
        *,
        group_id: str,
        user_id: str,
        member_id: str,
        request_id: str,
    ) -> None:
        await self._request(
            'DELETE',
            f'/v1/bindings/{quote(group_id, safe="")}',
            group_id=group_id,
            user_id=user_id,
            member_id=member_id,
            request_id=request_id,
        )

    async def query(
        self,
        *,
        command_type: CommandType,
        arguments: dict[str, str],
        group_id: str,
        user_id: str,
        member_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        path_template = self._QUERY_PATHS[command_type]
        path = path_template.format(ip=quote(arguments.get('ip', ''), safe=':'))
        return await self._request(
            'GET',
            path,
            group_id=group_id,
            user_id=user_id,
            member_id=member_id,
            request_id=request_id,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        group_id: str,
        user_id: str,
        request_id: str,
        member_id: str = '',
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise GatewayError('查询服务尚未配置，请联系管理员设置 IDC 查询网关。')

        headers = {
            'Accept': 'application/json',
            'X-QQ-Group-ID': group_id,
            'X-QQ-User-ID': user_id,
            'X-Request-ID': request_id,
        }
        if member_id:
            headers['X-IDC-Member-ID'] = member_id
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method,
                    f'{self.base_url}{path}',
                    headers=headers,
                    json=json_body,
                    ssl=self.verify_tls,
                ) as response:
                    response_text = await response.text()
                    try:
                        payload = json.loads(response_text) if response_text else {}
                    except json.JSONDecodeError as exc:
                        raise GatewayError('查询服务返回了无法识别的数据。') from exc
                    if not isinstance(payload, dict):
                        raise GatewayError('查询服务返回了无法识别的数据。')
                    if response.status >= 400:
                        message = payload.get('message')
                        raise GatewayError(str(message)[:200] if message else '查询服务暂时不可用，请稍后重试。')
        except asyncio.TimeoutError as exc:
            raise GatewayError('查询超时，请稍后重试。') from exc
        except aiohttp.ClientError as exc:
            raise GatewayError('无法连接查询服务，请稍后重试。') from exc

        if payload.get('ok') is False:
            message = payload.get('message')
            raise GatewayError(str(message)[:200] if message else '查询未成功，请稍后重试。')
        return payload
