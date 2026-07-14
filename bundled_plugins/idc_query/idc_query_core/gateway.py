from __future__ import annotations

import asyncio
import ipaddress
import json
import math
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp

from .commands import CommandType
from .text import is_unsafe_character


MAX_RESPONSE_BYTES = 512 * 1024
MAX_IDENTITY_LENGTH = 160
MAX_TOKEN_LENGTH = 8192
MAX_TIMEOUT_SECONDS = 120.0
MAX_JSON_DEPTH = 16
MAX_JSON_ITEMS = 4096
DEFAULT_MAX_CONCURRENT_REQUESTS = 32
MAX_CONCURRENT_REQUESTS = 256
_READ_CHUNK_BYTES = 64 * 1024
GATEWAY_BUSY_MESSAGE = '查询服务当前繁忙，请稍后重试。'

_ERROR_CODE_MESSAGES = {
    'INVALID_VERIFICATION_CODE': '绑定验证未通过，请检查会员号和验证码后重试。',
    'BINDING_VERIFICATION_FAILED': '绑定验证未通过，请检查会员号和验证码后重试。',
    'MEMBER_NOT_FOUND': '绑定验证未通过，请检查会员号和验证码后重试。',
    'AUTHENTICATION_FAILED': '查询服务鉴权失败，请联系管理员检查网关服务令牌。',
    'SERVICE_TOKEN_INVALID': '查询服务鉴权失败，请联系管理员检查网关服务令牌。',
    'UNAUTHORIZED': '当前会员无权执行该操作，请联系管理员确认权限。',
    'FORBIDDEN': '当前会员无权执行该操作，请联系管理员确认权限。',
    'NOT_FOUND': '未找到对应数据。',
    'CONFLICT': '当前数据状态已变化，请稍后重试。',
    'RATE_LIMITED': '查询请求过于频繁，请稍后重试。',
    'UPSTREAM_UNAVAILABLE': '查询服务暂时不可用，请稍后重试。',
}


