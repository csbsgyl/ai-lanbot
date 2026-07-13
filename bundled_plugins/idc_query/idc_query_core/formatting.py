from __future__ import annotations

from typing import Any
import unicodedata

from .text import is_unsafe_character


_FIELD_LABELS = {
    'ip': 'IP',
    'asset': '资产',
    'asset_name': '资产名称',
    'room': '机房',
    'line': '线路',
    'business': '业务',
    'business_name': '业务名称',
    'protection_status': '防护状态',
    'scrubbing_status': '牵引状态',
    'blackhole_status': '黑洞状态',
    'block_status': '封禁状态',
    'block_reason': '封禁原因',
    'release_at': '预计解除时间',
    'current_traffic': '当前流量',
    'peak_traffic': '峰值流量',
    'abnormal_status': '异常状态',
    'ticket_id': '工单号',
    'ticket_status': '工单状态',
    'balance': '余额',
    'account_status': '账户状态',
    'updated_at': '数据更新时间',
}
_SENSITIVE_KEYS = {
    'token',
    'secret',
    'password',
    'api_key',
    'access_key',
    'private_key',
    'credential',
    'authorization',
    'bearer',
    'cookie',
    '令牌',
    '密码',
    '密钥',
    '凭证',
}
_NORMALIZED_SENSITIVE_KEYS = {
    ''.join(character for character in unicodedata.normalize('NFKC', key).casefold() if character.isalnum())
    for key in _SENSITIVE_KEYS
}
_MAX_LINES = 32
_MAX_CHARS = 1800
_MAX_DEPTH = 4
_MAX_LABEL_CHARS = 80
_MAX_VALUE_CHARS = 500


def _is_sensitive_key(key: object) -> bool:
    normalized = ''.join(
        character
        for character in unicodedata.normalize('NFKC', str(key)).casefold()
        if character.isalnum() and not is_unsafe_character(character)
    )
    return any(part in normalized for part in _NORMALIZED_SENSITIVE_KEYS)


def _safe_inline(value: object, limit: int) -> str:
    text = str(value)
    text = ''.join(' ' if is_unsafe_character(character) else character for character in text)
    return ' '.join(text.split())[:limit]


def _safe_block(value: str) -> str:
    normalized = value.replace('\r\n', '\n').replace('\r', '\n')
    lines = []
    for line in normalized.split('\n')[:_MAX_LINES]:
        safe_line = ''.join(' ' if is_unsafe_character(character) else character for character in line)
        lines.append(safe_line[:_MAX_VALUE_CHARS].rstrip())
    return '\n'.join(lines).strip()


def _safe_label(value: object, default: str = '信息') -> str:
    rendered = _safe_inline(value, _MAX_LABEL_CHARS)
    return rendered or default


def _safe_value(value: Any) -> str:
    if value is None:
        return '-'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, (str, int, float)):
        return _safe_inline(value, _MAX_VALUE_CHARS)
    return ''


def _dict_lines(data: dict[str, Any], *, prefix: str = '', depth: int = 0) -> list[str]:
    if depth >= _MAX_DEPTH:
        return []
    lines: list[str] = []
    for key, value in data.items():
        if _is_sensitive_key(key):
            continue
        label = _safe_label(_FIELD_LABELS.get(str(key), key))
        if isinstance(value, dict):
            nested = _dict_lines(value, prefix=f'{prefix}{label} / ', depth=depth + 1)
            lines.extend(nested)
        elif isinstance(value, list):
            lines.extend(_list_lines(value, label=f'{prefix}{label}', depth=depth + 1))
        else:
            rendered = _safe_value(value)
            if rendered:
                lines.append(f'{prefix}{label}：{rendered}')
        if len(lines) >= _MAX_LINES:
            break
    return lines


def _list_lines(items: list[Any], *, label: str = '', depth: int = 0) -> list[str]:
    if depth >= _MAX_DEPTH:
        return []
    lines: list[str] = []
    if label:
        lines.append(f'{_safe_label(label)}：')
    for index, item in enumerate(items[:10], start=1):
        if isinstance(item, dict):
            fields = []
            for key, value in item.items():
                if _is_sensitive_key(key):
                    continue
                rendered = _safe_value(value)
                if rendered:
                    field_label = _safe_label(_FIELD_LABELS.get(str(key), key))
                    fields.append(f'{field_label}={rendered}')
            lines.append(f'{index}. ' + '，'.join(fields))
        elif not isinstance(item, (dict, list)):
            rendered = _safe_value(item)
            if rendered:
                lines.append(f'{index}. {rendered}')
        if len(lines) >= _MAX_LINES:
            break
    return lines


def format_gateway_response(title: str, payload: dict[str, Any]) -> str:
    data = payload.get('data') if 'data' in payload or 'ok' in payload else payload
    if isinstance(data, dict) and isinstance(data.get('text'), str) and data['text']:
        lines = [title, _safe_block(data['text'])]
    elif isinstance(data, dict) and isinstance(data.get('fields'), list):
        lines = [title]
        for field in data['fields'][:_MAX_LINES]:
            if not isinstance(field, dict):
                continue
            field_keys = [field.get('name'), field.get('key'), field.get('label')]
            if any(_is_sensitive_key(field_key) for field_key in field_keys if field_key):
                continue
            label = _safe_label(field.get('label') or field.get('name') or field.get('key') or '信息')
            rendered = _safe_value(field.get('value'))
            if rendered:
                lines.append(f'{label}：{rendered}')
    elif isinstance(data, dict):
        rendered = _dict_lines(data)
        lines = [title, *rendered] if rendered else [title, '查询成功，但没有可展示的数据。']
    elif isinstance(data, list):
        rendered = _list_lines(data)
        lines = [title, *rendered] if rendered else [title, '查询成功，但没有可展示的数据。']
    elif data not in (None, ''):
        lines = [title, _safe_value(data)]
    else:
        lines = [title, '查询成功，但没有可展示的数据。']

    result_lines: list[str] = []
    for line in lines:
        result_lines.extend(part for part in line.splitlines() if part)
        if len(result_lines) >= _MAX_LINES:
            break
    result = '\n'.join(result_lines[:_MAX_LINES]).strip()
    if len(result) > _MAX_CHARS:
        result = result[: _MAX_CHARS - 12].rstrip() + '...结果已截断'
    return result
