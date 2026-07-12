from __future__ import annotations

import json
import os
import stat

import pytest

from langbot.pkg.api.http.service import idc_query_config
from langbot.pkg.api.http.service.idc_query_config import (
    IDCQueryBindingStateError,
    IDCQueryConfigService,
    IDCQueryConfigValidationError,
)
from tests.factories import FakeApp


@pytest.fixture
def config_service(tmp_path, monkeypatch: pytest.MonkeyPatch) -> IDCQueryConfigService:
    monkeypatch.setenv('LANGBOT_DATA_ROOT', str(tmp_path))
    return IDCQueryConfigService(FakeApp())


@pytest.mark.asyncio
async def test_empty_config_uses_secure_defaults(config_service: IDCQueryConfigService):
    config = await config_service.get_config()

    assert config == {
        'base_url': '',
        'timeout_seconds': 8.0,
        'verify_tls': True,
        'token_configured': False,
        'configured': False,
        'requests_per_minute': 20,
        'bind_attempts_per_10_minutes': 5,
    }


@pytest.mark.asyncio
async def test_update_writes_config_without_returning_token(config_service: IDCQueryConfigService):
    config = await config_service.update_config(
        {
            'base_url': 'https://query.example.com/',
            'token': 'service-token==',
            'timeout_seconds': 12,
            'verify_tls': False,
            'requests_per_minute': 30,
            'bind_attempts_per_10_minutes': 4,
        }
    )

    assert config == {
        'base_url': 'https://query.example.com',
        'timeout_seconds': 12.0,
        'verify_tls': False,
        'token_configured': True,
        'configured': True,
        'requests_per_minute': 30,
        'bind_attempts_per_10_minutes': 4,
    }
    assert 'token' not in config
    assert config_service.config_path.read_text(encoding='utf-8') == (
        'IDC_QUERY_API_BASE_URL=https://query.example.com\n'
        'IDC_QUERY_API_TOKEN=service-token==\n'
        'IDC_QUERY_TIMEOUT_SECONDS=12\n'
        'IDC_QUERY_VERIFY_TLS=false\n'
        'IDC_QUERY_REQUESTS_PER_MINUTE=30\n'
        'IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES=4\n'
    )
    if os.name != 'nt':
        assert stat.S_IMODE(config_service.config_path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_blank_token_preserves_existing_token_and_explicit_clear_removes_it(
    config_service: IDCQueryConfigService,
):
    await config_service.update_config({'token': 'keep-this-token'})

    preserved = await config_service.update_config({'base_url': 'http://gateway.internal', 'token': ''})
    assert preserved['token_configured'] is True
    assert 'IDC_QUERY_API_TOKEN=keep-this-token\n' in config_service.config_path.read_text(encoding='utf-8')

    cleared = await config_service.update_config({'clear_token': True})
    assert cleared['token_configured'] is False
    assert 'IDC_QUERY_API_TOKEN=\n' in config_service.config_path.read_text(encoding='utf-8')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('payload', 'message'),
    [
        ({'base_url': 'ftp://query.example.com'}, 'HTTP or HTTPS'),
        ({'base_url': 'https://user:pass@query.example.com'}, 'HTTP or HTTPS'),
        ({'base_url': 'https://query.example.com?token=secret'}, 'HTTP or HTTPS'),
        ({'timeout_seconds': 0}, 'between 1 and 120'),
        ({'timeout_seconds': True}, 'must be a number'),
        ({'verify_tls': 'true'}, 'must be a boolean'),
        ({'requests_per_minute': 0}, 'between 1 and 1000'),
        ({'requests_per_minute': True}, 'must be an integer'),
        ({'bind_attempts_per_10_minutes': 1001}, 'between 1 and 1000'),
        ({'token': 'invalid\ttoken'}, 'token is invalid'),
        ({'unknown': 'value'}, 'unsupported fields'),
        ({'token': 'replacement', 'clear_token': True}, 'replaced and cleared'),
    ],
)
async def test_invalid_updates_are_rejected_without_changing_file(
    config_service: IDCQueryConfigService,
    payload: dict,
    message: str,
):
    await config_service.update_config({'base_url': 'https://query.example.com', 'token': 'original-token'})
    original = config_service.config_path.read_bytes()

    with pytest.raises(IDCQueryConfigValidationError, match=message):
        await config_service.update_config(payload)

    assert config_service.config_path.read_bytes() == original


@pytest.mark.asyncio
async def test_non_object_request_is_rejected(config_service: IDCQueryConfigService):
    with pytest.raises(IDCQueryConfigValidationError, match='JSON object'):
        await config_service.update_config(None)


