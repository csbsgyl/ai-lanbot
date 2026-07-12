from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .commands import Command, CommandType, parse_command
from .formatting import format_gateway_response
from .gateway import GatewayError, IDCQueryGateway
from .state import Binding, JsonBindingStore


HELP_TEXT = """IDC 自助查询机器人

帮助 / 菜单
绑定 <会员号> <验证码>
解绑
查IP <IP地址>
查防护 <IP地址>
查封禁 <IP地址>
查流量 <IP地址>
查业务
查工单
查余额

未绑定的群只能查看帮助和执行绑定。"""

_SENSITIVE_COMMANDS = {CommandType.BUSINESSES, CommandType.TICKETS, CommandType.BALANCE}
_QUERY_TITLES = {
    CommandType.IP: 'IP 查询结果',
    CommandType.PROTECTION: '防护查询结果',
    CommandType.BLOCK: '封禁查询结果',
    CommandType.TRAFFIC: '流量查询结果',
    CommandType.BUSINESSES: '业务查询结果',
    CommandType.TICKETS: '最近工单',
    CommandType.BALANCE: '账户余额',
}


@dataclass(frozen=True)
class HandleResult:
    handled: bool
    reply: str | None = None


class IDCQueryService:
    def __init__(
        self,
        *,
        store: JsonBindingStore,
        gateway: IDCQueryGateway,
        exclusive_mode: bool,
        sensitive_binder_only: bool,
        dedupe_ttl_seconds: float = 300,
    ):
        self.store = store
        self.gateway = gateway
        self.exclusive_mode = exclusive_mode
        self.sensitive_binder_only = sensitive_binder_only
        self.dedupe_ttl_seconds = dedupe_ttl_seconds
        self._seen_messages: dict[str, float] = {}
        self._dedupe_lock = asyncio.Lock()
        self._binding_locks: dict[str, asyncio.Lock] = {}

    async def initialize(self) -> None:
        await self.store.load()

    async def handle(
        self,
        *,
        text: str,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> HandleResult:
        parsed = parse_command(text)
        binding = await self.store.get(group_id)

        if parsed.command is None and parsed.error is None and not self.exclusive_mode:
            return HandleResult(False)
        if await self._is_duplicate(message_id):
            return HandleResult(True)

        if parsed.command is None and parsed.error is None:
            reply = (
                HELP_TEXT if binding else '当前群尚未绑定会员。\n请发送：绑定 <会员号> <验证码>\n发送“帮助”查看菜单。'
            )
            return HandleResult(True, reply)

        if parsed.error:
            return HandleResult(True, parsed.error)

        command = parsed.command
        if command is None:
            return HandleResult(False)
        if command.kind == CommandType.HELP:
            return HandleResult(True, HELP_TEXT)

        try:
            if command.kind == CommandType.BIND:
                async with self._binding_locks.setdefault(group_id, asyncio.Lock()):
                    current_binding = await self.store.get(group_id)
                    return await self._bind(command, current_binding, group_id, user_id, message_id)
            if command.kind == CommandType.UNBIND:
                async with self._binding_locks.setdefault(group_id, asyncio.Lock()):
                    current_binding = await self.store.get(group_id)
                    return await self._unbind(current_binding, group_id, user_id, message_id)
            if binding is None:
                return HandleResult(
                    True,
                    '当前群尚未绑定会员，只能查看帮助或执行绑定。\n请发送：绑定 <会员号> <验证码>',
                )
            if self.sensitive_binder_only and command.kind in _SENSITIVE_COMMANDS and user_id != binding.bound_by:
                return HandleResult(True, '该指令包含敏感账户信息，仅执行群绑定的成员可以查询。')
            return await self._query(command, binding, group_id, user_id, message_id)
        except GatewayError as exc:
            return HandleResult(True, exc.public_message)

    async def _bind(
        self,
        command: Command,
        binding: Binding | None,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> HandleResult:
        requested_member_id = command.arguments['member_id']
        if binding is not None:
            if binding.member_id == requested_member_id:
                return HandleResult(True, f'当前群已绑定会员 {binding.member_id}，无需重复绑定。')
            return HandleResult(True, f'当前群已绑定会员 {binding.member_id}，请先解绑后再更换。')

        verified = await self.gateway.verify_binding(
            group_id=group_id,
            user_id=user_id,
            member_id=requested_member_id,
            verification_code=command.arguments['verification_code'],
            request_id=message_id,
        )
        member_id = str(verified.get('member_id') or '').strip()
        if member_id != requested_member_id:
            raise GatewayError('绑定验证结果异常，请联系管理员检查 IDC 查询网关。')
        member_name = str(verified.get('member_name') or '')
        await self.store.put(
            group_id=group_id,
            member_id=member_id,
            bound_by=user_id,
            member_name=member_name,
        )
        display_name = f'（{member_name}）' if member_name else ''
        return HandleResult(True, f'绑定成功：会员 {member_id}{display_name}')

    async def _unbind(
        self,
        binding: Binding | None,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> HandleResult:
        if binding is None:
            return HandleResult(True, '当前群尚未绑定会员。')
        if user_id != binding.bound_by:
            return HandleResult(True, '只有执行群绑定的成员可以解绑。')

        await self.gateway.unbind(
            group_id=group_id,
            user_id=user_id,
            member_id=binding.member_id,
            request_id=message_id,
        )
        await self.store.remove(group_id)
        return HandleResult(True, f'已解除当前群与会员 {binding.member_id} 的绑定。')

    async def _query(
        self,
        command: Command,
        binding: Binding,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> HandleResult:
        payload = await self.gateway.query(
            command_type=command.kind,
            arguments=command.arguments,
            group_id=group_id,
            user_id=user_id,
            member_id=binding.member_id,
            request_id=message_id,
        )
        return HandleResult(True, format_gateway_response(_QUERY_TITLES[command.kind], payload))

    async def _is_duplicate(self, message_id: str) -> bool:
        if not message_id:
            return False
        now = time.monotonic()
        async with self._dedupe_lock:
            expired = [key for key, expires_at in self._seen_messages.items() if expires_at <= now]
            for key in expired:
                self._seen_messages.pop(key, None)
            if message_id in self._seen_messages:
                return True
            self._seen_messages[message_id] = now + self.dedupe_ttl_seconds
            return False
