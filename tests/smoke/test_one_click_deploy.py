from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
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


def create_deployment_archive(tmp_path: Path) -> Path:
    source = tmp_path / 'archive-source'
    (source / 'docker').mkdir(parents=True)
    (source / 'scripts').mkdir()
    (source / 'pyproject.toml').write_text('[project]\nname = "ai-lanbot"\n', encoding='utf-8')
    (source / 'docker' / 'docker-compose.yaml').write_text('services: {}\n', encoding='utf-8')
    (source / 'scripts' / 'one-click-deploy.sh').write_text('#!/usr/bin/env bash\n', encoding='utf-8')
    (source / 'new-source.txt').write_text('new source\n', encoding='utf-8')

    archive = tmp_path / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz') as file:
        file.add(source, arcname='ai-lanbot-revision')
    return archive


def create_managed_install(tmp_path: Path) -> Path:
    install_dir = tmp_path / 'ai-lanbot'
    (install_dir / 'docker' / 'data' / 'idc-query').mkdir(parents=True)
    (install_dir / 'scripts').mkdir()
    (install_dir / 'pyproject.toml').write_text('[project]\nname = "ai-lanbot"\n', encoding='utf-8')
    (install_dir / 'docker' / 'docker-compose.yaml').write_text('services: {}\n', encoding='utf-8')
    (install_dir / 'docker' / '.env').write_text('LANGBOT_HTTP_PORT=5300\n', encoding='utf-8')
    (install_dir / 'docker' / 'data' / 'idc-query' / 'bindings.json').write_text('{}\n', encoding='utf-8')
    (install_dir / 'scripts' / 'one-click-deploy.sh').write_text('#!/usr/bin/env bash\n', encoding='utf-8')
    (install_dir / 'old-source.txt').write_text('old source\n', encoding='utf-8')
    return install_dir


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


@pytest.mark.skipif(BASH is None, reason='bash is required to exercise existing deployment settings')
def test_repeat_deployment_reuses_resource_settings_and_respects_explicit_overrides(tmp_path):
    install_dir = create_managed_install(tmp_path)
    (install_dir / 'docker' / '.env').write_text(
        '\n'.join(
            (
                'COMPOSE_PROJECT_NAME=existing-project',
                'LANGBOT_HTTP_PORT=6300',
                'LANBOT_CONTAINER_NAME=existing-langbot',
                'LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME=existing-plugin-runtime',
                'LANBOT_BOX_CONTAINER_NAME=existing-box',
                'LANBOT_PLUGIN_DEBUG_PORT=6401',
                'LANBOT_REVERSE_PORT_MAPPING=7280-7285:2280-2285',
                'LANBOT_BOX_ENABLED=true',
                'LANBOT_SOURCE_MODE=git',
                '',
            )
        ),
        encoding='utf-8',
    )
    command = r"""
source "$1"
INSTALL_DIR="$2"
load_existing_deployment_settings
printf '%s\n' \
  "$COMPOSE_PROJECT" \
  "$HTTP_PORT" \
  "$LANGBOT_CONTAINER_NAME" \
  "$PLUGIN_RUNTIME_CONTAINER_NAME" \
  "$BOX_CONTAINER_NAME" \
  "$PLUGIN_DEBUG_PORT" \
  "$REVERSE_PORT_MAPPING" \
  "$COMPOSE_PROFILES" \
  "$SOURCE_MODE"
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith('LANBOT_')}
    env['PATH'] = os.pathsep.join((str(Path(BASH).parent), env.get('PATH', '')))

    reused = subprocess.run(
        [BASH, '-c', command, 'deployment-test', str(DEPLOY_SCRIPT), str(install_dir)],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    ).stdout.splitlines()
    overridden = subprocess.run(
        [BASH, '-c', command, 'deployment-test', str(DEPLOY_SCRIPT), str(install_dir)],
        check=True,
        capture_output=True,
        env={
            **env,
            'LANBOT_HTTP_PORT': '7300',
            'LANBOT_CONTAINER_NAME': 'override-langbot',
            'LANBOT_COMPOSE_PROFILES': '',
        },
        text=True,
    ).stdout.splitlines()

    assert reused[-9:] == [
        'existing-project',
        '6300',
        'existing-langbot',
        'existing-plugin-runtime',
        'existing-box',
        '6401',
        '7280-7285:2280-2285',
        'all',
        'git',
    ]
    assert overridden[-9:] == [
        'existing-project',
        '7300',
        'override-langbot',
        'existing-plugin-runtime',
        'existing-box',
        '6401',
        '7280-7285:2280-2285',
        '',
        'git',
    ]


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


def test_runtime_image_is_preflighted_before_source_replacement():
    script = DEPLOY_SCRIPT.read_text(encoding='utf-8')
    main_body = script.split('main() {', maxsplit=1)[1]

    assert main_body.index('runtime_image="$(resolve_runtime_image)"') < main_body.index('\n  fetch_source')
    assert main_body.index('prepare_runtime_image "$runtime_image"') < main_body.index('\n  fetch_source')
    assert 'acquire_deployment_lock' in main_body


def test_host_updater_files_are_installed_atomically():
    script = DEPLOY_SCRIPT.read_text(encoding='utf-8')

    assert 'install_root_file_atomically "${INSTALL_DIR}/scripts/host-update.sh" "$HOST_UPDATER_PATH" 0755' in script
    assert 'as_root install -m 0755 "${INSTALL_DIR}/scripts/host-update.sh" "$HOST_UPDATER_PATH"' not in script


@pytest.mark.skipif(BASH is None, reason='bash is required to exercise staged source replacement')
def test_archive_upgrade_preserves_data_and_environment(tmp_path):
    archive = create_deployment_archive(tmp_path)
    install_dir = create_managed_install(tmp_path)
    command = r"""
