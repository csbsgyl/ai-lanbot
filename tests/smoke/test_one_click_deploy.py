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
    env['PATH'] = os.pathsep.join((str(Path(BASH).parent), env.get('PATH', '')))
    command = r"""
source "$1"
shift
parse_args "$@"
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


def test_production_is_the_only_default_deployment():
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


def test_production_alias_preserves_the_same_defaults():
    default_config = resolve_deployment()
    explicit_config = resolve_deployment('production')

    assert explicit_config == default_config


def test_test_deployment_mode_is_rejected():
    if BASH is None:
        pytest.skip('bash is required to exercise the Linux deployment script')

    command = 'source "$1"; shift; parse_args "$@"'
    result = subprocess.run(
        [BASH, '-c', command, 'deployment-test', str(DEPLOY_SCRIPT), 'test'],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert 'production only' in result.stderr


def test_target_revision_pins_the_downloaded_source():
    if BASH is None:
        pytest.skip('bash is required to exercise the Linux deployment script')

    revision = 'a' * 40
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join((str(Path(BASH).parent), env.get('PATH', '')))
    command = rf'''
source "$1"
curl() {{ printf '%s' "{revision}"; }}
resolve_target_revision
printf '%s\n' "$TARGET_REVISION"
repository_archive_url "https://github.com"
'''
    result = subprocess.run(
        [BASH, '-c', command, 'deployment-test', str(DEPLOY_SCRIPT)],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.stdout.splitlines() == [
        revision,
        f'https://github.com/csbsgyl/ai-lanbot/archive/{revision}.tar.gz',
    ]


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
    assert 'LANBOT_UPDATE_ENABLED=${LANBOT_UPDATE_ENABLED:-false}' in services['langbot']['environment']
    assert './data/update:/app/data/update:ro' in services['langbot']['volumes']

    expected_ports = [
        '${LANGBOT_HTTP_PORT:-5300}:5300',
        '${LANBOT_REVERSE_PORT_MAPPING:-2280-2285:2280-2285}',
    ]
    assert services['langbot']['ports'] == expected_ports
    assert local_build['services']['langbot']['ports'] == expected_ports


def test_host_updater_is_fixed_to_the_managed_deployment():
    service_template = (ROOT / 'deploy' / 'systemd' / 'ai-lanbot-update.service.in').read_text(encoding='utf-8')
    path_template = (ROOT / 'deploy' / 'systemd' / 'ai-lanbot-update.path.in').read_text(encoding='utf-8')
    host_script = (ROOT / 'scripts' / 'host-update.sh').read_text(encoding='utf-8')

    assert 'ExecStart=/usr/bin/env bash /usr/local/libexec/ai-lanbot-host-update @INSTALL_DIR@' in service_template
    assert 'PathModified=@INSTALL_DIR@/docker/data/update-request/request.json' in path_template
    assert 'csbsgyl/ai-lanbot' in host_script
    assert 'raw.githubusercontent.com/${REPO_SLUG}/${TARGET_REVISION}' in host_script
    assert 'LANBOT_ALLOW_BUILD_FALLBACK="false"' in host_script
    assert '/var/run/docker.sock' not in host_script
    assert 'LANBOT_HTTP_PORT' in host_script
    assert 'LANBOT_COMPOSE_PROFILES' in host_script


def test_deployment_prints_qq_callback_reverse_proxy_details():
    script = DEPLOY_SCRIPT.read_text(encoding='utf-8')

    assert 'QQ callback upstream (reverse proxy on this server): ${local_url}' in script
    assert 'QQ callback upstream (reverse proxy on another server): ${remote_url}' in script
    assert 'QQ callback upstream: ${local_url}/qq/callback' in script
    assert 'https://<your-domain>/qq/callback' in script


def test_systemd_updater_rejects_unsafe_install_paths():
    if BASH is None:
        pytest.skip('bash is required to exercise the Linux deployment script')

    command = r"""
source "$1"
INSTALL_DIR=/opt/ai-lanbot
is_safe_systemd_install_dir
INSTALL_DIR='/opt/ai lanbot'
! is_safe_systemd_install_dir
INSTALL_DIR='/opt/../etc'
! is_safe_systemd_install_dir
INSTALL_DIR='relative/path'
! is_safe_systemd_install_dir
"""
    subprocess.run(
        [BASH, '-c', command, 'deployment-test', str(DEPLOY_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
    )
