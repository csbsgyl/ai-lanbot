from __future__ import annotations

import asyncio
import os
from pathlib import Path

from langbot_plugin.api.definition.plugin import BasePlugin

from idc_query_core.gateway import IDCQueryGateway
from idc_query_core.service import HandleResult, IDCQueryService
from idc_query_core.state import JsonBindingStore


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    return default


def _read_runtime_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"\'')
    return values


def _config_signature(path: Path) -> tuple[int, int, int] | None:
    try:
        file_stat = path.stat()
    except OSError:
        return None
    return (file_stat.st_ino, file_stat.st_mtime_ns, file_stat.st_size)


class IDCQueryPlugin(BasePlugin):
    async def initialize(self) -> None:
        self._plugin_config = self.get_config() or {}
        plugin_root = Path(__file__).resolve().parent
        runtime_data_dir = Path('/app/data/idc-query')
        self._runtime_config_path = Path(os.getenv('IDC_QUERY_CONFIG_PATH', str(runtime_data_dir / 'config.env')))
        self._gateway_reload_lock = asyncio.Lock()
        default_state_path = (
            runtime_data_dir / 'bindings.json'
            if runtime_data_dir.is_dir()
            else plugin_root / '.state' / 'bindings.json'
        )
        state_path = Path(
            os.getenv(
                'IDC_QUERY_STATE_PATH',
                str(default_state_path),
            )
        )
        gateway, self._runtime_config_signature = self._load_gateway()

        config = self._plugin_config
        self.idc_query_service = IDCQueryService(
            store=JsonBindingStore(state_path),
            gateway=gateway,
            exclusive_mode=_as_bool(config.get('exclusive_mode'), True),
            sensitive_binder_only=_as_bool(config.get('sensitive_binder_only'), True),
        )
        self.allow_simulated_events = _as_bool(config.get('allow_simulated_events'), False)
        await self.idc_query_service.initialize()

    def _load_gateway(self) -> tuple[IDCQueryGateway, tuple[int, int, int] | None]:
        runtime_config: dict[str, str] = {}
        signature = _config_signature(self._runtime_config_path)
        for _ in range(2):
            before_read = signature
            runtime_config = _read_runtime_config(self._runtime_config_path)
            signature = _config_signature(self._runtime_config_path)
            if before_read == signature:
                break

        config = self._plugin_config
        api_base_url = (
            os.getenv('IDC_QUERY_API_BASE_URL')
            or runtime_config.get('IDC_QUERY_API_BASE_URL')
            or str(config.get('api_base_url', '')).strip()
        )
        api_token = os.getenv('IDC_QUERY_API_TOKEN') or runtime_config.get('IDC_QUERY_API_TOKEN', '')
        timeout_seconds = float(
            os.getenv('IDC_QUERY_TIMEOUT_SECONDS')
            or runtime_config.get('IDC_QUERY_TIMEOUT_SECONDS')
            or config.get('timeout_seconds', 8)
        )
        verify_tls = _as_bool(
            os.getenv('IDC_QUERY_VERIFY_TLS') or runtime_config.get('IDC_QUERY_VERIFY_TLS') or config.get('verify_tls'),
            True,
        )

        return (
            IDCQueryGateway(
                base_url=api_base_url,
                token=api_token,
                timeout_seconds=timeout_seconds,
                verify_tls=verify_tls,
            ),
            signature,
        )

    async def _reload_gateway_if_changed(self) -> None:
        signature = _config_signature(self._runtime_config_path)
        if signature == self._runtime_config_signature:
            return

        async with self._gateway_reload_lock:
            signature = _config_signature(self._runtime_config_path)
            if signature == self._runtime_config_signature:
                return
            try:
                gateway, loaded_signature = self._load_gateway()
            except (OSError, TypeError, UnicodeError, ValueError):
                return
            self.idc_query_service.gateway = gateway
            self._runtime_config_signature = loaded_signature

    async def handle_idc_query(
        self,
        *,
        text: str,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> HandleResult:
        await self._reload_gateway_if_changed()
        return await self.idc_query_service.handle(
            text=text,
            group_id=group_id,
            user_id=user_id,
            message_id=message_id,
        )
