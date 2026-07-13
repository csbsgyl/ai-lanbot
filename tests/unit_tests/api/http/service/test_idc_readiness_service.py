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
