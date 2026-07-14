from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import tarfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = ROOT / 'scripts' / 'data-backup.sh'
BASH = os.environ.get('BASH') or shutil.which('bash')
ARCHIVE_PATTERN = re.compile(
    r'^ai-lanbot-20260714T120000Z-(?P<sequence>\d{6})-(?P<revision>[0-9a-f]{12}|unknown)\.tar\.gz$'
)


@dataclass(frozen=True)
class BackupHarness:
    install_dir: Path
    backup_dir: Path
    control_dir: Path
    command_log: Path
    env: dict[str, str]

    def create(self) -> subprocess.CompletedProcess[str]:
        assert BASH is not None
        return subprocess.run(
            [BASH, str(BACKUP_SCRIPT), 'create', str(self.install_dir)],
            capture_output=True,
            env=self.env,
            text=True,
        )

    def restore(self, archive: Path) -> subprocess.CompletedProcess[str]:
        assert BASH is not None
        return subprocess.run(
            [BASH, str(BACKUP_SCRIPT), 'restore', str(archive), str(self.install_dir)],
            capture_output=True,
            env=self.env,
            text=True,
        )

    def archives(self) -> list[Path]:
        return sorted(
            archive for archive in self.backup_dir.glob('ai-lanbot-*.tar.gz') if ARCHIVE_PATTERN.fullmatch(archive.name)
        )


pytestmark = pytest.mark.skipif(BASH is None, reason='bash is required to exercise the Linux backup script')


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding='utf-8')
    path.chmod(0o755)


def create_harness(tmp_path: Path, *, backend: str = 'sqlite') -> BackupHarness:
    assert BASH is not None
    install_dir = tmp_path / 'ai-lanbot'
    data_dir = install_dir / 'docker' / 'data'
    scripts_dir = install_dir / 'scripts'
    fake_bin = tmp_path / 'fake-bin'
    control_dir = tmp_path / 'control'
    backup_dir = tmp_path / 'backups'
    command_log = tmp_path / 'docker-commands.log'

    data_dir.mkdir(parents=True)
    scripts_dir.mkdir()
    fake_bin.mkdir()
    control_dir.mkdir()
    (install_dir / 'pyproject.toml').write_text('[project]\nname = "ai-lanbot"\n', encoding='utf-8')
    (install_dir / 'docker' / 'docker-compose.yaml').write_text('services: {}\n', encoding='utf-8')
    (install_dir / 'docker' / '.env').write_text(
        f'LANGBOT_HTTP_PORT=5300\nLANBOT_BUILD_REVISION={"a" * 40}\n',
        encoding='utf-8',
    )
    (data_dir / 'config.yaml').write_text(f'database:\n    use: {backend}\n', encoding='utf-8')
    (data_dir / 'value.txt').write_text('old\n', encoding='utf-8')
    (data_dir / 'value-link.txt').symlink_to('value.txt')
    shutil.copy2(BACKUP_SCRIPT, scripts_dir / 'data-backup.sh')
    (scripts_dir / 'data-backup.sh').chmod(0o755)

    real_mv = shutil.which('mv')
    real_date = shutil.which('date')
    assert real_mv is not None
    assert real_date is not None

    write_executable(
        fake_bin / 'docker',
        r"""
        #!/usr/bin/env bash
        set -eu
        printf '%s\n' "$*" >> "$TEST_COMMAND_LOG"
        if [ "${1:-}" = 'compose' ] && [ "${2:-}" = 'version' ]; then
          exit 0
        fi
        case " $* " in
          *' ps --services '*) printf '%s\n' "${TEST_RUNNING_SERVICES-langbot}" ;;
          *' stop '*) [ ! -f "$TEST_CONTROL_DIR/fail-stop" ] || exit 1 ;;
          *' start '*) [ ! -f "$TEST_CONTROL_DIR/fail-start" ] || exit 1 ;;
        esac
        """,
    )
    write_executable(
        fake_bin / 'curl',
        r"""
        #!/usr/bin/env bash
        set -eu
        if [ -f "$TEST_CONTROL_DIR/fail-health-value" ]; then
          current_value="$(cat "$TEST_INSTALL_DIR/docker/data/value.txt" 2>/dev/null || true)"
          failed_value="$(cat "$TEST_CONTROL_DIR/fail-health-value")"
          [ "$current_value" != "$failed_value" ] || exit 1
        fi
        exit 0
        """,
    )
    write_executable(
        fake_bin / 'date',
        r"""
        #!/usr/bin/env bash
        set -eu
        case "${2:-}" in
          '+%Y%m%dT%H%M%SZ') printf '%s\n' '20260714T120000Z' ;;
          '+%Y-%m-%dT%H:%M:%SZ') printf '%s\n' '2026-07-14T12:00:00Z' ;;
          *) exec "$TEST_REAL_DATE" "$@" ;;
        esac
        """,
    )
    write_executable(
        fake_bin / 'sleep',
        r"""
        #!/usr/bin/env bash
        exit 0
        """,
    )
    write_executable(
        fake_bin / 'mv',
        r"""
        #!/usr/bin/env bash
        set -eu
        source_path="${1:-}"
        destination_path="${2:-}"
        if [[ "$source_path" == *'/.restore-stage.'*'/docker/data' ]] \
          && [ "$destination_path" = "$TEST_INSTALL_DIR/docker/data" ] \
          && [ -f "$TEST_CONTROL_DIR/fail-activate" ]; then
          exit 1
        fi
        if [[ "$source_path" == *'/.restore-current.'*'/data' ]] \
          && [ "$destination_path" = "$TEST_INSTALL_DIR/docker/data" ]; then
          if [ -f "$TEST_CONTROL_DIR/fail-original-always" ]; then
            exit 1
          fi
          if [ -f "$TEST_CONTROL_DIR/fail-original-once" ] \
            && [ ! -f "$TEST_CONTROL_DIR/original-move-failed" ]; then
            : > "$TEST_CONTROL_DIR/original-move-failed"
            exit 1
          fi
        fi
        exec "$TEST_REAL_MV" "$@"
        """,
    )

    env = {key: value for key, value in os.environ.items() if not key.startswith('LANBOT_')}
    env.update(
        {
            'PATH': os.pathsep.join((str(fake_bin), env.get('PATH', ''))),
            'LANBOT_BACKUP_DIR': str(backup_dir),
            'TEST_COMMAND_LOG': str(command_log),
            'TEST_CONTROL_DIR': str(control_dir),
            'TEST_INSTALL_DIR': str(install_dir),
            'TEST_REAL_DATE': real_date,
            'TEST_REAL_MV': real_mv,
        }
    )
    return BackupHarness(install_dir, backup_dir, control_dir, command_log, env)


