from __future__ import annotations

import os
import stat

import pytest

from langbot.pkg.api.http.service.idc_query_config import (
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
    }


@pytest.mark.asyncio
async def test_update_writes_config_without_returning_token(config_service: IDCQueryConfigService):
    config = await config_service.update_config(
        {
            'base_url': 'https://query.example.com/',
            'token': 'service-token==',
            'timeout_seconds': 12,
            'verify_tls': False,
        }
    )

    assert config == {
        'base_url': 'https://query.example.com',
        'timeout_seconds': 12.0,
        'verify_tls': False,
        'token_configured': True,
        'configured': True,
    }
    assert 'token' not in config
    assert config_service.config_path.read_text(encoding='utf-8') == (
        'IDC_QUERY_API_BASE_URL=https://query.example.com\n'
        'IDC_QUERY_API_TOKEN=service-token==\n'
        'IDC_QUERY_TIMEOUT_SECONDS=12\n'
        'IDC_QUERY_VERIFY_TLS=false\n'
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
