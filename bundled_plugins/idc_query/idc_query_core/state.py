from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)
_MAX_IDENTIFIER_LENGTH = 160
_MAX_MEMBER_NAME_LENGTH = 200


def _required_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{field_name} must be a string')
    text = value.strip()
    if (
        not text
        or len(text) > _MAX_IDENTIFIER_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        raise ValueError(f'{field_name} is invalid')
    return text


def _member_name(value: Any) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('member_name must be a string')
    return ''.join(character for character in value if ord(character) >= 32 and ord(character) != 127)[
        :_MAX_MEMBER_NAME_LENGTH
    ].strip()


@dataclass(frozen=True)
class Binding:
    group_id: str
    member_id: str
    bound_by: str
    bound_at: str
    member_name: str = ''

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Binding':
        if not isinstance(data, dict):
            raise ValueError('binding must be an object')
        bound_at = _required_identifier(data.get('bound_at'), 'bound_at')
        try:
            parsed_bound_at = datetime.fromisoformat(bound_at.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('bound_at is invalid') from exc
        if parsed_bound_at.tzinfo is None:
            raise ValueError('bound_at must include a timezone')

        return cls(
            group_id=_required_identifier(data.get('group_id'), 'group_id'),
            member_id=_required_identifier(data.get('member_id'), 'member_id'),
            bound_by=_required_identifier(data.get('bound_by'), 'bound_by'),
            bound_at=bound_at,
            member_name=_member_name(data.get('member_name', '')),
        )


class JsonBindingStore:
    def __init__(self, path: Path):
        self.path = path
        self.backup_path = path.with_name(f'{path.name}.bak')
        self._bindings: dict[str, Binding] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        async with self._lock:
            self._bindings = await asyncio.to_thread(self._load_with_recovery)

    async def get(self, group_id: str) -> Binding | None:
        async with self._lock:
            return self._bindings.get(str(group_id))

    async def put(
        self,
        *,
        group_id: str,
        member_id: str,
        bound_by: str,
        member_name: str = '',
    ) -> Binding:
        binding = Binding.from_dict(
            {
                'group_id': group_id,
                'member_id': member_id,
                'bound_by': bound_by,
                'bound_at': datetime.now(timezone.utc).isoformat(),
                'member_name': member_name,
            }
        )
        async with self._lock:
            next_bindings = dict(self._bindings)
            next_bindings[binding.group_id] = binding
            await asyncio.to_thread(self._persist_snapshot, next_bindings, self._bindings)
            self._bindings = next_bindings
        return binding

    async def remove(self, group_id: str) -> Binding | None:
        async with self._lock:
            binding = self._bindings.get(str(group_id))
            if binding is None:
                return None
            next_bindings = dict(self._bindings)
            next_bindings.pop(str(group_id), None)
            await asyncio.to_thread(self._persist_snapshot, next_bindings, self._bindings)
            self._bindings = next_bindings
            return binding

    def _load_with_recovery(self) -> dict[str, Binding]:
        self._secure_parent()
        if not self.path.exists():
            return {}

        primary_mtime = self.path.stat().st_mtime_ns
        try:
            bindings = self._read_snapshot(self.path)
        except (json.JSONDecodeError, KeyError, TypeError, UnicodeError, ValueError) as primary_error:
            if not self.backup_path.is_file() or self.backup_path.stat().st_mtime_ns > primary_mtime:
                raise ValueError('IDC binding state is corrupted and has no committed backup') from primary_error
            try:
                bindings = self._read_snapshot(self.backup_path)
            except (json.JSONDecodeError, KeyError, TypeError, UnicodeError, ValueError) as backup_error:
                raise ValueError('IDC binding state and its backup are corrupted') from backup_error
            self._atomic_write(self.path, self._serialize(bindings))
            logger.error('Recovered IDC binding state from the last committed backup')

        self._secure_file(self.path)
        if self.backup_path.exists():
            self._secure_file(self.backup_path)
        return bindings

    @staticmethod
    def _read_snapshot(path: Path) -> dict[str, Binding]:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or payload.get('version') != 1:
            raise ValueError('unsupported binding state format')
        raw_bindings = payload.get('bindings')
        if not isinstance(raw_bindings, dict):
            raise ValueError('bindings must be an object')

        bindings: dict[str, Binding] = {}
        for raw_group_id, raw_binding in raw_bindings.items():
            group_id = _required_identifier(raw_group_id, 'group_id')
            binding = Binding.from_dict(raw_binding)
            if binding.group_id != group_id:
                raise ValueError('binding group_id does not match its key')
            bindings[group_id] = binding
        return bindings

    @staticmethod
    def _serialize(bindings: dict[str, Binding]) -> str:
        payload = {
            'version': 1,
            'bindings': {group_id: asdict(binding) for group_id, binding in sorted(bindings.items())},
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + '\n'

    def _persist_snapshot(
        self,
        bindings: dict[str, Binding],
        previous_bindings: dict[str, Binding],
    ) -> None:
        self._secure_parent()
        next_content = self._serialize(bindings)
        previous_content = self._serialize(previous_bindings)
        primary_existed = self.path.exists()

        self._atomic_write(self.backup_path, next_content)
        try:
            self._atomic_write(self.path, next_content)
        except OSError:
            try:
                if primary_existed:
                    self._atomic_write(self.backup_path, previous_content)
                else:
                    self.backup_path.unlink(missing_ok=True)
            except OSError:
                logger.exception('Could not roll back the IDC binding backup after a failed state write')
            raise

    def _secure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass

    @staticmethod
    def _secure_file(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _atomic_write(self, path: Path, content: str) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                newline='\n',
                prefix=f'.{path.name}.',
                suffix='.tmp',
                dir=path.parent,
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                os.chmod(temp_path, 0o600)
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            os.replace(temp_path, path)
            self._secure_file(path)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