def archive_sequence(archive: Path) -> int:
    match = ARCHIVE_PATTERN.fullmatch(archive.name)
    assert match is not None
    return int(match.group('sequence'))


def test_create_writes_consistent_private_archive_and_checksum(tmp_path: Path):
    harness = create_harness(tmp_path)

    result = harness.create()

    assert result.returncode == 0, result.stderr
    [archive] = harness.archives()
    assert archive_sequence(archive) == 0
    assert ARCHIVE_PATTERN.fullmatch(archive.name).group('revision') == 'a' * 12
    checksum_file = Path(f'{archive}.sha256')
    expected_checksum, referenced_name = checksum_file.read_text(encoding='utf-8').split()
    assert expected_checksum == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert referenced_name == archive.name
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(checksum_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(harness.backup_dir.stat().st_mode) == 0o700

    with tarfile.open(archive, 'r:gz') as backup:
        assert {
            'docker/data',
            'docker/data/value.txt',
            'docker/data/value-link.txt',
            'docker/.env',
            'backup-manifest.env',
        } <= set(backup.getnames())
        assert backup.getmember('docker/data/value-link.txt').issym()
        manifest = backup.extractfile('backup-manifest.env')
        assert manifest is not None
        assert b'FORMAT_VERSION=1\n' in manifest.read()

    commands = harness.command_log.read_text(encoding='utf-8')
    assert 'compose --profile all stop langbot' in commands
    assert 'compose --profile all start langbot' in commands


def test_same_second_backups_use_monotonic_sequence_across_revisions(tmp_path: Path):
    harness = create_harness(tmp_path)
    assert harness.create().returncode == 0
    (harness.install_dir / 'docker' / '.env').write_text(
        f'LANGBOT_HTTP_PORT=5300\nLANBOT_BUILD_REVISION={"b" * 40}\n',
        encoding='utf-8',
    )

    result = harness.create()

    assert result.returncode == 0, result.stderr
    archives = harness.archives()
    assert [archive_sequence(archive) for archive in archives] == [0, 1]
    assert archives[1].name.endswith(f'-{"b" * 12}.tar.gz')


def test_restore_rejects_tampered_archive_before_touching_current_data(tmp_path: Path):
    harness = create_harness(tmp_path)
    assert harness.create().returncode == 0
    [archive] = harness.archives()
    (harness.install_dir / 'docker' / 'data' / 'value.txt').write_text('current\n', encoding='utf-8')
    archive.write_bytes(archive.read_bytes() + b'tampered')
    harness.command_log.write_text('', encoding='utf-8')

    result = harness.restore(archive)

    assert result.returncode != 0
    assert 'checksum verification failed' in result.stderr
    assert (harness.install_dir / 'docker' / 'data' / 'value.txt').read_text(encoding='utf-8') == 'current\n'
    commands = harness.command_log.read_text(encoding='utf-8')
    assert ' stop ' not in f' {commands} '


def test_restore_replaces_data_but_preserves_current_environment(tmp_path: Path):
    harness = create_harness(tmp_path)
    assert harness.create().returncode == 0
    [archive] = harness.archives()
    (harness.install_dir / 'docker' / 'data' / 'value.txt').write_text('current\n', encoding='utf-8')
    current_environment = f'LANGBOT_HTTP_PORT=6300\nLANBOT_BUILD_REVISION={"b" * 40}\n'
    (harness.install_dir / 'docker' / '.env').write_text(current_environment, encoding='utf-8')

    result = harness.restore(archive)

    assert result.returncode == 0, result.stderr
    assert (harness.install_dir / 'docker' / 'data' / 'value.txt').read_text(encoding='utf-8') == 'old\n'
    assert (harness.install_dir / 'docker' / 'data' / 'value-link.txt').is_symlink()
    assert (harness.install_dir / 'docker' / 'data' / 'value-link.txt').read_text(encoding='utf-8') == 'old\n'
    assert (harness.install_dir / 'docker' / '.env').read_text(encoding='utf-8') == current_environment
    assert [archive_sequence(item) for item in harness.archives()] == [0, 1]
    assert not list((harness.install_dir / 'docker').glob('.restore-*'))


def test_failed_restore_health_check_recovers_pre_restore_data(tmp_path: Path):
    harness = create_harness(tmp_path)
    assert harness.create().returncode == 0
    [archive] = harness.archives()
    (harness.install_dir / 'docker' / 'data' / 'value.txt').write_text('current\n', encoding='utf-8')
    (harness.control_dir / 'fail-health-value').write_text('old', encoding='utf-8')

    result = harness.restore(archive)

    assert result.returncode != 0
    assert 'pre-restore data was restored' in result.stderr
    assert (harness.install_dir / 'docker' / 'data' / 'value.txt').read_text(encoding='utf-8') == 'current\n'
    assert not list((harness.install_dir / 'docker').glob('.restore-*'))


def test_exit_cleanup_retries_interrupted_activation_rollback(tmp_path: Path):
    harness = create_harness(tmp_path)
    assert harness.create().returncode == 0
    [archive] = harness.archives()
    (harness.install_dir / 'docker' / 'data' / 'value.txt').write_text('current\n', encoding='utf-8')
    (harness.control_dir / 'fail-activate').touch()
    (harness.control_dir / 'fail-original-once').touch()
    harness.command_log.write_text('', encoding='utf-8')

    result = harness.restore(archive)

    assert result.returncode != 0
    assert 'Recovering pre-restore data' in result.stdout
    assert (harness.install_dir / 'docker' / 'data' / 'value.txt').read_text(encoding='utf-8') == 'current\n'
    assert not list((harness.install_dir / 'docker').glob('.restore-current.*'))
    assert 'compose --profile all start langbot' in harness.command_log.read_text(encoding='utf-8')


def test_unrecoverable_activation_preserves_safeguard_and_leaves_services_stopped(tmp_path: Path):
    harness = create_harness(tmp_path)
    assert harness.create().returncode == 0
    [archive] = harness.archives()
    (harness.install_dir / 'docker' / 'data' / 'value.txt').write_text('current\n', encoding='utf-8')
    (harness.control_dir / 'fail-activate').touch()
    (harness.control_dir / 'fail-original-always').touch()
    harness.command_log.write_text('', encoding='utf-8')

    result = harness.restore(archive)

    assert result.returncode != 0
    safeguards = list((harness.install_dir / 'docker').glob('.restore-current.*/data/value.txt'))
    assert len(safeguards) == 1
    assert safeguards[0].read_text(encoding='utf-8') == 'current\n'
    assert 'preserved safeguards' in result.stderr
    commands = harness.command_log.read_text(encoding='utf-8')
    assert ' start ' not in f' {commands} '


def test_external_database_restore_requires_explicit_operator_override(tmp_path: Path):
    harness = create_harness(tmp_path, backend='postgresql')
    assert harness.create().returncode == 0
    [archive] = harness.archives()
    (harness.install_dir / 'docker' / 'data' / 'value.txt').write_text('current\n', encoding='utf-8')
    harness.command_log.write_text('', encoding='utf-8')

    result = harness.restore(archive)

    assert result.returncode != 0
    assert 'external database' in result.stderr
    assert (harness.install_dir / 'docker' / 'data' / 'value.txt').read_text(encoding='utf-8') == 'current\n'
    commands = harness.command_log.read_text(encoding='utf-8')
    assert ' stop ' not in f' {commands} '


def test_restore_rejects_archive_member_nested_beneath_symlink(tmp_path: Path):
    harness = create_harness(tmp_path)
    harness.backup_dir.mkdir()
    archive = harness.backup_dir / 'ai-lanbot-20260714T120000Z-000000-unknown.tar.gz'
    with tarfile.open(archive, 'w:gz') as backup:
        for directory in ('docker/data',):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            backup.addfile(info)
        link = tarfile.TarInfo('docker/data/linked')
        link.type = tarfile.SYMTYPE
        link.linkname = '../../outside'
        backup.addfile(link)
        for name, content in (
            ('docker/data/linked/payload.txt', b'unsafe\n'),
            ('docker/.env', b'LANGBOT_HTTP_PORT=5300\n'),
            ('backup-manifest.env', b'FORMAT_VERSION=1\n'),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            backup.addfile(info, io.BytesIO(content))
    Path(f'{archive}.sha256').write_text(
        f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n',
        encoding='utf-8',
    )

    result = harness.restore(archive)

    assert result.returncode != 0
    assert 'nested beneath a symbolic link' in result.stderr
    assert (harness.install_dir / 'docker' / 'data' / 'value.txt').read_text(encoding='utf-8') == 'old\n'


def test_backup_directory_inside_install_is_rejected(tmp_path: Path):
    harness = create_harness(tmp_path)
    harness.env['LANBOT_BACKUP_DIR'] = str(harness.install_dir / 'unsafe-backups')

    result = harness.create()

    assert result.returncode != 0
    assert 'must be outside' in result.stderr


def test_retention_keeps_latest_sequences_and_ignores_unmanaged_names(tmp_path: Path):
    harness = create_harness(tmp_path)
    harness.env['LANBOT_BACKUP_KEEP'] = '2'
    unmanaged = harness.backup_dir / 'ai-lanbot-not-a-managed-backup.tar.gz'
    harness.backup_dir.mkdir()
    unmanaged.write_text('keep me\n', encoding='utf-8')

    for _ in range(4):
        result = harness.create()
        assert result.returncode == 0, result.stderr

    assert [archive_sequence(archive) for archive in harness.archives()] == [2, 3]
    assert unmanaged.read_text(encoding='utf-8') == 'keep me\n'
    assert len(list(harness.backup_dir.glob('*.sha256'))) == 2


def test_partial_stop_failure_still_attempts_to_restart_original_services(tmp_path: Path):
    harness = create_harness(tmp_path)
    (harness.control_dir / 'fail-stop').touch()

    result = harness.create()

    assert result.returncode != 0
    commands = harness.command_log.read_text(encoding='utf-8')
    assert 'compose --profile all stop langbot' in commands
    assert 'compose --profile all start langbot' in commands
    assert not harness.archives()
