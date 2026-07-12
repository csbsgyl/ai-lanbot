from __future__ import annotations

import asyncio
import datetime
import json
import math
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from ....utils import paths

if TYPE_CHECKING:
    from ....core import app


DEFAULT_TIMEOUT_SECONDS = 8.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 120.0
MAX_BASE_URL_LENGTH = 2048
MAX_TOKEN_LENGTH = 8192
DEFAULT_REQUESTS_PER_MINUTE = 20
DEFAULT_BIND_ATTEMPTS_PER_10_MINUTES = 5
MIN_RATE_LIMIT = 1
MAX_RATE_LIMIT = 1000
DEFAULT_AUDIT_LIMIT = 100
MAX_AUDIT_LIMIT = 200
AUDIT_BACKUP_COUNT = 3
AUDIT_COMMANDS = {'bind', 'unbind', 'ip', 'protection', 'block', 'traffic', 'businesses', 'tickets', 'balance'}
AUDIT_OUTCOMES = {'success', 'denied', 'rate_limited', 'gateway_error', 'internal_error'}
DEFAULT_BINDINGS_LIMIT = 200
MAX_BINDINGS_LIMIT = 500
MAX_BINDINGS_FILE_BYTES = 5 * 1024 * 1024


class IDCQueryConfigValidationError(ValueError):
    pass


class IDCQueryBindingStateError(RuntimeError):
    pass


