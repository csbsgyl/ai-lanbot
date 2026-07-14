from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from langbot.pkg.api.http.service.idc_readiness import IDCReadinessService


def _make_app(
    *,
    qq_status: dict | Exception | None = None,
    plugin_enabled: bool = True,
    ping_result: object | Exception = None,
    plugin_result: dict | Exception | None = None,
    config: dict | Exception | None = None,
    audit: dict | Exception | None = None,
):
    if qq_status is None:
        qq_status = {
            'status': 'ready',
            'bots': [
                {
                    'enabled': True,
                    'metrics': {'last_event_at': '2026-07-13T10:05:00+00:00'},
                }
            ],
        }
    if plugin_result is None:
        plugin_result = {'status': 'initialized'}
    if config is None:
        config = {
            'base_url': 'https://query.example.com',
            'verify_tls': True,
            'token_configured': True,
        }
    if audit is None:
        audit = {'events': [{'timestamp': '2026-07-13T10:06:00+00:00'}]}

    qq_reader = AsyncMock(side_effect=qq_status if isinstance(qq_status, Exception) else None)
    if not isinstance(qq_status, Exception):
        qq_reader.return_value = qq_status

    ping = AsyncMock(side_effect=ping_result if isinstance(ping_result, Exception) else None)
    if not isinstance(ping_result, Exception):
        ping.return_value = ping_result

    plugin_reader = AsyncMock(side_effect=plugin_result if isinstance(plugin_result, Exception) else None)
    if not isinstance(plugin_result, Exception):
        plugin_reader.return_value = plugin_result

    config_reader = AsyncMock(side_effect=config if isinstance(config, Exception) else None)
    if not isinstance(config, Exception):
        config_reader.return_value = config

    audit_reader = AsyncMock(side_effect=audit if isinstance(audit, Exception) else None)
    if not isinstance(audit, Exception):
        audit_reader.return_value = audit

    return SimpleNamespace(
        qqofficial_status_service=SimpleNamespace(get_status=qq_reader),
        plugin_connector=SimpleNamespace(
            is_enable_plugin=plugin_enabled,
            ping_plugin_runtime=ping,
            get_plugin_info=plugin_reader,
        ),
        idc_query_config_service=SimpleNamespace(
            get_config=config_reader,
            get_audit_events=audit_reader,
        ),
    )


def _checks_by_id(result: dict) -> dict[str, dict[str, str]]:
    return {check['id']: check for check in result['checks']}


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


@pytest.mark.asyncio
async def test_reports_ready_when_all_required_and_observation_checks_pass():
    app = _make_app()

    result = await IDCReadinessService(app).get_readiness()
    checks = _checks_by_id(result)

    assert result['status'] == 'ready'
    assert all(check['status'] == 'pass' for check in checks.values())
    assert result['last_qq_event_at'] == '2026-07-13T10:05:00+00:00'
    assert result['last_idc_operation_at'] == '2026-07-13T10:06:00+00:00'
    app.plugin_connector.get_plugin_info.assert_awaited_once_with('csbsgyl', 'idc-query')
    app.idc_query_config_service.get_audit_events.assert_awaited_once_with(20)


@pytest.mark.asyncio
async def test_unconfigured_install_reports_blockers_and_non_blocking_warnings():
    app = _make_app(
        qq_status={'status': 'not_configured', 'bots': []},
        config={
            'base_url': '',
            'verify_tls': True,
            'token_configured': False,
        },
        audit={'events': []},
    )

    result = await IDCReadinessService(app).get_readiness()
    checks = _checks_by_id(result)

    assert result['status'] == 'not_ready'
    assert checks['qq_bot'] == {'id': 'qq_bot', 'status': 'fail', 'code': 'not_configured'}
    assert checks['qq_callback']['status'] == 'fail'
    assert checks['gateway_config']['status'] == 'fail'
    assert checks['gateway_auth'] == {'id': 'gateway_auth', 'status': 'warn', 'code': 'optional'}
    assert checks['qq_activity']['status'] == 'warn'
    assert checks['idc_activity']['status'] == 'warn'
    assert result['last_qq_event_at'] is None
    assert result['last_idc_operation_at'] is None


