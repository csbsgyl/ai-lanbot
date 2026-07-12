from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = ROOT / 'scripts' / 'one-click-deploy.sh'
BASH = os.environ.get('BASH') or shutil.which('bash')
CONFIG_KEYS = (
    'environment',
    'mode',
    'install_dir',
    'http_port',
    'compose_project',
    'langbot_container',
    'plugin_container',
    'box_container',
    'plugin_debug_port',
    'reverse_port_mapping',
)


def resolve_deployment(*args: str, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    if BASH is None:
        pytest.skip('bash is required to exercise the Linux deployment script')

    env = {key: value for key, value in os.environ.items() if not key.startswith('LANBOT_')}
    env.update(extra_env or {})
    command = r"""
source "$1"
shift
parse_args "$@"
configure_deployment
printf '%s\n' \
  "$DEPLOY_ENVIRONMENT" \
  "$DEPLOY_MODE" \
  "$INSTALL_DIR" \
  "$HTTP_PORT" \
  "$COMPOSE_PROJECT" \
  "$LANGBOT_CONTAINER_NAME" \
  "$PLUGIN_RUNTIME_CONTAINER_NAME" \
  "$BOX_CONTAINER_NAME" \
  "$PLUGIN_DEBUG_PORT" \
  "$REVERSE_PORT_MAPPING"
"""
    result = subprocess.run(
        [BASH, '-c', command, 'deployment-test', str(DEPLOY_SCRIPT), *args],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )
    return dict(zip(CONFIG_KEYS, result.stdout.splitlines(), strict=True))


def test_test_mode_uses_isolated_source_build_defaults():
    config = resolve_deployment('test')

    assert config == {
        'environment': 'test',
        'mode': 'build',
        'install_dir': config['install_dir'],
        'http_port': '5301',
        'compose_project': 'ai-lanbot-test',
        'langbot_container': 'langbot_test',
        'plugin_container': 'langbot_plugin_runtime_test',
        'box_container': 'langbot_box_test',
        'plugin_debug_port': '5402',
        'reverse_port_mapping': '3280-3285:2280-2285',
    }
    assert config['install_dir'].endswith('/ai-lanbot-test')


def test_production_mode_is_the_backward_compatible_default():
    config = resolve_deployment()

    assert config == {
        'environment': 'production',
        'mode': 'image',
        'install_dir': config['install_dir'],
        'http_port': '5300',
        'compose_project': 'docker',
        'langbot_container': 'langbot',
        'plugin_container': 'langbot_plugin_runtime',
        'box_container': 'langbot_box',
        'plugin_debug_port': '5401',
        'reverse_port_mapping': '2280-2285:2280-2285',
    }
    assert config['install_dir'].endswith('/ai-lanbot')


def test_explicit_mode_takes_precedence_over_environment_default():
    config = resolve_deployment('test', extra_env={'LANBOT_ENVIRONMENT': 'production'})

    assert config['environment'] == 'test'
    assert config['mode'] == 'build'
    assert config['http_port'] == '5301'


def test_compose_files_parameterize_environment_specific_resources():
    with (ROOT / 'docker' / 'docker-compose.yaml').open(encoding='utf-8') as file:
        compose = yaml.safe_load(file)
    with (ROOT / 'docker' / 'docker-compose.local-build.yaml').open(encoding='utf-8') as file:
        local_build = yaml.safe_load(file)

    services = compose['services']
    assert services['langbot']['container_name'] == '${LANBOT_CONTAINER_NAME:-langbot}'
    assert services['langbot_plugin_runtime']['container_name'] == (
        '${LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME:-langbot_plugin_runtime}'
    )
    assert services['langbot_box']['container_name'] == '${LANBOT_BOX_CONTAINER_NAME:-langbot_box}'
    assert services['langbot_plugin_runtime']['ports'] == ['${LANBOT_PLUGIN_DEBUG_PORT:-5401}:5401']

    expected_ports = [
        '${LANGBOT_HTTP_PORT:-5300}:5300',
        '${LANBOT_REVERSE_PORT_MAPPING:-2280-2285:2280-2285}',
    ]
    assert services['langbot']['ports'] == expected_ports
    assert local_build['services']['langbot']['ports'] == expected_ports
