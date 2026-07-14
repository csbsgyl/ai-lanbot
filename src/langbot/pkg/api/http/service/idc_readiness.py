from __future__ import annotations

import asyncio
import datetime
import math
import os
import re
import unicodedata
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from ....utils import constants
from . import idc_query_config

if TYPE_CHECKING:
    from ....core import app


IDC_PLUGIN_AUTHOR = 'csbsgyl'
IDC_PLUGIN_NAME = 'idc-query'
RUNTIME_CHECK_TIMEOUT_SECONDS = 3.0
DIAGNOSTIC_SCHEMA_VERSION = 1
DIAGNOSTIC_AUDIT_LIMIT = 100
MAX_DIAGNOSTIC_COUNT = 1_000_000_000_000
REVISION_PATTERN = re.compile(r'^[0-9a-f]{40}$')
READINESS_CHECK_IDS = {
    'qq_bot',
    'qq_callback',
    'qq_activity',
    'plugin_runtime',
    'idc_plugin',
    'gateway_config',
    'gateway_tls',
    'gateway_auth',
    'idc_activity',
}
READINESS_CHECK_STATUSES = {'pass', 'warn', 'fail'}
READINESS_CHECK_CODES = {
    'unavailable',
    'enabled',
    'not_configured',
    'disabled',
    'ready',
    'websocket_mode',
    'conflict',
    'received',
    'none',
    'connected',
    'disconnected',
    'not_loaded',
    'initialized',
    'not_initialized',
    'configured',
    'invalid',
    'verified',
    'plaintext',
    'verification_disabled',
    'optional',
    'recorded',
}
QQ_CALLBACK_STATUSES = {'ready', 'not_configured', 'disabled', 'websocket_mode', 'conflict'}
QQ_WEBHOOK_COUNTERS = (
    'requests_total',
    'validations_total',
    'events_total',
    'duplicates_total',
    'rejected_total',
    'overloaded_total',
    'pending_events',
    'pending_limit',
)
QQ_WEBHOOK_TIMESTAMPS = (
    'last_request_at',
    'last_valid_at',
    'last_event_at',
    'last_rejected_at',
    'last_overloaded_at',
)
AUDIT_REASONS = {
    'bound',
    'unbound',
    'queried',
    'not_bound',
    'binder_required',
    'already_bound',
    'binding_conflict',
    'rate_limit',
    'gateway_error',
    'internal_error',
}


