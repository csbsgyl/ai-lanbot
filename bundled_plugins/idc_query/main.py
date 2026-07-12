from __future__ import annotations

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
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


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


class IDCQueryPlugin(BasePlugin):
    async def initialize(self) -> None:
        config = self.get_config() or {}
        plugin_root = Path(__file__).resolve().parent
        runtime_data_dir = Path('/app/data/idc-query')
        runtime_config = _read_runtime_config(
            Path(os.getenv('IDC_QUERY_CONFIG_PATH', str(runtime_data_dir / 'config.env')))
        )
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

        gateway = IDCQueryGateway(
            base_url=api_base_url,
            token=api_token,
            timeout_seconds=timeout_seconds,
            verify_tls=verify_tls,
        )
        self.idc_query_service = IDCQueryService(
            store=JsonBindingStore(state_path),
            gateway=gateway,
            exclusive_mode=_as_bool(config.get('exclusive_mode'), True),
            sensitive_binder_only=_as_bool(config.get('sensitive_binder_only'), True),
        )
        self.allow_simulated_events = _as_bool(config.get('allow_simulated_events'), False)
        await self.idc_query_service.initialize()

    async def handle_idc_query(
        self,
        *,
        text: str,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> HandleResult:
        return await self.idc_query_service.handle(
            text=text,
            group_id=group_id,
            user_id=user_id,
            message_id=message_id,
        )