def _reject_json_constant(_value: str) -> None:
    raise ValueError('invalid JSON constant')


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
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
    ):
        self.base_url = base_url.rstrip('/') if isinstance(base_url, str) else base_url
        self.token = token
        try:
            parsed_timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            parsed_timeout = 8.0
        if not math.isfinite(parsed_timeout):
            parsed_timeout = 8.0
        self.timeout_seconds = max(1.0, min(parsed_timeout, MAX_TIMEOUT_SECONDS))
        self.verify_tls = verify_tls
        try:
            parsed_concurrency = int(max_concurrent_requests)
        except (TypeError, ValueError):
            parsed_concurrency = DEFAULT_MAX_CONCURRENT_REQUESTS
        self.max_concurrent_requests = max(1, min(parsed_concurrency, MAX_CONCURRENT_REQUESTS))
        self._request_slots = asyncio.BoundedSemaphore(self.max_concurrent_requests)

    async def verify_binding(
        self,
        *,
        group_id: str,
        user_id: str,
        member_id: str,
        verification_code: str,
        request_id: str,
    ) -> dict[str, Any]:
        safe_group_id = self._identity(group_id)
        safe_user_id = self._identity(user_id)
        safe_request_id = self._identity(request_id)
        safe_member_id = self._identity(member_id)
        if not 2 <= len(safe_member_id) <= 64:
            raise GatewayError('请求身份信息无效，请稍后重试或联系管理员。')
        if (
            not isinstance(verification_code, str)
            or not verification_code.isascii()
            or not verification_code.isdigit()
            or not 4 <= len(verification_code) <= 8
        ):
            raise GatewayError('绑定验证码格式无效，请重新发送绑定指令。')
        payload = await self._request(
            'POST',
            '/v1/bindings/verify',
            operation='binding',
            group_id=safe_group_id,
            user_id=safe_user_id,
            request_id=safe_request_id,
            json_body={
                'group_id': safe_group_id,
                'user_id': safe_user_id,
                'member_id': safe_member_id,
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
        safe_group_id = self._identity(group_id)
        await self._request(
            'DELETE',
            f'/v1/bindings/{quote(safe_group_id, safe="")}',
            operation='unbind',
            group_id=safe_group_id,
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
        if command_type not in self._QUERY_PATHS or not isinstance(arguments, dict):
            raise GatewayError('查询条件无效，请检查后重试。')
        path_template = self._QUERY_PATHS[command_type]
        ip_argument = arguments.get('ip', '')
        if '{ip}' in path_template:
            if not isinstance(ip_argument, str) or not ip_argument:
                raise GatewayError('查询条件无效，请检查后重试。')
            try:
                ip_argument = ipaddress.ip_address(ip_argument).compressed
            except ValueError as exc:
                raise GatewayError('查询条件无效，请检查后重试。') from exc
        path = path_template.format(ip=quote(ip_argument, safe=':'))
        return await self._request(
            'GET',
            path,
            operation='query',
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
        operation: str,
        group_id: str,
        user_id: str,
        request_id: str,
        member_id: str = '',
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(self.base_url, str):
            raise GatewayError('查询网关配置无效，请联系管理员检查。')
        if not self.base_url:
            raise GatewayError('查询服务尚未配置，请联系管理员设置 IDC 查询网关。')
        if not isinstance(self.verify_tls, bool):
            raise GatewayError('查询网关 TLS 配置无效，请联系管理员检查。')

        request_url = self._request_url(path)
        safe_group_id = self._identity(group_id)
        safe_user_id = self._identity(user_id)
        safe_request_id = self._identity(request_id)
        safe_member_id = self._identity(member_id) if member_id else ''
        safe_token = self._token()

        headers = {
            'Accept': 'application/json',
            'X-QQ-Group-ID': safe_group_id,
            'X-QQ-User-ID': safe_user_id,
            'X-Request-ID': safe_request_id,
        }
        if safe_member_id:
            headers['X-IDC-Member-ID'] = safe_member_id
        if safe_token:
            headers['Authorization'] = f'Bearer {safe_token}'

        request_deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        try:
            await asyncio.wait_for(self._request_slots.acquire(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise GatewayError(GATEWAY_BUSY_MESSAGE) from exc

        try:
            remaining_seconds = request_deadline - asyncio.get_running_loop().time()
            if remaining_seconds <= 0:
                raise GatewayError(GATEWAY_BUSY_MESSAGE)
            timeout = aiohttp.ClientTimeout(total=remaining_seconds)
            try:
                async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                    async with session.request(
                        method,
                        request_url,
                        headers=headers,
                        json=json_body,
                        ssl=self.verify_tls,
                        allow_redirects=False,
                    ) as response:
                        if response.status < 200 or 300 <= response.status < 400:
                            raise GatewayError('查询网关返回了重定向或异常状态，请联系管理员检查网关地址。')
                        if response.status >= 400:
                            raise GatewayError(self._http_error_message(response.status, operation))
                        response_bytes = await self._read_response(response)
                        payload = self._parse_response(response_bytes)
            except asyncio.TimeoutError as exc:
                raise GatewayError('查询超时，请稍后重试。') from exc
            except aiohttp.ClientError as exc:
                raise GatewayError('无法连接查询服务，请稍后重试。') from exc
        finally:
            self._request_slots.release()

        if not payload and operation == 'unbind':
            return payload
        if 'ok' not in payload or not isinstance(payload['ok'], bool):
            raise GatewayError('查询服务返回了无法识别的数据。')
        if payload.get('ok') is False:
            raise GatewayError(self._payload_error_message(payload, operation))
        return payload

    def _request_url(self, path: str) -> str:
        try:
            parsed = urlsplit(self.base_url)
            parsed.port
        except (TypeError, ValueError) as exc:
            raise GatewayError('查询网关配置无效，请联系管理员检查。') from exc
        if (
            parsed.scheme.lower() not in {'http', 'https'}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(character.isspace() or is_unsafe_character(character) for character in self.base_url)
        ):
            raise GatewayError('查询网关配置无效，请联系管理员检查。')
        return f'{self.base_url}{path}'

    @staticmethod
    def _identity(value: Any) -> str:
        if not isinstance(value, str):
            raise GatewayError('请求身份信息无效，请稍后重试或联系管理员。')
        text = value.strip()
        if (
            not text
            or text != value
            or len(text) > MAX_IDENTITY_LENGTH
            or any(not 33 <= ord(character) <= 126 for character in text)
        ):
            raise GatewayError('请求身份信息无效，请稍后重试或联系管理员。')
        return text

    def _token(self) -> str:
        if not isinstance(self.token, str):
            raise GatewayError('查询网关服务令牌配置无效，请联系管理员检查。')
        token = self.token.strip()
        if (
            token != self.token
            or len(token) > MAX_TOKEN_LENGTH
            or any(not 33 <= ord(character) <= 126 for character in token)
        ):
            raise GatewayError('查询网关服务令牌配置无效，请联系管理员检查。')
        return token

    @staticmethod
    async def _read_response(response: aiohttp.ClientResponse) -> bytes:
        if response.content_length is not None and response.content_length > MAX_RESPONSE_BYTES:
            raise GatewayError('查询服务返回的数据过大，请联系管理员检查网关。')

        chunks: list[bytes] = []
        total_bytes = 0
        async for chunk in response.content.iter_chunked(_READ_CHUNK_BYTES):
            total_bytes += len(chunk)
            if total_bytes > MAX_RESPONSE_BYTES:
                raise GatewayError('查询服务返回的数据过大，请联系管理员检查网关。')
            chunks.append(chunk)
        return b''.join(chunks)

    @staticmethod
    def _parse_response(response_bytes: bytes) -> dict[str, Any]:
        if not response_bytes:
            return {}
        try:
            response_text = response_bytes.decode('utf-8')
            payload = json.loads(
                response_text,
                parse_constant=_reject_json_constant,
            )
        except RecursionError as exc:
            raise GatewayError('查询服务返回的数据结构过于复杂。') from exc
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise GatewayError('查询服务返回了无法识别的数据。') from exc
        if not isinstance(payload, dict):
            raise GatewayError('查询服务返回了无法识别的数据。')
        IDCQueryGateway._validate_payload_complexity(payload)
        return payload

    @staticmethod
    def _validate_payload_complexity(payload: dict[str, Any]) -> None:
        stack: list[tuple[Any, int]] = [(payload, 0)]
        item_count = 0
        while stack:
            value, depth = stack.pop()
            if depth > MAX_JSON_DEPTH:
                raise GatewayError('查询服务返回的数据结构过于复杂。')
            if isinstance(value, dict):
                item_count += len(value)
                stack.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                item_count += len(value)
                stack.extend((item, depth + 1) for item in value)
            elif isinstance(value, float) and not math.isfinite(value):
                raise GatewayError('查询服务返回了无法识别的数据。')
            if item_count > MAX_JSON_ITEMS:
                raise GatewayError('查询服务返回的数据结构过于复杂。')

    @staticmethod
    def _payload_error_message(payload: dict[str, Any], operation: str) -> str:
        error = payload.get('error')
        raw_code = error.get('code') if isinstance(error, dict) else payload.get('code')
        code = str(raw_code or '').strip().upper()
        if code == 'RATE_LIMITED' and operation == 'binding':
            return '绑定验证请求过于频繁，请稍后重试。'
        if code in _ERROR_CODE_MESSAGES:
            return _ERROR_CODE_MESSAGES[code]
        return IDCQueryGateway._operation_error_message(operation)

    @staticmethod
    def _http_error_message(status: int, operation: str) -> str:
        if status == 429:
            return '绑定验证请求过于频繁，请稍后重试。' if operation == 'binding' else '查询请求过于频繁，请稍后重试。'
        if operation == 'binding' and status in {400, 404, 409, 422}:
            return '绑定验证未通过，请检查会员号和验证码后重试。'
        if status == 401:
            return '查询服务鉴权失败，请联系管理员检查网关服务令牌。'
        if status == 403:
            return '当前会员无权执行该操作，请联系管理员确认权限。'
        if status == 404:
            return '未找到对应数据。'
        if status == 409:
            return '当前数据状态已变化，请稍后重试。'
        if status in {400, 422}:
            return '查询条件无效，请检查后重试。'
        return '查询服务暂时不可用，请稍后重试。'

    @staticmethod
    def _operation_error_message(operation: str) -> str:
        if operation == 'binding':
            return '绑定验证未通过，请检查会员号和验证码后重试。'
        if operation == 'unbind':
            return '解绑未成功，请稍后重试或联系管理员。'
        return '查询未成功，请稍后重试。'