source "$1"
INSTALL_DIR="$2"
ARCHIVE="$3"
download_archive() { cp "$ARCHIVE" "$1"; }
install_from_archive
"""

    subprocess.run(
        [BASH, '-c', command, 'deployment-test', str(DEPLOY_SCRIPT), str(install_dir), str(archive)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (install_dir / 'new-source.txt').read_text(encoding='utf-8') == 'new source\n'
    assert not (install_dir / 'old-source.txt').exists()
    assert (install_dir / 'docker' / '.env').read_text(encoding='utf-8') == 'LANGBOT_HTTP_PORT=5300\n'
    assert (install_dir / 'docker' / 'data' / 'idc-query' / 'bindings.json').read_text(encoding='utf-8') == '{}\n'
    assert not list(tmp_path.glob('.ai-lanbot.stage.*'))
    assert not list(tmp_path.glob('.ai-lanbot.backup.*'))


@pytest.mark.skipif(BASH is None, reason='bash is required to exercise staged source rollback')
def test_archive_upgrade_restores_previous_install_when_activation_fails(tmp_path):
    archive = create_deployment_archive(tmp_path)
    install_dir = create_managed_install(tmp_path)
    command = r"""
source "$1"
INSTALL_DIR="$2"
ARCHIVE="$3"
download_archive() { cp "$ARCHIVE" "$1"; }
mv() {
  if [ "$#" -eq 2 ] && [ "$2" = "$INSTALL_DIR" ] && [[ "$1" == *'.ai-lanbot.stage.'* ]]; then
    return 1
  fi
  command mv "$@"
}
install_from_archive
"""

    result = subprocess.run(
        [BASH, '-c', command, 'deployment-test', str(DEPLOY_SCRIPT), str(install_dir), str(archive)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (install_dir / 'old-source.txt').read_text(encoding='utf-8') == 'old source\n'
    assert not (install_dir / 'new-source.txt').exists()
    assert (install_dir / 'docker' / '.env').read_text(encoding='utf-8') == 'LANGBOT_HTTP_PORT=5300\n'
    assert (install_dir / 'docker' / 'data' / 'idc-query' / 'bindings.json').read_text(encoding='utf-8') == '{}\n'
    assert not list(tmp_path.glob('.ai-lanbot.stage.*'))
    assert not list(tmp_path.glob('.ai-lanbot.backup.*'))


def test_deployment_prints_qq_callback_reverse_proxy_details():
    script = DEPLOY_SCRIPT.read_text(encoding='utf-8')

    assert 'QQ callback upstream (reverse proxy on this server): ${local_url}' in script
    assert 'QQ callback upstream (reverse proxy on another server): ${remote_url}' in script
    assert 'QQ callback upstream: ${local_url}/qq/callback' in script
    assert 'https://<your-domain>/qq/callback' in script
    assert 'Backup: ${INSTALL_DIR}/scripts/data-backup.sh create ${INSTALL_DIR}' in script
    assert 'Restore: ${INSTALL_DIR}/scripts/data-backup.sh restore <archive.tar.gz> ${INSTALL_DIR}' in script


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
