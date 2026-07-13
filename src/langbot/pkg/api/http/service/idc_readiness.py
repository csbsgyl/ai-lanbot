from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from ....core import app


IDC_PLUGIN_AUTHOR = 'csbsgyl'
IDC_PLUGIN_NAME = 'idc-query'
RUNTIME_CHECK_TIMEOUT_SECONDS = 3.0


class IDCReadinessService:
    """Aggregate secret-free readiness signals for the IDC query workflow."""

    def __init__(self, ap: app.Application) -> None:
        self.ap = ap

    async def get_readiness(self) -> dict[str, Any]:
        qq_result, plugin_checks, gateway_checks, activity_result = await asyncio.gather(
            self._qq_checks(),
            self._plugin_checks(),
            self._gateway_checks(),
            self._idc_activity_check(),
        )
        qq_checks, last_qq_event_at = qq_result
        activity_check, last_idc_operation_at = activity_result
        checks = [*qq_checks, *plugin_checks, *gateway_checks, activity_check]

        if any(check['status'] == 'fail' for check in checks):
            status = 'not_ready'
        elif any(check['status'] == 'warn' for check in checks):
            status = 'attention'
        else:
            status = 'ready'

        return {
            'status': status,
            'checks': checks,
            'last_qq_event_at': last_qq_event_at,
            'last_idc_operation_at': last_idc_operation_at,
            'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    async def _qq_checks(self) -> tuple[list[dict[str, str]], str | None]:
        try:
            raw_status = await self.ap.qqofficial_status_service.get_status()
        except Exception:
            return (
                [
                    self._check('qq_bot', 'fail', 'unavailable'),
                    self._check('qq_callback', 'fail', 'unavailable'),
                    self._check('qq_activity', 'warn', 'unavailable'),
                ],
                None,
            )

        if not isinstance(raw_status, dict):
            raw_status = {}
        status = raw_status.get('status')
        last_event_at = self._latest_qq_event(raw_status.get('bots'))

        if status in {'ready', 'websocket_mode', 'conflict'}:
            bot_check = self._check('qq_bot', 'pass', 'enabled')
        elif status == 'not_configured':
            bot_check = self._check('qq_bot', 'fail', 'not_configured')
        elif status == 'disabled':
            bot_check = self._check('qq_bot', 'fail', 'disabled')
        else:
            bot_check = self._check('qq_bot', 'fail', 'unavailable')

        if status == 'ready':
            callback_check = self._check('qq_callback', 'pass', 'ready')
        elif status == 'websocket_mode':
            callback_check = self._check('qq_callback', 'warn', 'websocket_mode')
        elif status == 'conflict':
            callback_check = self._check('qq_callback', 'fail', 'conflict')
        elif status == 'not_configured':
            callback_check = self._check('qq_callback', 'fail', 'not_configured')
        elif status == 'disabled':
            callback_check = self._check('qq_callback', 'fail', 'disabled')
        else:
            callback_check = self._check('qq_callback', 'fail', 'unavailable')

        if last_event_at:
            activity_check = self._check('qq_activity', 'pass', 'received')
        elif status == 'websocket_mode':
            activity_check = self._check('qq_activity', 'warn', 'websocket_mode')
        elif status in {'ready', 'conflict'}:
            activity_check = self._check('qq_activity', 'warn', 'none')
        else:
            activity_check = self._check('qq_activity', 'warn', 'unavailable')

        return [bot_check, callback_check, activity_check], last_event_at

    async def _plugin_checks(self) -> list[dict[str, str]]:
        connector = getattr(self.ap, 'plugin_connector', None)
        if connector is None:
            return [
                self._check('plugin_runtime', 'fail', 'unavailable'),
                self._check('idc_plugin', 'fail', 'unavailable'),
            ]
        if not bool(getattr(connector, 'is_enable_plugin', False)):
            return [
                self._check('plugin_runtime', 'fail', 'disabled'),
                self._check('idc_plugin', 'fail', 'unavailable'),
            ]

        try:
            await asyncio.wait_for(
                connector.ping_plugin_runtime(),
                timeout=RUNTIME_CHECK_TIMEOUT_SECONDS,
            )
        except Exception:
            return [
                self._check('plugin_runtime', 'fail', 'disconnected'),
                self._check('idc_plugin', 'fail', 'unavailable'),
            ]

        runtime_check = self._check('plugin_runtime', 'pass', 'connected')
        try:
            plugin = await asyncio.wait_for(
                connector.get_plugin_info(IDC_PLUGIN_AUTHOR, IDC_PLUGIN_NAME),
                timeout=RUNTIME_CHECK_TIMEOUT_SECONDS,
            )
        except Exception:
            return [runtime_check, self._check('idc_plugin', 'fail', 'not_loaded')]

        if isinstance(plugin, dict) and plugin.get('status') == 'initialized':
            plugin_check = self._check('idc_plugin', 'pass', 'initialized')
        else:
            plugin_check = self._check('idc_plugin', 'fail', 'not_initialized')
        return [runtime_check, plugin_check]

    async def _gateway_checks(self) -> list[dict[str, str]]:
        try:
            config = await self.ap.idc_query_config_service.get_config()
        except Exception:
            return [
                self._check('gateway_config', 'fail', 'unavailable'),
                self._check('gateway_tls', 'warn', 'unavailable'),
                self._check('gateway_auth', 'warn', 'unavailable'),
            ]

        if not isinstance(config, dict):
            config = {}
        base_url = config.get('base_url') if isinstance(config.get('base_url'), str) else ''
        parsed = None
        valid_url = False
        invalid_character = any(
            character.isspace() or ord(character) < 32 or ord(character) == 127 for character in base_url
        )
        if base_url and not invalid_character:
            try:
                parsed = urlsplit(base_url)
                parsed.port
                valid_url = bool(
                    parsed.scheme in {'http', 'https'}
                    and parsed.netloc
                    and parsed.hostname
                    and not parsed.username
                    and not parsed.password
                    and not parsed.query
                    and not parsed.fragment
                )
            except ValueError:
                valid_url = False

        if not base_url:
            config_check = self._check('gateway_config', 'fail', 'not_configured')
        elif not valid_url:
            config_check = self._check('gateway_config', 'fail', 'invalid')
        else:
            config_check = self._check('gateway_config', 'pass', 'configured')

        if not valid_url:
            tls_check = self._check('gateway_tls', 'warn', 'unavailable')
        elif parsed is not None and parsed.scheme == 'http':
            tls_check = self._check('gateway_tls', 'warn', 'plaintext')
        elif bool(config.get('verify_tls')):
            tls_check = self._check('gateway_tls', 'pass', 'verified')
        else:
            tls_check = self._check('gateway_tls', 'warn', 'verification_disabled')

        auth_check = self._check(
            'gateway_auth',
            'pass' if bool(config.get('token_configured')) else 'warn',
            'configured' if bool(config.get('token_configured')) else 'optional',
        )
        return [config_check, tls_check, auth_check]

    async def _idc_activity_check(self) -> tuple[dict[str, str], str | None]:
        try:
            result = await self.ap.idc_query_config_service.get_audit_events(20)
        except Exception:
            return self._check('idc_activity', 'warn', 'unavailable'), None

        events = result.get('events') if isinstance(result, dict) else None
        last_operation_at = self._latest_event_timestamp(events)
        if last_operation_at:
            return self._check('idc_activity', 'pass', 'recorded'), last_operation_at
        return self._check('idc_activity', 'warn', 'none'), None

    @classmethod
    def _latest_qq_event(cls, bots: Any) -> str | None:
        if not isinstance(bots, list):
            return None
        values = []
        for bot in bots:
            if not isinstance(bot, dict) or not bot.get('enabled'):
                continue
            metrics = bot.get('metrics') if isinstance(bot, dict) else None
            if isinstance(metrics, dict):
                values.append(metrics.get('last_event_at'))
        return cls._latest_timestamp(values)

    @classmethod
    def _latest_event_timestamp(cls, events: Any) -> str | None:
        if not isinstance(events, list):
            return None
        values = [event.get('timestamp') for event in events if isinstance(event, dict)]
        return cls._latest_timestamp(values)

    @staticmethod
    def _latest_timestamp(values: list[Any]) -> str | None:
        parsed_values: list[tuple[datetime.datetime, str]] = []
        for value in values:
            if not isinstance(value, str) or not value or len(value) > 64:
                continue
            try:
                parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    continue
                normalized = parsed.astimezone(datetime.timezone.utc)
            except (ValueError, OverflowError, OSError):
                continue
            parsed_values.append((normalized, normalized.isoformat()))
        if not parsed_values:
            return None
        return max(parsed_values, key=lambda item: item[0])[1]

    @staticmethod
    def _check(check_id: str, status: str, code: str) -> dict[str, str]:
        return {'id': check_id, 'status': status, 'code': code}
