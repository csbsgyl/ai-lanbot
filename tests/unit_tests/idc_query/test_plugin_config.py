from pathlib import Path

import pytest
import yaml

from main import IDCQueryPlugin, _as_bool, _read_runtime_config


PLUGIN_MANIFEST = Path(__file__).resolve().parents[3] / 'bundled_plugins' / 'idc_query' / 'manifest.yaml'


def test_runtime_config_preserves_token_with_equals(tmp_path):
    path = tmp_path / 'config.env'
    path.write_text(
        'IDC_QUERY_API_BASE_URL=https://query.example.com\nIDC_QUERY_API_TOKEN=abc==\n',
        encoding='utf-8',
    )

    config = _read_runtime_config(path)

    assert config['IDC_QUERY_API_BASE_URL'] == 'https://query.example.com'
    assert config['IDC_QUERY_API_TOKEN'] == 'abc=='


def test_invalid_boolean_config_uses_secure_default():
    assert _as_bool('invalid', True) is True
    assert _as_bool('invalid', False) is False


@pytest.mark.asyncio
async def test_plugin_loads_secure_runtime_config_file(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.env'
    state_path = tmp_path / 'bindings.json'
    config_path.write_text(
        'IDC_QUERY_API_BASE_URL=https://query.example.com\n'
        'IDC_QUERY_API_TOKEN=service-token\n'
        'IDC_QUERY_TIMEOUT_SECONDS=12\n'
        'IDC_QUERY_VERIFY_TLS=false\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('IDC_QUERY_CONFIG_PATH', str(config_path))
    monkeypatch.setenv('IDC_QUERY_STATE_PATH', str(state_path))

    plugin = IDCQueryPlugin()
    plugin.config = {
        'api_base_url': '',
        'timeout_seconds': 8,
        'verify_tls': True,
        'exclusive_mode': True,
        'sensitive_binder_only': True,
        'allow_simulated_events': False,
    }
    await plugin.initialize()

    gateway = plugin.idc_query_service.gateway
    assert gateway.base_url == 'https://query.example.com'
    assert gateway.token == 'service-token'
    assert gateway.timeout_seconds == 12
    assert gateway.verify_tls is False
    assert plugin.idc_query_service.store.path == state_path


@pytest.mark.asyncio
async def test_plugin_hot_reloads_runtime_gateway_config(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.env'
    state_path = tmp_path / 'bindings.json'
    config_path.write_text(
        'IDC_QUERY_API_BASE_URL=https://old-query.example.com\n'
        'IDC_QUERY_API_TOKEN=old-token\n'
        'IDC_QUERY_TIMEOUT_SECONDS=8\n'
        'IDC_QUERY_VERIFY_TLS=true\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('IDC_QUERY_CONFIG_PATH', str(config_path))
    monkeypatch.setenv('IDC_QUERY_STATE_PATH', str(state_path))

    plugin = IDCQueryPlugin()
    plugin.config = {
        'exclusive_mode': True,
        'sensitive_binder_only': True,
        'allow_simulated_events': False,
    }
    await plugin.initialize()
    old_gateway = plugin.idc_query_service.gateway

    config_path.write_text(
        'IDC_QUERY_API_BASE_URL=https://new-query.example.com/api\n'
        'IDC_QUERY_API_TOKEN=new-token==\n'
        'IDC_QUERY_TIMEOUT_SECONDS=15\n'
        'IDC_QUERY_VERIFY_TLS=false\n',
        encoding='utf-8',
    )
    result = await plugin.handle_idc_query(
        text='帮助',
        group_id='group-1',
        user_id='user-1',
        message_id='message-1',
    )

    gateway = plugin.idc_query_service.gateway
    assert result.handled is True
    assert gateway is not old_gateway
    assert gateway.base_url == 'https://new-query.example.com/api'
    assert gateway.token == 'new-token=='
    assert gateway.timeout_seconds == 15
    assert gateway.verify_tls is False


@pytest.mark.asyncio
async def test_plugin_keeps_last_valid_gateway_when_hot_reload_is_invalid(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.env'
    state_path = tmp_path / 'bindings.json'
    config_path.write_text(
        'IDC_QUERY_API_BASE_URL=https://query.example.com\nIDC_QUERY_TIMEOUT_SECONDS=8\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('IDC_QUERY_CONFIG_PATH', str(config_path))
    monkeypatch.setenv('IDC_QUERY_STATE_PATH', str(state_path))

    plugin = IDCQueryPlugin()
    plugin.config = {}
    await plugin.initialize()
    old_gateway = plugin.idc_query_service.gateway

    config_path.write_text(
        'IDC_QUERY_API_BASE_URL=https://query.example.com\nIDC_QUERY_TIMEOUT_SECONDS=invalid\n',
        encoding='utf-8',
    )
    result = await plugin.handle_idc_query(
        text='帮助',
        group_id='group-1',
        user_id='user-1',
        message_id='message-2',
    )

    assert result.handled is True
    assert plugin.idc_query_service.gateway is old_gateway


def test_manifest_config_fields_have_unique_ids_and_do_not_expose_token():
    manifest = yaml.safe_load(PLUGIN_MANIFEST.read_text(encoding='utf-8'))
    config_items = manifest['spec']['config']
    names = [item['name'] for item in config_items]
    ids = [item['id'] for item in config_items]

    assert ids == names
    assert len(ids) == len(set(ids))
    assert 'api_token' not in names