@pytest.mark.asyncio
async def test_websocket_mode_is_attention_instead_of_callback_failure():
    app = _make_app(qq_status={'status': 'websocket_mode', 'bots': [{'enabled': True, 'metrics': None}]})

    result = await IDCReadinessService(app).get_readiness()
    checks = _checks_by_id(result)

    assert result['status'] == 'attention'
    assert checks['qq_bot']['status'] == 'pass'
    assert checks['qq_callback'] == {
        'id': 'qq_callback',
        'status': 'warn',
        'code': 'websocket_mode',
    }
    assert checks['qq_activity']['status'] == 'warn'


@pytest.mark.asyncio
async def test_disabled_or_disconnected_runtime_does_not_probe_plugin():
    disabled_app = _make_app(plugin_enabled=False)

    disabled = await IDCReadinessService(disabled_app).get_readiness()
    disabled_checks = _checks_by_id(disabled)

    assert disabled_checks['plugin_runtime']['code'] == 'disabled'
    assert disabled_checks['idc_plugin']['status'] == 'fail'
    disabled_app.plugin_connector.ping_plugin_runtime.assert_not_awaited()
    disabled_app.plugin_connector.get_plugin_info.assert_not_awaited()

    disconnected_app = _make_app(ping_result=RuntimeError('ws://private-runtime:5400/secret'))
    disconnected = await IDCReadinessService(disconnected_app).get_readiness()
    disconnected_checks = _checks_by_id(disconnected)

    assert disconnected_checks['plugin_runtime']['code'] == 'disconnected'
    assert disconnected_checks['idc_plugin']['code'] == 'unavailable'
    disconnected_app.plugin_connector.get_plugin_info.assert_not_awaited()
    assert 'private-runtime' not in json.dumps(disconnected)


@pytest.mark.asyncio
async def test_plugin_must_reach_initialized_state():
    app = _make_app(plugin_result={'status': 'initializing', 'error': 'private stack trace'})

    result = await IDCReadinessService(app).get_readiness()
    checks = _checks_by_id(result)

    assert result['status'] == 'not_ready'
    assert checks['idc_plugin'] == {
        'id': 'idc_plugin',
        'status': 'fail',
        'code': 'not_initialized',
    }
    assert 'private stack trace' not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('config', 'tls_code'),
    [
        (
            {
                'base_url': 'https://query.example.com',
                'verify_tls': False,
                'token_configured': True,
            },
            'verification_disabled',
        ),
        (
            {
                'base_url': 'http://query.internal',
                'verify_tls': True,
                'token_configured': True,
            },
            'plaintext',
        ),
    ],
)
async def test_gateway_transport_warnings_are_non_blocking(config: dict, tls_code: str):
    result = await IDCReadinessService(_make_app(config=config)).get_readiness()
    checks = _checks_by_id(result)

    assert result['status'] == 'attention'
    assert checks['gateway_config']['status'] == 'pass'
    assert checks['gateway_tls'] == {'id': 'gateway_tls', 'status': 'warn', 'code': tls_code}


@pytest.mark.asyncio
async def test_malformed_gateway_url_from_disk_is_reported_without_raising():
    result = await IDCReadinessService(
        _make_app(
            config={
                'base_url': 'https://[invalid-ipv6',
                'verify_tls': True,
                'token_configured': True,
            }
        )
    ).get_readiness()
    checks = _checks_by_id(result)

    assert result['status'] == 'not_ready'
    assert checks['gateway_config'] == {
        'id': 'gateway_config',
        'status': 'fail',
        'code': 'invalid',
    }
    assert checks['gateway_tls']['code'] == 'unavailable'


@pytest.mark.asyncio
async def test_gateway_url_with_invisible_formatting_character_is_invalid():
    result = await IDCReadinessService(
        _make_app(
            config={
                'base_url': 'https://query.example.com/\u202eTXT',
                'verify_tls': True,
                'token_configured': True,
            }
        )
    ).get_readiness()

    assert _checks_by_id(result)['gateway_config']['code'] == 'invalid'
    assert result['status'] == 'not_ready'


