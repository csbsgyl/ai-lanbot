from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from langbot.pkg.api.http.service.system_update import (
    MAX_REVISION_RESPONSE_BYTES,
    SystemUpdateService,
    UpdateDisabledError,
    UpdateInProgressError,
)
from tests.factories import FakeApp


CURRENT_REVISION = '1' * 40
LATEST_REVISION = '2' * 40


@pytest.fixture
def update_service(tmp_path, monkeypatch: pytest.MonkeyPatch) -> SystemUpdateService:
    monkeypatch.setenv('LANGBOT_DATA_ROOT', str(tmp_path))
    monkeypatch.setenv('LANBOT_UPDATE_ENABLED', 'true')
    monkeypatch.setenv('LANBOT_BUILD_REVISION', CURRENT_REVISION)
    monkeypatch.setenv('LANBOT_UPDATE_REPOSITORY', 'csbsgyl/ai-lanbot')
    monkeypatch.setenv('LANBOT_UPDATE_BRANCH', 'main')
    return SystemUpdateService(FakeApp())


@pytest.mark.asyncio
async def test_status_reports_revision_update_and_capability(update_service: SystemUpdateService):
    update_service.get_latest_revision = AsyncMock(return_value=LATEST_REVISION)

    status = await update_service.get_status()

    assert status['enabled'] is True
    assert status['current_revision'] == CURRENT_REVISION
    assert status['latest_revision'] == LATEST_REVISION
    assert status['update_available'] is True
    assert status['can_update'] is True
    assert status['state'] == 'idle'


@pytest.mark.asyncio
async def test_request_update_writes_fixed_host_signal(update_service: SystemUpdateService):
    update_service.get_latest_revision = AsyncMock(return_value=LATEST_REVISION)

    status = await update_service.request_update()

    request = json.loads(update_service.request_file.read_text(encoding='utf-8'))
    assert request['target_revision'] == LATEST_REVISION
    assert set(request) == {'requested_at', 'target_revision'}
    assert not update_service.status_file.exists()
    assert update_service._read_status()['target_revision'] == LATEST_REVISION
    assert status['state'] == 'queued'
    assert status['can_update'] is False


@pytest.mark.asyncio
async def test_request_update_rejects_disabled_host(
    update_service: SystemUpdateService, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv('LANBOT_UPDATE_ENABLED', 'false')

    with pytest.raises(UpdateDisabledError):
        await update_service.request_update()

    assert not update_service.request_file.exists()


@pytest.mark.asyncio
async def test_request_update_rejects_duplicate_active_request(update_service: SystemUpdateService):
    update_service.update_dir.mkdir(parents=True)
    update_service.status_file.write_text(
        json.dumps({'state': 'deploying', 'target_revision': LATEST_REVISION}),
        encoding='utf-8',
    )

    with pytest.raises(UpdateInProgressError):
        await update_service.request_update()


@pytest.mark.asyncio
async def test_request_update_recovers_when_host_signal_cannot_be_written(
    update_service: SystemUpdateService, monkeypatch: pytest.MonkeyPatch
):
    update_service.get_latest_revision = AsyncMock(return_value=LATEST_REVISION)

    def fail_write(_payload):
        raise OSError('read-only request path')

    monkeypatch.setattr(update_service, '_write_request', fail_write)

    with pytest.raises(UpdateDisabledError, match='not writable'):
        await update_service.request_update()

    assert not update_service.status_file.exists()
    assert update_service._read_status()['state'] == 'idle'


@pytest.mark.asyncio
async def test_request_update_is_noop_when_current(update_service: SystemUpdateService):
    update_service.get_latest_revision = AsyncMock(return_value=CURRENT_REVISION)

    status = await update_service.request_update()

    assert status['update_available'] is False
    assert not update_service.request_file.exists()


@pytest.mark.asyncio
async def test_latest_revision_is_cached(update_service: SystemUpdateService):
    update_service._fetch_revision = AsyncMock(return_value=LATEST_REVISION)

    first = await update_service.get_latest_revision()
    second = await update_service.get_latest_revision()

    assert first == LATEST_REVISION
    assert second == LATEST_REVISION
    update_service._fetch_revision.assert_awaited_once()


@pytest.mark.asyncio
async def test_latest_revision_falls_back_from_atom_to_api(update_service: SystemUpdateService):
    calls = []

    async def fetch_revision(url: str, *, response_format: str = 'api') -> str:
        calls.append((url, response_format))
        if response_format == 'atom':
            raise ValueError('Atom unavailable')
        return LATEST_REVISION

    update_service._fetch_revision = fetch_revision

    assert await update_service.get_latest_revision() == LATEST_REVISION
    assert [response_format for _, response_format in calls] == ['atom', 'atom', 'api']
    assert calls[0][0] == 'https://github.com/csbsgyl/ai-lanbot/commits/main.atom'


def test_atom_revision_parser_reads_the_first_feed_entry(update_service: SystemUpdateService):
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>tag:github.com,2008:Grit::Commit/{LATEST_REVISION}</id></entry>
  <entry><id>tag:github.com,2008:Grit::Commit/{CURRENT_REVISION}</id></entry>
</feed>""".encode()

    assert update_service._parse_atom_revision(feed) == LATEST_REVISION


@pytest.mark.parametrize(
    'feed',
    [
        b'<html></html>',
        b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>',
        b'<!DOCTYPE feed><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>not-a-commit</id></entry></feed>',
    ],
)
def test_atom_revision_parser_rejects_invalid_feeds(update_service: SystemUpdateService, feed: bytes):
    with pytest.raises(ValueError):
        update_service._parse_atom_revision(feed)


def test_api_revision_parser_accepts_raw_sha_and_json(update_service: SystemUpdateService):
    assert update_service._parse_api_revision(LATEST_REVISION.encode()) == LATEST_REVISION
    assert update_service._parse_api_revision(json.dumps({'sha': LATEST_REVISION}).encode()) == LATEST_REVISION


@pytest.mark.asyncio
async def test_revision_response_reader_enforces_decoded_size_limit(update_service: SystemUpdateService):
    class Content:
        async def iter_chunked(self, _chunk_size: int):
            yield b'a' * MAX_REVISION_RESPONSE_BYTES
            yield b'b'

    class Response:
        content_length = None
        content = Content()

    with pytest.raises(ValueError, match='too large'):
        await update_service._read_limited_response(Response())


def test_malformed_status_file_is_ignored(update_service: SystemUpdateService):
    update_service.update_dir.mkdir(parents=True)
    update_service.status_file.write_text('{broken', encoding='utf-8')

    assert update_service._read_status()['state'] == 'idle'


def test_repository_and_branch_environment_are_constrained(update_service: SystemUpdateService, monkeypatch):
    monkeypatch.setenv('LANBOT_UPDATE_REPOSITORY', '../../other')
    monkeypatch.setenv('LANBOT_UPDATE_BRANCH', '../unsafe')

    assert update_service._repository() == 'csbsgyl/ai-lanbot'
    assert update_service._branch() == 'main'
