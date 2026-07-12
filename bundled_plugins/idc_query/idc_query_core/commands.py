from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from enum import Enum


class CommandType(str, Enum):
    HELP = 'help'
    BIND = 'bind'
    UNBIND = 'unbind'
    IP = 'ip'
    PROTECTION = 'protection'
    BLOCK = 'block'
    TRAFFIC = 'traffic'
    BUSINESSES = 'businesses'
    TICKETS = 'tickets'
    BALANCE = 'balance'


@dataclass(frozen=True)
class Command:
    kind: CommandType
    arguments: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParseResult:
    command: Command | None = None
    error: str | None = None


_BIND_PATTERN = re.compile(r'^绑定\s+([A-Za-z0-9][A-Za-z0-9_.-]{1,63})\s+(\d{4,8})$')
_BOT_MENTION_PATTERN = re.compile(r'<@![^>]+>')
_IP_PATTERNS = (
    (re.compile(r'^查\s*IP\s+(\S+)$', re.IGNORECASE), CommandType.IP),
    (re.compile(r'^查防护\s+(\S+)$'), CommandType.PROTECTION),
    (re.compile(r'^查封禁\s+(\S+)$'), CommandType.BLOCK),
    (re.compile(r'^查流量\s+(\S+)$'), CommandType.TRAFFIC),
)
_NO_ARGUMENT_COMMANDS = {
    '帮助': CommandType.HELP,
    '菜单': CommandType.HELP,
    '解绑': CommandType.UNBIND,
    '查业务': CommandType.BUSINESSES,
    '查工单': CommandType.TICKETS,
    '查余额': CommandType.BALANCE,
}


def normalize_command_text(text: str) -> str:
    without_bot_mention = _BOT_MENTION_PATTERN.sub(' ', text)
    return re.sub(r'\s+', ' ', without_bot_mention.replace('\u3000', ' ')).strip()


def parse_command(text: str) -> ParseResult:
    normalized = normalize_command_text(text)
    if not normalized:
        return ParseResult()

    no_argument = _NO_ARGUMENT_COMMANDS.get(normalized)
    if no_argument is not None:
        return ParseResult(Command(no_argument))

    binding = _BIND_PATTERN.fullmatch(normalized)
    if binding:
        return ParseResult(
            Command(
                CommandType.BIND,
                {'member_id': binding.group(1), 'verification_code': binding.group(2)},
            )
        )
    if normalized.startswith('绑定'):
        return ParseResult(error='格式错误，请发送：绑定 <会员号> <验证码>')

    for pattern, command_type in _IP_PATTERNS:
        match = pattern.fullmatch(normalized)
        if not match:
            continue
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            return ParseResult(error='IP 地址格式不正确，请检查后重试。')
        return ParseResult(Command(command_type, {'ip': address.compressed}))

    if normalized.lower().startswith('查ip'):
        return ParseResult(error='格式错误，请发送：查IP <IP地址>')
    for prefix in ('查防护', '查封禁', '查流量'):
        if normalized.startswith(prefix):
            return ParseResult(error=f'格式错误，请发送：{prefix} <IP地址>')

    return ParseResult()
