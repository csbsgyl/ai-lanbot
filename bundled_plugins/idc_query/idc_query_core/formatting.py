from __future__ import annotations

from typing import Any


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
    '令牌',
    '密码',
    '密钥',
    '凭证',
}
_MAX_LINES = 32
_MAX_CHARS = 1800


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower()
    return normalized in _SENSITIVE_KEYS or any(part in normalized for part in _SENSITIVE_KEYS)


def _safe_value(value: Any) -> str:
    if value is None:
        return '-'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, (str, int, float)):
        return str(value)
    return ''


def _dict_lines(data: dict[str, Any], *, prefix: str = '') -> list[str]:
    lines: list[str] = []
    for key, value in data.items():
        if _is_sensitive_key(key):
            continue
        label = _FIELD_LABELS.get(str(key), str(key))
        if isinstance(value, dict):
            nested = _dict_lines(value, prefix=f'{prefix}{label} / ')
            lines.extend(nested)
        elif isinstance(value, list):
            lines.extend(_list_lines(value, label=label))
        else:
            rendered = _safe_value(value)
            if rendered:
                lines.append(f'{prefix}{label}：{rendered}')
        if len(lines) >= _MAX_LINES:
            break
    return lines


def _list_lines(items: list[Any], *, label: str = '') -> list[str]:
    lines: list[str] = []
    if label:
        lines.append(f'{label}：')
    for index, item in enumerate(items[:10], start=1):
        if isinstance(item, dict):
            fields = []
            for key, value in item.items():
                if _is_sensitive_key(key):
                    continue
                rendered = _safe_value(value)
                if rendered:
                    fields.append(f'{_FIELD_LABELS.get(str(key), str(key))}={rendered}')
            lines.append(f'{index}. ' + '，'.join(fields))
        else:
            lines.append(f'{index}. {_safe_value(item)}')
    return lines


def format_gateway_response(title: str, payload: dict[str, Any]) -> str:
    data = payload.get('data', payload)
    if isinstance(data, dict) and data.get('text'):
        lines = [title, str(data['text'])]
    elif isinstance(data, dict) and isinstance(data.get('fields'), list):
        lines = [title]
        for field in data['fields'][:_MAX_LINES]:
            if not isinstance(field, dict):
                continue
            field_key = field.get('name') or field.get('key') or field.get('label') or ''
            if _is_sensitive_key(field_key):
                continue
            label = field.get('label') or field.get('name') or '信息'
            lines.append(f'{label}：{_safe_value(field.get("value"))}')
    elif isinstance(data, dict):
        lines = [title, *_dict_lines(data)]
    elif isinstance(data, list):
        lines = [title, *_list_lines(data)]
    elif data not in (None, ''):
        lines = [title, str(data)]
    else:
        message = payload.get('message') or '查询成功，但没有可展示的数据。'
        lines = [title, str(message)]

    result = '\n'.join(line for line in lines if line).strip()
    if len(result) > _MAX_CHARS:
        result = result[: _MAX_CHARS - 16].rstrip() + '\n...结果已截断'
    return result
