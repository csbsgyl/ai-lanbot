from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import aiohttp

from ....utils import httpclient, paths

if TYPE_CHECKING:
    from ....core import app


DEFAULT_REPOSITORY = 'csbsgyl/ai-lanbot'
DEFAULT_BRANCH = 'main'
GITHUB_ACCELERATOR = 'https://github.xiaohangyun.org'
REVISION_PATTERN = re.compile(r'^[0-9a-f]{40}$')
REPOSITORY_PATTERN = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
BRANCH_PATTERN = re.compile(r'^[A-Za-z0-9._/-]{1,128}$')
ACTIVE_STATES = {'queued', 'checking', 'deploying'}
KNOWN_STATES = ACTIVE_STATES | {'idle', 'success', 'failed'}
CACHE_SECONDS = 60


class UpdateDisabledError(RuntimeError):
    pass


class UpdateInProgressError(RuntimeError):
    pass


class UpdateCheckError(RuntimeError):
    pass


class SystemUpdateService:
    """Coordinate repository checks with the host-side managed updater."""

    def __init__(self, ap: app.Application) -> None:
        self.ap = ap
        self.update_dir = Path(paths.get_data_path('update'))
        self.status_file = self.update_dir / 'status.json'
        self.request_file = Path(paths.get_data_path('update-request/request.json'))
        self._request_lock = asyncio.Lock()
        self._check_lock = asyncio.Lock()
        self._cached_revision = ''
        self._cache_time = 0.0

    async def get_status(self, *, force_refresh: bool = False) -> dict[str, Any]:
        status = self._read_status()
        check_error = ''
        try:
            latest_revision = await self.get_latest_revision(force_refresh=force_refresh)
        except UpdateCheckError:
            latest_revision = self._cached_revision or status.get('target_revision', '')
            check_error = 'repository_unreachable'

        current_revision = self._normalize_revision(os.environ.get('LANBOT_BUILD_REVISION', ''))
        state = status.get('state', 'idle')
        update_available = bool(latest_revision and current_revision != latest_revision)

        return {
            'enabled': self._is_enabled(),
            'repository': self._repository(),
            'branch': self._branch(),
            'current_revision': current_revision,
            'latest_revision': latest_revision,
            'update_available': update_available,
            'can_update': self._is_enabled() and update_available and state not in ACTIVE_STATES,
            'state': state,
            'message': status.get('message', ''),
            'target_revision': status.get('target_revision', ''),
            'updated_at': status.get('updated_at', ''),
            'check_error': check_error,
        }

    async def request_update(self) -> dict[str, Any]:
        if not self._is_enabled():
            raise UpdateDisabledError('Managed updates are not enabled on this host.')

        async with self._request_lock:
            status = self._read_status()
            if status.get('state') in ACTIVE_STATES:
                raise UpdateInProgressError('An update is already in progress.')

            target_revision = await self.get_latest_revision(force_refresh=True)
            current_revision = self._normalize_revision(os.environ.get('LANBOT_BUILD_REVISION', ''))
            if target_revision == current_revision:
                return await self.get_status()

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            request = {
                'requested_at': now,
                'target_revision': target_revision,
            }

            self.request_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                self._write_request(request)
            except OSError as exc:
                self.ap.logger.error(f'Failed to signal the managed updater: {exc}')
                raise UpdateDisabledError('The managed updater request path is not writable.') from exc
            return await self.get_status()

    async def get_latest_revision(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._cached_revision and time.monotonic() - self._cache_time < CACHE_SECONDS:
            return self._cached_revision

        async with self._check_lock:
            if not force_refresh and self._cached_revision and time.monotonic() - self._cache_time < CACHE_SECONDS:
                return self._cached_revision

            repository = self._repository()
            branch = self._branch()
            api_url = f'https://api.github.com/repos/{repository}/commits/{quote(branch, safe="")}'
            urls = (api_url, f'{GITHUB_ACCELERATOR}/{api_url}')
            errors = []
            for url in urls:
                try:
                    revision = await self._fetch_revision(url)
                    self._cached_revision = revision
                    self._cache_time = time.monotonic()
                    return revision
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                    errors.append(str(exc))

            self.ap.logger.warning(f'Failed to check application update revision: {errors}')
            raise UpdateCheckError('Could not reach the update repository.')

    async def _fetch_revision(self, url: str) -> str:
        session = httpclient.get_session(trust_env=True)
        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(
            url,
            headers={
                'Accept': 'application/vnd.github.sha',
                'User-Agent': 'ai-lanbot-update-check',
            },
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            body = (await response.text()).strip()

        revision = self._normalize_revision(body)
        if revision:
            return revision

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError('Update repository returned an invalid revision.') from exc
        revision = self._normalize_revision(payload.get('sha', '') if isinstance(payload, dict) else '')
        if not revision:
            raise ValueError('Update repository returned an invalid revision.')
        return revision

    def _read_status(self) -> dict[str, str]:
        status_mtime_ns = 0
        try:
            status_mtime_ns = self.status_file.stat().st_mtime_ns
            payload = json.loads(self.status_file.read_text(encoding='utf-8'))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        state = payload.get('state', 'idle')
        if state not in KNOWN_STATES:
            state = 'idle'
        status = {
            'state': state,
            'message': self._limited_string(payload.get('message')),
            'current_revision': self._normalize_revision(payload.get('current_revision', '')),
            'target_revision': self._normalize_revision(payload.get('target_revision', '')),
            'updated_at': self._limited_string(payload.get('updated_at')),
        }
        return self._with_pending_request(status, status_mtime_ns)

    def _with_pending_request(self, status: dict[str, str], status_mtime_ns: int) -> dict[str, str]:
        if status['state'] in ACTIVE_STATES:
            return status
        try:
            request_mtime_ns = self.request_file.stat().st_mtime_ns
            request = json.loads(self.request_file.read_text(encoding='utf-8'))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return status
        if not isinstance(request, dict) or request_mtime_ns <= status_mtime_ns:
            return status

        target_revision = self._normalize_revision(request.get('target_revision', ''))
        if not target_revision:
            return status
        return {
            'state': 'queued',
            'message': 'update_queued',
            'current_revision': status['current_revision'],
            'target_revision': target_revision,
            'updated_at': self._limited_string(request.get('requested_at')),
        }

    def _write_request(self, payload: dict[str, str]) -> None:
        with self.request_file.open('w', encoding='utf-8') as file:
            json.dump(payload, file, ensure_ascii=True, separators=(',', ':'))
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())

    @staticmethod
    def _normalize_revision(value: Any) -> str:
        if not isinstance(value, str):
            return ''
        revision = value.strip().lower()
        return revision if REVISION_PATTERN.fullmatch(revision) else ''

    @staticmethod
    def _limited_string(value: Any) -> str:
        return value[:160] if isinstance(value, str) else ''

    @staticmethod
    def _is_enabled() -> bool:
        return os.environ.get('LANBOT_UPDATE_ENABLED', '').strip().lower() == 'true'

    @staticmethod
    def _repository() -> str:
        repository = os.environ.get('LANBOT_UPDATE_REPOSITORY', DEFAULT_REPOSITORY).strip()
        return repository if REPOSITORY_PATTERN.fullmatch(repository) else DEFAULT_REPOSITORY

    @staticmethod
    def _branch() -> str:
        branch = os.environ.get('LANBOT_UPDATE_BRANCH', DEFAULT_BRANCH).strip()
        return branch if BRANCH_PATTERN.fullmatch(branch) and '..' not in branch else DEFAULT_BRANCH