@pytest.mark.asyncio
async def test_manually_edited_gateway_url_with_whitespace_is_invalid():
    result = await IDCReadinessService(
        _make_app(
            config={
                'base_url': 'https://query.example.com/private path',
                'verify_tls': True,
                'token_configured': True,
            }
        )
    ).get_readiness()

    assert _checks_by_id(result)['gateway_config']['code'] == 'invalid'
    assert result['status'] == 'not_ready'


@pytest.mark.asyncio
async def test_service_failures_and_malformed_timestamps_are_sanitized():
    secret = 'https://user:password@private-gateway.example/path?token=secret'
    app = _make_app(
        qq_status=RuntimeError(secret),
        plugin_result=RuntimeError(secret),
        config=OSError(secret),
        audit=UnicodeError(secret),
    )

    result = await IDCReadinessService(app).get_readiness()
    serialized = json.dumps(result)

    assert result['status'] == 'not_ready'
    assert secret not in serialized
    assert 'password' not in serialized
    assert 'private-gateway' not in serialized
    assert result['last_qq_event_at'] is None
    assert result['last_idc_operation_at'] is None


@pytest.mark.asyncio
async def test_latest_valid_activity_timestamps_are_normalized_and_disabled_bots_are_ignored():
    app = _make_app(
        qq_status={
            'status': 'ready',
            'bots': [
                {'enabled': False, 'metrics': {'last_event_at': '2026-07-13T12:00:00Z'}},
                {'enabled': True, 'metrics': {'last_event_at': 'invalid'}},
                {'enabled': True, 'metrics': {'last_event_at': '2026-07-13T11:00:00+08:00'}},
            ],
        },
        audit={
            'events': [
                {'timestamp': 'invalid'},
                {'timestamp': '0001-01-01T00:00:00+23:59'},
                {'timestamp': '2026-07-13T10:30:00+08:00'},
                {'timestamp': '2026-07-13T03:00:00Z'},
            ]
        },
    )

    result = await IDCReadinessService(app).get_readiness()

    assert result['last_qq_event_at'] == '2026-07-13T03:00:00+00:00'
    assert result['last_idc_operation_at'] == '2026-07-13T03:00:00+00:00'


