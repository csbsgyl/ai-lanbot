from __future__ import annotations

import asyncio
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


class IDCQueryConfigValidationError(ValueError):
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

            if 'base_url' in payload:
                base_url = self._validate_base_url(payload['base_url'])
            if 'timeout_seconds' in payload:
                timeout_seconds = self._validate_timeout(payload['timeout_seconds'])
            if 'verify_tls' in payload:
                verify_tls = self._validate_boolean(payload['verify_tls'], 'verify_tls')

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
        }

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