class IDCQueryConfigService:
    """Manage the credential file shared with the bundled IDC query plugin."""

    def __init__(self, ap: app.Application) -> None:
        self.ap = ap
        self.config_path = Path(paths.get_data_path('idc-query', 'config.env'))
        self._write_lock = asyncio.Lock()

    async def get_config(self) -> dict[str, Any]:
        return self._public_config(self._read_config())

    async def update_config(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise IDCQueryConfigValidationError('Request body must be a JSON object.')

        allowed_fields = {
            'base_url',
            'token',
            'clear_token',
            'timeout_seconds',
            'verify_tls',
            'requests_per_minute',
            'bind_attempts_per_10_minutes',
        }
        unknown_fields = set(payload) - allowed_fields
        if unknown_fields:
            raise IDCQueryConfigValidationError('Request contains unsupported fields.')

        async with self._write_lock:
            current = self._read_config()
            base_url = current['base_url']
            token = current['token']
            timeout_seconds = current['timeout_seconds']
            verify_tls = current['verify_tls']
            requests_per_minute = current['requests_per_minute']
            bind_attempts_per_10_minutes = current['bind_attempts_per_10_minutes']

            if 'base_url' in payload:
                base_url = self._validate_base_url(payload['base_url'])
            if 'timeout_seconds' in payload:
                timeout_seconds = self._validate_timeout(payload['timeout_seconds'])
            if 'verify_tls' in payload:
                verify_tls = self._validate_boolean(payload['verify_tls'], 'verify_tls')
            if 'requests_per_minute' in payload:
                requests_per_minute = self._validate_rate_limit(
                    payload['requests_per_minute'],
                    'requests_per_minute',
                )
            if 'bind_attempts_per_10_minutes' in payload:
                bind_attempts_per_10_minutes = self._validate_rate_limit(
                    payload['bind_attempts_per_10_minutes'],
                    'bind_attempts_per_10_minutes',
                )

            clear_token = payload.get('clear_token', False)
            clear_token = self._validate_boolean(clear_token, 'clear_token')
            replacement_token = payload.get('token')
            if replacement_token is not None:
                replacement_token = self._validate_token(replacement_token)
            if clear_token and replacement_token:
                raise IDCQueryConfigValidationError('Token cannot be replaced and cleared at the same time.')
            if clear_token:
                token = ''
            elif replacement_token:
                token = replacement_token

            config = {
                'base_url': base_url,
                'token': token,
                'timeout_seconds': timeout_seconds,
                'verify_tls': verify_tls,
                'requests_per_minute': requests_per_minute,
                'bind_attempts_per_10_minutes': bind_attempts_per_10_minutes,
            }
            self._write_config(config)
            return self._public_config(config)

    def _read_config(self) -> dict[str, Any]:
        values: dict[str, str] = {}
        try:
            lines = self.config_path.read_text(encoding='utf-8').splitlines()
        except FileNotFoundError:
            lines = []

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"\'')

        return {
            'base_url': values.get('IDC_QUERY_API_BASE_URL', '').strip().rstrip('/'),
            'token': values.get('IDC_QUERY_API_TOKEN', ''),
            'timeout_seconds': self._parse_timeout(values.get('IDC_QUERY_TIMEOUT_SECONDS')),
            'verify_tls': self._parse_boolean(values.get('IDC_QUERY_VERIFY_TLS'), default=True),
            'requests_per_minute': self._parse_rate_limit(
                values.get('IDC_QUERY_REQUESTS_PER_MINUTE'),
                DEFAULT_REQUESTS_PER_MINUTE,
            ),
            'bind_attempts_per_10_minutes': self._parse_rate_limit(
                values.get('IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES'),
                DEFAULT_BIND_ATTEMPTS_PER_10_MINUTES,
            ),
        }

    def _write_config(self, config: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.config_path.parent, 0o700)
        except OSError:
            pass

        content = (
            f'IDC_QUERY_API_BASE_URL={config["base_url"]}\n'
            f'IDC_QUERY_API_TOKEN={config["token"]}\n'
            f'IDC_QUERY_TIMEOUT_SECONDS={config["timeout_seconds"]:g}\n'
            f'IDC_QUERY_VERIFY_TLS={str(config["verify_tls"]).lower()}\n'
            f'IDC_QUERY_REQUESTS_PER_MINUTE={config["requests_per_minute"]}\n'
            f'IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES={config["bind_attempts_per_10_minutes"]}\n'
        )

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                newline='\n',
                prefix='.config.',
                suffix='.tmp',
                dir=self.config_path.parent,
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                os.chmod(temp_path, 0o600)
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            os.replace(temp_path, self.config_path)
            os.chmod(self.config_path, 0o600)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _public_config(config: dict[str, Any]) -> dict[str, Any]:
        base_url = str(config['base_url'])
        return {
            'base_url': base_url,
            'timeout_seconds': config['timeout_seconds'],
            'verify_tls': config['verify_tls'],
            'token_configured': bool(config['token']),
            'configured': bool(base_url),
            'requests_per_minute': config['requests_per_minute'],
            'bind_attempts_per_10_minutes': config['bind_attempts_per_10_minutes'],
        }

    async def get_audit_events(self, limit: int = DEFAULT_AUDIT_LIMIT) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_AUDIT_LIMIT:
            raise IDCQueryConfigValidationError(f'Audit limit must be between 1 and {MAX_AUDIT_LIMIT}.')

        events = await asyncio.to_thread(self._read_latest_audit_events, limit)
        return {
            'events': events,
            'count': len(events),
            'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    @classmethod
    def _read_latest_audit_events(cls, limit: int) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        audit_path = Path(paths.get_data_path('idc-query', 'audit.jsonl'))
        audit_paths = [audit_path] + [
            audit_path.with_name(f'{audit_path.name}.{index}') for index in range(1, AUDIT_BACKUP_COUNT + 1)
        ]
        for candidate in audit_paths:
            events.extend(cls._read_audit_file(candidate, limit - len(events)))
            if len(events) >= limit:
                break
        return events[:limit]

    @classmethod
    def _read_audit_file(cls, path: Path, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except FileNotFoundError:
            return []

        events = []
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            event = cls._normalize_audit_event(payload)
            if event is not None:
                events.append(event)
            if len(events) >= limit:
                break
        return events

    @classmethod
    def _normalize_audit_event(cls, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        command = cls._limited_text(payload.get('command'), 40)
        outcome = cls._limited_text(payload.get('outcome'), 40)
        if command not in AUDIT_COMMANDS or outcome not in AUDIT_OUTCOMES:
            return None
        duration = payload.get('duration_ms', 0)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            duration = 0
        return {
            'timestamp': cls._limited_text(payload.get('timestamp'), 64),
            'command': command,
            'outcome': outcome,
            'reason': cls._limited_text(payload.get('reason'), 80),
            'group_id': cls._limited_text(payload.get('group_id'), 160),
            'user_id': cls._limited_text(payload.get('user_id'), 160),
            'member_id': cls._limited_text(payload.get('member_id'), 160),
            'request_id': cls._limited_text(payload.get('request_id'), 160),
            'duration_ms': max(0, min(round(duration), 3_600_000)),
        }

    async def get_bindings(self, limit: int = DEFAULT_BINDINGS_LIMIT) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BINDINGS_LIMIT:
            raise IDCQueryConfigValidationError(f'Binding limit must be between 1 and {MAX_BINDINGS_LIMIT}.')

        bindings = await asyncio.to_thread(self._read_bindings)
        selected = bindings[:limit]
        return {
            'bindings': selected,
            'count': len(selected),
            'total': len(bindings),
            'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    @classmethod
    def _read_bindings(cls) -> list[dict[str, str]]:
        binding_path = Path(paths.get_data_path('idc-query', 'bindings.json'))
        try:
            with binding_path.open('rb') as binding_file:
                raw_payload = binding_file.read(MAX_BINDINGS_FILE_BYTES + 1)
        except FileNotFoundError:
            return []

        if len(raw_payload) > MAX_BINDINGS_FILE_BYTES:
            raise IDCQueryBindingStateError('IDC binding state exceeds the supported size.')
        try:
            payload = json.loads(raw_payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise IDCQueryBindingStateError('IDC binding state is invalid.') from exc
        if not isinstance(payload, dict) or payload.get('version') != 1:
            raise IDCQueryBindingStateError('IDC binding state version is unsupported.')
        raw_bindings = payload.get('bindings')
        if not isinstance(raw_bindings, dict):
            raise IDCQueryBindingStateError('IDC binding state is invalid.')

        bindings = []
        for raw_group_id, raw_binding in raw_bindings.items():
            binding = cls._normalize_binding(raw_group_id, raw_binding)
            if binding is not None:
                bindings.append(binding)
        bindings.sort(key=lambda binding: binding['bound_at'], reverse=True)
        return bindings

    @classmethod
    def _normalize_binding(cls, raw_group_id: Any, payload: Any) -> dict[str, str] | None:
        if not isinstance(payload, dict):
            return None
        group_id = cls._limited_text(raw_group_id, 160)
        payload_group_id = cls._limited_text(payload.get('group_id'), 160)
        member_id = cls._limited_text(payload.get('member_id'), 160)
        bound_by = cls._limited_text(payload.get('bound_by'), 160)
        bound_at = cls._limited_text(payload.get('bound_at'), 64)
        if not group_id or payload_group_id != group_id or not member_id or not bound_by or not bound_at:
            return None
        try:
            parsed_bound_at = datetime.datetime.fromisoformat(bound_at.replace('Z', '+00:00'))
        except ValueError:
            return None
        if parsed_bound_at.tzinfo is None:
            return None
        return {
            'group_id': group_id,
            'member_id': member_id,
            'bound_by': bound_by,
            'bound_at': bound_at,
            'member_name': cls._limited_text(payload.get('member_name'), 200),
        }

    @staticmethod
    def _limited_text(value: Any, limit: int) -> str:
        if not isinstance(value, str):
            return ''
        return ''.join(character for character in value if ord(character) >= 32 and ord(character) != 127)[:limit]

    @staticmethod
    def _validate_base_url(value: Any) -> str:
        if not isinstance(value, str):
            raise IDCQueryConfigValidationError('Gateway URL must be a string.')
        base_url = value.strip().rstrip('/')
        if not base_url:
            return ''
        if len(base_url) > MAX_BASE_URL_LENGTH or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127 for character in base_url
        ):
            raise IDCQueryConfigValidationError('Gateway URL is invalid.')

        try:
            parsed = urlsplit(base_url)
            parsed_port = parsed.port
        except ValueError as exc:
            raise IDCQueryConfigValidationError('Gateway URL is invalid.') from exc
        if (
            parsed.scheme.lower() not in {'http', 'https'}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (parsed_port is not None and not 1 <= parsed_port <= 65535)
        ):
            raise IDCQueryConfigValidationError('Gateway URL must be a valid HTTP or HTTPS base URL.')
        return base_url

    @staticmethod
    def _validate_token(value: Any) -> str:
        if not isinstance(value, str):
            raise IDCQueryConfigValidationError('Service token must be a string.')
        token = value.strip()
        if len(token) > MAX_TOKEN_LENGTH or any(ord(character) < 32 or ord(character) == 127 for character in token):
            raise IDCQueryConfigValidationError('Service token is invalid.')
        return token

    @staticmethod
    def _validate_timeout(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IDCQueryConfigValidationError('Timeout must be a number.')
        timeout_seconds = float(value)
        if (
            not math.isfinite(timeout_seconds)
            or timeout_seconds < MIN_TIMEOUT_SECONDS
            or timeout_seconds > MAX_TIMEOUT_SECONDS
        ):
            raise IDCQueryConfigValidationError(
                f'Timeout must be between {MIN_TIMEOUT_SECONDS:g} and {MAX_TIMEOUT_SECONDS:g} seconds.'
            )
        return timeout_seconds

    @staticmethod
    def _validate_boolean(value: Any, field_name: str) -> bool:
        if not isinstance(value, bool):
            raise IDCQueryConfigValidationError(f'{field_name} must be a boolean.')
        return value

    @staticmethod
    def _validate_rate_limit(value: Any, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise IDCQueryConfigValidationError(f'{field_name} must be an integer.')
        if not MIN_RATE_LIMIT <= value <= MAX_RATE_LIMIT:
            raise IDCQueryConfigValidationError(f'{field_name} must be between {MIN_RATE_LIMIT} and {MAX_RATE_LIMIT}.')
        return value

    @staticmethod
    def _parse_timeout(value: str | None) -> float:
        try:
            timeout_seconds = float(value) if value is not None else DEFAULT_TIMEOUT_SECONDS
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_SECONDS
        if not math.isfinite(timeout_seconds) or not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            return DEFAULT_TIMEOUT_SECONDS
        return timeout_seconds

    @staticmethod
    def _parse_boolean(value: str | None, *, default: bool) -> bool:
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
        return default

    @staticmethod
    def _parse_rate_limit(value: str | None, default: int) -> int:
        try:
            parsed = int(value) if value is not None else default
        except (TypeError, ValueError):
            return default
        return parsed if MIN_RATE_LIMIT <= parsed <= MAX_RATE_LIMIT else default