class IDCReadinessService:
    """Aggregate secret-free readiness signals for the IDC query workflow."""

    def __init__(self, ap: app.Application) -> None:
        self.ap = ap

    async def get_readiness(self) -> dict[str, Any]:
        qq_status, plugin_checks, gateway_config, audit = await asyncio.gather(
            self.ap.qqofficial_status_service.get_status(),
            self._plugin_checks(),
            self.ap.idc_query_config_service.get_config(),
            self.ap.idc_query_config_service.get_audit_events(20),
            return_exceptions=True,
        )
        return self._build_readiness(qq_status, plugin_checks, gateway_config, audit)

    async def get_diagnostics(self) -> dict[str, Any]:
        """Return a fixed-schema report that is safe to share with support."""
        qq_status, plugin_checks, gateway_config, audit = await asyncio.gather(
            self.ap.qqofficial_status_service.get_status(),
            self._plugin_checks(),
            self.ap.idc_query_config_service.get_config(),
            self.ap.idc_query_config_service.get_audit_events(DIAGNOSTIC_AUDIT_LIMIT),
            return_exceptions=True,
        )
        readiness = self._build_readiness(qq_status, plugin_checks, gateway_config, audit)
        return {
            'schema_version': DIAGNOSTIC_SCHEMA_VERSION,
            'application': self._diagnostic_application(),
            'readiness': self._diagnostic_readiness(readiness),
            'qq_callback': self._diagnostic_qq_callback(qq_status),
            'gateway': self._diagnostic_gateway(gateway_config),
            'audit': self._diagnostic_audit(audit),
            'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def _build_readiness(
        self,
        qq_status: Any,
        plugin_checks: Any,
        gateway_config: Any,
        audit: Any,
    ) -> dict[str, Any]:
        qq_checks, last_qq_event_at = self._qq_checks_from_status(qq_status)
        normalized_plugin_checks = self._plugin_checks_from_result(plugin_checks)
        gateway_checks = self._gateway_checks_from_config(gateway_config)
        activity_check, last_idc_operation_at = self._idc_activity_check_from_audit(audit)
        checks = [*qq_checks, *normalized_plugin_checks, *gateway_checks, activity_check]

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

    @staticmethod
    def _diagnostic_application() -> dict[str, Any]:
        revision = os.environ.get('LANBOT_BUILD_REVISION', '').strip().lower()
        if not REVISION_PATTERN.fullmatch(revision):
            revision = 'unknown'
        return {
            'version': constants.semantic_version,
            'revision': revision,
            'edition': constants.edition,
            'debug': bool(constants.debug_mode),
            'managed_updates': os.environ.get('LANBOT_UPDATE_ENABLED', '').strip().lower() == 'true',
        }

    @classmethod
    def _diagnostic_readiness(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {
                'available': False,
                'status': 'not_ready',
                'checks': [],
                'last_qq_event_at': None,
                'last_idc_operation_at': None,
            }

        status = value.get('status') if value.get('status') in {'ready', 'attention', 'not_ready'} else 'not_ready'
        checks = []
        raw_checks = value.get('checks') if isinstance(value.get('checks'), list) else []
        for raw_check in raw_checks[: len(READINESS_CHECK_IDS)]:
            if not isinstance(raw_check, dict):
                continue
            check_id = raw_check.get('id')
            check_status = raw_check.get('status')
            check_code = raw_check.get('code')
            if check_id not in READINESS_CHECK_IDS or check_status not in READINESS_CHECK_STATUSES:
                continue
            checks.append(
                {
                    'id': check_id,
                    'status': check_status,
                    'code': check_code if check_code in READINESS_CHECK_CODES else 'unavailable',
                }
            )
        return {
            'available': True,
            'status': status,
            'checks': checks,
            'last_qq_event_at': cls._normalized_timestamp(value.get('last_qq_event_at')),
            'last_idc_operation_at': cls._normalized_timestamp(value.get('last_idc_operation_at')),
        }

    @classmethod
    def _diagnostic_qq_callback(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return cls._empty_qq_diagnostics()

        raw_bots = value.get('bots') if isinstance(value.get('bots'), list) else []
        bots = [bot for bot in raw_bots[:1000] if isinstance(bot, dict)]
        enabled_bots = [bot for bot in bots if bot.get('enabled') is True]
        active_webhooks = [bot for bot in enabled_bots if bot.get('mode') == 'webhook']
        active_websockets = [bot for bot in enabled_bots if bot.get('mode') == 'websocket']
        metrics = {counter: 0 for counter in QQ_WEBHOOK_COUNTERS}
        metric_timestamps: dict[str, list[Any]] = {timestamp: [] for timestamp in QQ_WEBHOOK_TIMESTAMPS}
        for bot in active_webhooks:
            raw_metrics = bot.get('metrics')
            if not isinstance(raw_metrics, dict):
                continue
            for counter in QQ_WEBHOOK_COUNTERS:
                metrics[counter] = min(
                    MAX_DIAGNOSTIC_COUNT,
                    metrics[counter] + cls._safe_count(raw_metrics.get(counter)),
                )
            for timestamp in QQ_WEBHOOK_TIMESTAMPS:
                metric_timestamps[timestamp].append(raw_metrics.get(timestamp))
        metrics.update({timestamp: cls._latest_timestamp(values) for timestamp, values in metric_timestamps.items()})

        status = value.get('status')
        return {
            'available': True,
            'status': status if status in QQ_CALLBACK_STATUSES else 'unavailable',
            'callback_path': '/qq/callback',
            'configured_bots': len(bots),
            'enabled_bots': len(enabled_bots),
            'disabled_bots': len(bots) - len(enabled_bots),
            'active_webhook_bots': len(active_webhooks),
            'active_websocket_bots': len(active_websockets),
            'metrics': metrics,
        }

    @staticmethod
    def _empty_qq_diagnostics() -> dict[str, Any]:
        metrics: dict[str, Any] = {counter: 0 for counter in QQ_WEBHOOK_COUNTERS}
        metrics.update({timestamp: None for timestamp in QQ_WEBHOOK_TIMESTAMPS})
        return {
            'available': False,
            'status': 'unavailable',
            'callback_path': '/qq/callback',
            'configured_bots': 0,
            'enabled_bots': 0,
            'disabled_bots': 0,
            'active_webhook_bots': 0,
            'active_websocket_bots': 0,
            'metrics': metrics,
        }

    @classmethod
    def _diagnostic_gateway(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {
                'available': False,
                'configured': False,
                'transport': 'unavailable',
                'verify_tls': False,
                'service_token_configured': False,
                'timeout_seconds': idc_query_config.DEFAULT_TIMEOUT_SECONDS,
                'requests_per_minute': idc_query_config.DEFAULT_REQUESTS_PER_MINUTE,
                'bind_attempts_per_10_minutes': idc_query_config.DEFAULT_BIND_ATTEMPTS_PER_10_MINUTES,
            }

        base_url = value.get('base_url') if isinstance(value.get('base_url'), str) else ''
        try:
            scheme = urlsplit(base_url).scheme.lower()
        except ValueError:
            scheme = ''
        transport = scheme if scheme in {'http', 'https'} else 'unavailable'
        return {
            'available': True,
            'configured': bool(value.get('configured')),
            'transport': transport,
            'verify_tls': value.get('verify_tls') is True,
            'service_token_configured': value.get('token_configured') is True,
            'timeout_seconds': cls._safe_number(
                value.get('timeout_seconds'),
                idc_query_config.DEFAULT_TIMEOUT_SECONDS,
                idc_query_config.MIN_TIMEOUT_SECONDS,
                idc_query_config.MAX_TIMEOUT_SECONDS,
            ),
            'requests_per_minute': cls._safe_integer(
                value.get('requests_per_minute'),
                idc_query_config.DEFAULT_REQUESTS_PER_MINUTE,
                idc_query_config.MIN_RATE_LIMIT,
                idc_query_config.MAX_RATE_LIMIT,
            ),
            'bind_attempts_per_10_minutes': cls._safe_integer(
                value.get('bind_attempts_per_10_minutes'),
                idc_query_config.DEFAULT_BIND_ATTEMPTS_PER_10_MINUTES,
                idc_query_config.MIN_RATE_LIMIT,
                idc_query_config.MAX_RATE_LIMIT,
            ),
        }

    @classmethod
    def _diagnostic_audit(cls, value: Any) -> dict[str, Any]:
        available = isinstance(value, dict)
        raw_events = value.get('events') if available and isinstance(value.get('events'), list) else []
        events = [event for event in raw_events[:DIAGNOSTIC_AUDIT_LIMIT] if isinstance(event, dict)]
        command_counts = {command: 0 for command in sorted(idc_query_config.AUDIT_COMMANDS)}
        command_counts['unknown'] = 0
        outcome_counts = {outcome: 0 for outcome in sorted(idc_query_config.AUDIT_OUTCOMES)}
        outcome_counts['unknown'] = 0
        reason_counts = {reason: 0 for reason in sorted(AUDIT_REASONS)}
        reason_counts['unknown'] = 0
        for event in events:
            command = cls._known_category(event.get('command'), idc_query_config.AUDIT_COMMANDS)
            outcome = cls._known_category(event.get('outcome'), idc_query_config.AUDIT_OUTCOMES)
            reason = cls._known_category(event.get('reason'), AUDIT_REASONS)
            command_counts[command] += 1
            outcome_counts[outcome] += 1
            reason_counts[reason] += 1

        last_event = None
        if events:
            raw_last = events[0]
            last_event = {
                'command': cls._known_category(raw_last.get('command'), idc_query_config.AUDIT_COMMANDS),
                'outcome': cls._known_category(raw_last.get('outcome'), idc_query_config.AUDIT_OUTCOMES),
                'reason': cls._known_category(raw_last.get('reason'), AUDIT_REASONS),
                'duration_ms': min(3_600_000, cls._safe_count(raw_last.get('duration_ms'))),
            }
        return {
            'available': available,
            'sample_size': len(events),
            'commands': command_counts,
            'outcomes': outcome_counts,
            'reasons': reason_counts,
            'last_event_at': cls._latest_timestamp([event.get('timestamp') for event in events]),
            'last_event': last_event,
        }

    @staticmethod
    def _known_category(value: Any, allowed: set[str]) -> str:
        return value if isinstance(value, str) and value in allowed else 'unknown'

    @staticmethod
    def _safe_count(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(0, min(value, MAX_DIAGNOSTIC_COUNT))

    @staticmethod
    def _safe_integer(value: Any, default: int, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            return default
        return value

    @staticmethod
    def _safe_number(value: Any, default: float, minimum: float, maximum: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        numeric = float(value)
        if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
            return default
        return numeric

    @classmethod
    def _normalized_timestamp(cls, value: Any) -> str | None:
        return cls._latest_timestamp([value])

    @classmethod
    def _qq_checks_from_status(cls, value: Any) -> tuple[list[dict[str, str]], str | None]:
        if not isinstance(value, dict):
            return (
                [
                    cls._check('qq_bot', 'fail', 'unavailable'),
                    cls._check('qq_callback', 'fail', 'unavailable'),
                    cls._check('qq_activity', 'warn', 'unavailable'),
                ],
                None,
            )

        status = value.get('status')
        last_event_at = cls._latest_qq_event(value.get('bots'))

        if status in {'ready', 'websocket_mode', 'conflict'}:
            bot_check = cls._check('qq_bot', 'pass', 'enabled')
        elif status == 'not_configured':
            bot_check = cls._check('qq_bot', 'fail', 'not_configured')
        elif status == 'disabled':
            bot_check = cls._check('qq_bot', 'fail', 'disabled')
        else:
            bot_check = cls._check('qq_bot', 'fail', 'unavailable')

        if status == 'ready':
            callback_check = cls._check('qq_callback', 'pass', 'ready')
        elif status == 'websocket_mode':
            callback_check = cls._check('qq_callback', 'warn', 'websocket_mode')
        elif status == 'conflict':
            callback_check = cls._check('qq_callback', 'fail', 'conflict')
        elif status == 'not_configured':
            callback_check = cls._check('qq_callback', 'fail', 'not_configured')
        elif status == 'disabled':
            callback_check = cls._check('qq_callback', 'fail', 'disabled')
        else:
            callback_check = cls._check('qq_callback', 'fail', 'unavailable')

        if last_event_at:
            activity_check = cls._check('qq_activity', 'pass', 'received')
        elif status == 'websocket_mode':
            activity_check = cls._check('qq_activity', 'warn', 'websocket_mode')
        elif status in {'ready', 'conflict'}:
            activity_check = cls._check('qq_activity', 'warn', 'none')
        else:
            activity_check = cls._check('qq_activity', 'warn', 'unavailable')

        return [bot_check, callback_check, activity_check], last_event_at

    async def _qq_checks(self) -> tuple[list[dict[str, str]], str | None]:
        try:
            raw_status = await self.ap.qqofficial_status_service.get_status()
        except Exception:
            raw_status = None
        return self._qq_checks_from_status(raw_status)

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

    @classmethod
    def _plugin_checks_from_result(cls, value: Any) -> list[dict[str, str]]:
        fallback = [
            cls._check('plugin_runtime', 'fail', 'unavailable'),
            cls._check('idc_plugin', 'fail', 'unavailable'),
        ]
        if not isinstance(value, list):
            return fallback
        by_id = {
            check.get('id'): check
            for check in value
            if isinstance(check, dict) and check.get('id') in {'plugin_runtime', 'idc_plugin'}
        }
        normalized = []
        for index, check_id in enumerate(('plugin_runtime', 'idc_plugin')):
            check = by_id.get(check_id)
            if not isinstance(check, dict):
                normalized.append(fallback[index])
                continue
            status = check.get('status')
            code = check.get('code')
            normalized.append(
                cls._check(
                    check_id,
                    status if status in READINESS_CHECK_STATUSES else 'fail',
                    code if code in READINESS_CHECK_CODES else 'unavailable',
                )
            )
        return normalized

    @classmethod
    def _gateway_checks_from_config(cls, value: Any) -> list[dict[str, str]]:
        if isinstance(value, BaseException):
            return [
                cls._check('gateway_config', 'fail', 'unavailable'),
                cls._check('gateway_tls', 'warn', 'unavailable'),
                cls._check('gateway_auth', 'warn', 'unavailable'),
            ]

        config = value if isinstance(value, dict) else {}
        base_url = config.get('base_url') if isinstance(config.get('base_url'), str) else ''
        parsed = None
        valid_url = False
        invalid_character = any(
            character.isspace() or unicodedata.category(character) in {'Cc', 'Cf', 'Cs'} for character in base_url
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
            config_check = cls._check('gateway_config', 'fail', 'not_configured')
        elif not valid_url:
            config_check = cls._check('gateway_config', 'fail', 'invalid')
        else:
            config_check = cls._check('gateway_config', 'pass', 'configured')

        if not valid_url:
            tls_check = cls._check('gateway_tls', 'warn', 'unavailable')
        elif parsed is not None and parsed.scheme == 'http':
            tls_check = cls._check('gateway_tls', 'warn', 'plaintext')
        elif bool(config.get('verify_tls')):
            tls_check = cls._check('gateway_tls', 'pass', 'verified')
        else:
            tls_check = cls._check('gateway_tls', 'warn', 'verification_disabled')

        auth_check = cls._check(
            'gateway_auth',
            'pass' if bool(config.get('token_configured')) else 'warn',
            'configured' if bool(config.get('token_configured')) else 'optional',
        )
        return [config_check, tls_check, auth_check]

    async def _gateway_checks(self) -> list[dict[str, str]]:
        try:
            config = await self.ap.idc_query_config_service.get_config()
        except Exception as exc:
            config = exc
        return self._gateway_checks_from_config(config)

    @classmethod
    def _idc_activity_check_from_audit(cls, value: Any) -> tuple[dict[str, str], str | None]:
        if isinstance(value, BaseException):
            return cls._check('idc_activity', 'warn', 'unavailable'), None
        events = value.get('events') if isinstance(value, dict) else None
        last_operation_at = cls._latest_event_timestamp(events)
        if last_operation_at:
            return cls._check('idc_activity', 'pass', 'recorded'), last_operation_at
        return cls._check('idc_activity', 'warn', 'none'), None

    async def _idc_activity_check(self) -> tuple[dict[str, str], str | None]:
        try:
            result = await self.ap.idc_query_config_service.get_audit_events(20)
        except Exception as exc:
            result = exc
        return self._idc_activity_check_from_audit(result)

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