@pytest.mark.asyncio
async def test_audit_reader_returns_latest_valid_events_across_rotated_files(config_service: IDCQueryConfigService):
    audit_path = config_service.config_path.parent / 'audit.jsonl'
    audit_path.parent.mkdir(parents=True)
    current_events = [
        {
            'timestamp': '2026-07-12T10:02:00+00:00',
            'command': 'ip',
            'outcome': 'success',
            'reason': 'queried',
            'group_id': 'group-1',
            'user_id': 'user-1',
            'member_id': 'member-1',
            'request_id': 'request-2',
            'duration_ms': 12,
        },
        {
            'timestamp': '2026-07-12T10:03:00+00:00',
            'command': 'balance',
            'outcome': 'denied',
            'reason': 'binder_required',
            'group_id': 'group-1\nignored',
            'user_id': 'user-2',
            'member_id': 'member-1',
            'request_id': 'request-3',
            'duration_ms': 4,
        },
    ]
    audit_path.write_text(
        '\n'.join(json.dumps(event) for event in current_events) + '\n{broken}\n',
        encoding='utf-8',
    )
    audit_path.with_name('audit.jsonl.1').write_text(
        json.dumps(
            {
                'timestamp': '2026-07-12T10:01:00+00:00',
                'command': 'bind',
                'outcome': 'success',
                'reason': 'bound',
                'group_id': 'group-1',
                'user_id': 'user-1',
                'member_id': 'member-1',
                'request_id': 'request-1',
                'duration_ms': 30,
            }
        )
        + '\n',
        encoding='utf-8',
    )

    result = await config_service.get_audit_events(3)

    assert result['count'] == 3
    assert [event['request_id'] for event in result['events']] == ['request-3', 'request-2', 'request-1']
    assert result['events'][0]['group_id'] == 'group-1ignored'
    assert result['generated_at']


@pytest.mark.asyncio
async def test_audit_reader_rejects_unknown_schema_and_invalid_limit(config_service: IDCQueryConfigService):
    audit_path = config_service.config_path.parent / 'audit.jsonl'
    audit_path.parent.mkdir(parents=True)
    audit_path.write_text(
        json.dumps({'command': 'custom', 'outcome': 'success', 'token': 'must-not-leak'}) + '\n',
        encoding='utf-8',
    )

    assert (await config_service.get_audit_events())['events'] == []
    with pytest.raises(IDCQueryConfigValidationError, match='between 1 and 200'):
        await config_service.get_audit_events(201)


@pytest.mark.asyncio
async def test_binding_reader_returns_latest_valid_bindings(config_service: IDCQueryConfigService):
    binding_path = config_service.config_path.parent / 'bindings.json'
    binding_path.parent.mkdir(parents=True)
    binding_path.write_text(
        json.dumps(
            {
                'version': 1,
                'bindings': {
                    'group-1': {
                        'group_id': 'group-1',
                        'member_id': 'member-1',
                        'bound_by': 'user-1',
                        'bound_at': '2026-07-12T10:01:00+00:00',
                        'member_name': 'Customer One',
                    },
                    'group-2': {
                        'group_id': 'group-2',
                        'member_id': 'member-2',
                        'bound_by': 'user-2',
                        'bound_at': '2026-07-12T10:02:00+00:00',
                        'member_name': 'Customer Two\nIgnored',
                    },
                    'group-invalid': {
                        'group_id': 'different-group',
                        'member_id': 'member-3',
                        'bound_by': 'user-3',
                        'bound_at': '2026-07-12T10:03:00+00:00',
                    },
                },
            }
        ),
        encoding='utf-8',
    )

    result = await config_service.get_bindings(1)

    assert result['count'] == 1
    assert result['total'] == 2
    assert result['bindings'] == [
        {
            'group_id': 'group-2',
            'member_id': 'member-2',
            'bound_by': 'user-2',
            'bound_at': '2026-07-12T10:02:00+00:00',
            'member_name': 'Customer TwoIgnored',
        }
    ]
    assert result['generated_at']


@pytest.mark.asyncio
async def test_binding_reader_handles_missing_file_and_rejects_invalid_state(config_service: IDCQueryConfigService):
    assert (await config_service.get_bindings())['bindings'] == []

    binding_path = config_service.config_path.parent / 'bindings.json'
    binding_path.parent.mkdir(parents=True)
    binding_path.write_text('{broken', encoding='utf-8')
    with pytest.raises(IDCQueryBindingStateError, match='invalid'):
        await config_service.get_bindings()

    with pytest.raises(IDCQueryConfigValidationError, match='between 1 and 500'):
        await config_service.get_bindings(501)


@pytest.mark.asyncio
async def test_binding_reader_rejects_oversized_state(
    config_service: IDCQueryConfigService,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(idc_query_config, 'MAX_BINDINGS_FILE_BYTES', 16)
    binding_path = config_service.config_path.parent / 'bindings.json'
    binding_path.parent.mkdir(parents=True)
    binding_path.write_bytes(b'{' + b' ' * 16 + b'}')

    with pytest.raises(IDCQueryBindingStateError, match='supported size'):
        await config_service.get_bindings()
