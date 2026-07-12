from pathlib import Path

import pytest
import yaml

from main import IDCQueryPlugin, _read_runtime_config


PLUGIN_MANIFEST = (
    Path(__file__).resolve().parents[3] / 'bundled_plugins' / 'idc_query' / 'manifest.yaml'
)


def test_runtime_config_preserves_token_with_equals(tmp_path):
    path = tmp_path / 'config.env'
    path.write_text(
        'IDC_QUERY_API_BASE_URL=https://query.example.com\nIDC_QUERY_API_TOKEN=abc==\n',
        encoding='utf-8',
    )

    config = _read_runtime_config(path)

    assert config['IDC_QUERY_API_BASE_URL'] == 'https://query.example.com'
    assert config['IDC_QUERY_API_TOKEN'] == 'abc=='


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


def test_manifest_config_fields_have_unique_ids_and_do_not_expose_token():
    manifest = yaml.safe_load(PLUGIN_MANIFEST.read_text(encoding='utf-8'))
    config_items = manifest['spec']['config']
    names = [item['name'] for item in config_items]
    ids = [item['id'] for item in config_items]

    assert ids == names
    assert len(ids) == len(set(ids))
    assert 'api_token' not in names