@pytest.mark.asyncio
async def test_diagnostics_aggregate_runtime_signals_without_identity_or_credentials(monkeypatch):
    secrets = {
        'private-app-id-1029384756',
        'private-bot-uuid',
        'Private QQ Bot Name',
        'https://private-gateway.example/internal?token=secret',
        'private-service-token',
        'private-group-openid',
        'private-user-openid',
        'private-member-id',
        'private-request-id',
        'private-untrusted-reason',
    }
    app = _make_app(
        qq_status={
            'status': 'ready',
            'configured_callback_url': 'https://private-callback.example/qq/callback',
            'bots': [
                {
                    'uuid': 'private-bot-uuid',
                    'name': 'Private QQ Bot Name',
                    'app_id': 'private-app-id-1029384756',
                    'enabled': True,
                    'mode': 'webhook',
                    'metrics': {
                        'requests_total': 12,
                        'validations_total': 2,
                        'events_total': 8,
                        'duplicates_total': 1,
                        'rejected_total': 1,
                        'overloaded_total': 0,
                        'pending_events': 3,
                        'pending_limit': 256,
                        'last_request_at': '2026-07-13T10:05:00Z',
                        'last_valid_at': '2026-07-13T10:04:00Z',
                        'last_event_at': '2026-07-13T10:03:00Z',
                        'last_rejected_at': '2026-07-13T10:02:00Z',
                        'last_overloaded_at': None,
                    },
                },
                {
                    'uuid': 'disabled-private-bot',
                    'name': 'Disabled Private Bot',
                    'app_id': 'disabled-private-app-id',
                    'enabled': False,
                    'mode': 'webhook',
                    'metrics': {'events_total': 999},
                },
                {
                    'uuid': 'websocket-private-bot',
                    'name': 'WebSocket Private Bot',
                    'app_id': 'websocket-private-app-id',
                    'enabled': True,
                    'mode': 'websocket',
                    'metrics': None,
                },
            ],
        },
        config={
            'base_url': 'https://private-gateway.example/internal?token=secret',
            'token': 'private-service-token',
            'configured': True,
            'verify_tls': True,
            'token_configured': True,
            'timeout_seconds': 12,
            'requests_per_minute': 30,
            'bind_attempts_per_10_minutes': 4,
        },
        audit={
            'events': [
                {
                    'timestamp': '2026-07-13T10:06:00Z',
                    'command': 'ip',
                    'outcome': 'success',
                    'reason': 'queried',
                    'group_id': 'private-group-openid',
                    'user_id': 'private-user-openid',
                    'member_id': 'private-member-id',
                    'request_id': 'private-request-id',
                    'duration_ms': 42,
                },
                {
                    'timestamp': '2026-07-13T10:05:00Z',
                    'command': 'unexpected-private-command',
                    'outcome': 'unexpected-private-outcome',
                    'reason': 'private-untrusted-reason',
                    'duration_ms': 5,
                },
            ]
        },
    )
    monkeypatch.setenv('LANBOT_BUILD_REVISION', 'a' * 40)
    monkeypatch.setenv('LANBOT_UPDATE_ENABLED', 'true')

    result = await IDCReadinessService(app).get_diagnostics()
    serialized = json.dumps(result, ensure_ascii=False)

    assert result['schema_version'] == 1
    assert result['application']['revision'] == 'a' * 40
    assert result['application']['managed_updates'] is True
    assert result['qq_callback']['configured_bots'] == 3
    assert result['qq_callback']['enabled_bots'] == 2
    assert result['qq_callback']['active_webhook_bots'] == 1
    assert result['qq_callback']['active_websocket_bots'] == 1
    assert result['qq_callback']['metrics']['events_total'] == 8
    assert result['qq_callback']['metrics']['pending_events'] == 3
    assert result['gateway'] == {
        'available': True,
        'configured': True,
        'transport': 'https',
        'verify_tls': True,
        'service_token_configured': True,
        'timeout_seconds': 12.0,
        'requests_per_minute': 30,
        'bind_attempts_per_10_minutes': 4,
    }
    assert result['audit']['sample_size'] == 2
    assert result['audit']['commands']['ip'] == 1
    assert result['audit']['commands']['unknown'] == 1
    assert result['audit']['outcomes']['success'] == 1
    assert result['audit']['outcomes']['unknown'] == 1
    assert result['audit']['reasons']['queried'] == 1
    assert result['audit']['reasons']['unknown'] == 1
    assert result['audit']['last_event'] == {
        'command': 'ip',
        'outcome': 'success',
        'reason': 'queried',
        'duration_ms': 42,
    }
    app.qqofficial_status_service.get_status.assert_awaited_once_with()
    app.idc_query_config_service.get_config.assert_awaited_once_with()
    app.idc_query_config_service.get_audit_events.assert_awaited_once_with(100)
    app.plugin_connector.ping_plugin_runtime.assert_awaited_once_with()
    app.plugin_connector.get_plugin_info.assert_awaited_once_with('csbsgyl', 'idc-query')
    assert all(secret not in serialized for secret in secrets)
    assert {
        'app_id',
        'uuid',
        'name',
        'configured_callback_url',
        'base_url',
        'token',
        'group_id',
        'user_id',
        'member_id',
        'request_id',
    }.isdisjoint(_all_keys(result))


@pytest.mark.asyncio
async def test_diagnostics_degrade_without_exposing_source_exceptions():
    secret = 'private-service-token at /private/idc/config.env'
    app = _make_app(
        qq_status=RuntimeError(secret),
        ping_result=RuntimeError(secret),
        config=OSError(secret),
        audit=UnicodeError(secret),
    )

    result = await IDCReadinessService(app).get_diagnostics()
    serialized = json.dumps(result)

    assert result['readiness']['available'] is True
    assert result['readiness']['status'] == 'not_ready'
    assert result['qq_callback']['available'] is False
    assert result['gateway']['available'] is False
    assert result['audit']['available'] is False
    assert secret not in serialized
    assert '/private/idc' not in serialized
