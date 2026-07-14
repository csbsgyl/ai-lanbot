from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .audit import JsonlAuditLog
from .commands import Command, CommandType, parse_command
from .formatting import format_gateway_response
from .gateway import GatewayError, IDCQueryGateway
from .rate_limit import SlidingWindowRateLimiter
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
DEFAULT_MAX_DEDUPE_MESSAGES = 4096
DEFAULT_BINDING_LOCK_STRIPES = 64
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


@dataclass(frozen=True)
class _OperationResult:
    result: HandleResult
    outcome: str
    reason: str
    member_id: str = ''


class IDCQueryService:
    def __init__(
        self,
        *,
        store: JsonBindingStore,
        gateway: IDCQueryGateway,
        exclusive_mode: bool,
        sensitive_binder_only: bool,
        audit_log: JsonlAuditLog | None = None,
        requests_per_minute: int = 20,
        bind_attempts_per_10_minutes: int = 5,
        dedupe_ttl_seconds: float = 300,
        max_dedupe_messages: int = DEFAULT_MAX_DEDUPE_MESSAGES,
        binding_lock_stripes: int = DEFAULT_BINDING_LOCK_STRIPES,
    ):
        self.store = store
        self.gateway = gateway
        self.exclusive_mode = exclusive_mode
        self.sensitive_binder_only = sensitive_binder_only
        self.audit_log = audit_log
        self.dedupe_ttl_seconds = max(1.0, float(dedupe_ttl_seconds))
        self.max_dedupe_messages = max(1, int(max_dedupe_messages))
        self._seen_messages: dict[str, float] = {}
        self._dedupe_lock = asyncio.Lock()
        lock_count = max(1, int(binding_lock_stripes))
        self._binding_locks = tuple(asyncio.Lock() for _ in range(lock_count))
        self.configure_rate_limits(
            requests_per_minute=requests_per_minute,
            bind_attempts_per_10_minutes=bind_attempts_per_10_minutes,
        )

    def configure_rate_limits(
        self,
        *,
        requests_per_minute: int,
        bind_attempts_per_10_minutes: int,
    ) -> None:
        self.requests_per_minute = max(1, int(requests_per_minute))
        self.bind_attempts_per_10_minutes = max(1, int(bind_attempts_per_10_minutes))
        self._query_rate_limiter = SlidingWindowRateLimiter(
            limit=self.requests_per_minute,
            window_seconds=60,
        )
        self._bind_rate_limiter = SlidingWindowRateLimiter(
            limit=self.bind_attempts_per_10_minutes,
            window_seconds=600,
        )

    async def initialize(self) -> None:
        await self.store.load()

    def _binding_lock(self, group_id: str) -> asyncio.Lock:
        return self._binding_locks[hash(group_id) % len(self._binding_locks)]

    async def handle(
        self,
        *,
        text: str,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> HandleResult:
        started_at = time.monotonic()
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

        member_id = binding.member_id if binding else command.arguments.get('member_id', '')
        rate_limiter = None
        if command.kind == CommandType.BIND:
            rate_limiter = self._bind_rate_limiter
        elif command.kind != CommandType.UNBIND:
            rate_limiter = self._query_rate_limiter

        if rate_limiter is not None:
            rate_decision = await rate_limiter.acquire(f'{group_id}:{user_id}')
            if not rate_decision.allowed:
                reply = (
                    f'绑定尝试过于频繁，请在 {rate_decision.retry_after_seconds} 秒后重试。'
                    if command.kind == CommandType.BIND
                    else f'查询过于频繁，请在 {rate_decision.retry_after_seconds} 秒后重试。'
                )
                operation = _OperationResult(HandleResult(True, reply), 'rate_limited', 'rate_limit', member_id)
                await self._audit(command, operation, group_id, user_id, message_id, started_at)
                return operation.result

        try:
            if command.kind == CommandType.BIND:
                async with self._binding_lock(group_id):
                    current_binding = await self.store.get(group_id)
                    operation = await self._bind(command, current_binding, group_id, user_id, message_id)
            elif command.kind == CommandType.UNBIND:
                async with self._binding_lock(group_id):
                    current_binding = await self.store.get(group_id)
                    operation = await self._unbind(current_binding, group_id, user_id, message_id)
            elif binding is None:
                operation = _OperationResult(
                    HandleResult(
                        True,
                        '当前群尚未绑定会员，只能查看帮助或执行绑定。\n请发送：绑定 <会员号> <验证码>',
                    ),
                    'denied',
                    'not_bound',
                )
            elif self.sensitive_binder_only and command.kind in _SENSITIVE_COMMANDS and user_id != binding.bound_by:
                operation = _OperationResult(
                    HandleResult(True, '该指令包含敏感账户信息，仅执行群绑定的成员可以查询。'),
                    'denied',
                    'binder_required',
                    binding.member_id,
                )
            else:
                operation = await self._query(command, binding, group_id, user_id, message_id)
        except GatewayError as exc:
            operation = _OperationResult(
                HandleResult(True, exc.public_message),
                'gateway_error',
                'gateway_error',
                member_id,
            )
        except Exception:
            operation = _OperationResult(HandleResult(True), 'internal_error', 'internal_error', member_id)
            await self._audit(command, operation, group_id, user_id, message_id, started_at)
            raise

        await self._audit(command, operation, group_id, user_id, message_id, started_at)
        return operation.result

    async def _bind(
        self,
        command: Command,
        binding: Binding | None,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> _OperationResult:
        requested_member_id = command.arguments['member_id']
        if binding is not None:
            if binding.member_id == requested_member_id:
                return _OperationResult(
                    HandleResult(True, f'当前群已绑定会员 {binding.member_id}，无需重复绑定。'),
                    'denied',
                    'already_bound',
                    binding.member_id,
                )
            return _OperationResult(
                HandleResult(True, f'当前群已绑定会员 {binding.member_id}，请先解绑后再更换。'),
                'denied',
                'binding_conflict',
                binding.member_id,
            )

        verified = await self.gateway.verify_binding(
            group_id=group_id,
            user_id=user_id,
            member_id=requested_member_id,
            verification_code=command.arguments['verification_code'],
            request_id=message_id,
        )
        raw_member_id = verified.get('member_id')
        if not isinstance(raw_member_id, str) or raw_member_id.strip() != raw_member_id:
            raise GatewayError('绑定验证结果异常，请联系管理员检查 IDC 查询网关。')
        if raw_member_id != requested_member_id:
            raise GatewayError('绑定验证结果异常，请联系管理员检查 IDC 查询网关。')
        raw_member_name = verified.get('member_name', '')
        if raw_member_name is None:
            raw_member_name = ''
        if not isinstance(raw_member_name, str):
            raise GatewayError('绑定验证结果异常，请联系管理员检查 IDC 查询网关。')
        binding = await self.store.put(
            group_id=group_id,
            member_id=raw_member_id,
            bound_by=user_id,
            member_name=raw_member_name,
        )
        member_id = binding.member_id
        member_name = binding.member_name
        display_name = f'（{member_name}）' if member_name else ''
        return _OperationResult(
            HandleResult(True, f'绑定成功：会员 {member_id}{display_name}'),
            'success',
            'bound',
            member_id,
        )

    async def _unbind(
        self,
        binding: Binding | None,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> _OperationResult:
        if binding is None:
            return _OperationResult(HandleResult(True, '当前群尚未绑定会员。'), 'denied', 'not_bound')
        if user_id != binding.bound_by:
            return _OperationResult(
                HandleResult(True, '只有执行群绑定的成员可以解绑。'),
                'denied',
                'binder_required',
                binding.member_id,
            )

        await self.gateway.unbind(
            group_id=group_id,
            user_id=user_id,
            member_id=binding.member_id,
            request_id=message_id,
        )
        await self.store.remove(group_id)
        return _OperationResult(
            HandleResult(True, f'已解除当前群与会员 {binding.member_id} 的绑定。'),
            'success',
            'unbound',
            binding.member_id,
        )

    async def _query(
        self,
        command: Command,
        binding: Binding,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> _OperationResult:
        payload = await self.gateway.query(
            command_type=command.kind,
            arguments=command.arguments,
            group_id=group_id,
            user_id=user_id,
            member_id=binding.member_id,
            request_id=message_id,
        )
        return _OperationResult(
            HandleResult(True, format_gateway_response(_QUERY_TITLES[command.kind], payload)),
            'success',
            'queried',
            binding.member_id,
        )

    async def _audit(
        self,
        command: Command,
        operation: _OperationResult,
        group_id: str,
        user_id: str,
        message_id: str,
        started_at: float,
    ) -> None:
        if self.audit_log is None:
            return
        try:
            await self.audit_log.append(
                command=command.kind.value,
                outcome=operation.outcome,
                reason=operation.reason,
                group_id=group_id,
                user_id=user_id,
                member_id=operation.member_id,
                request_id=message_id,
                duration_ms=round((time.monotonic() - started_at) * 1000),
            )
        except (OSError, TypeError, UnicodeError, ValueError):
            return

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
            while len(self._seen_messages) >= self.max_dedupe_messages:
                self._seen_messages.pop(next(iter(self._seen_messages)))
            self._seen_messages[message_id] = now + self.dedupe_ttl_seconds
            return False
