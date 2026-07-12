from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Binding:
    group_id: str
    member_id: str
    bound_by: str
    bound_at: str
    member_name: str = ''

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Binding':
        return cls(
            group_id=str(data['group_id']),
            member_id=str(data['member_id']),
            bound_by=str(data['bound_by']),
            bound_at=str(data['bound_at']),
            member_name=str(data.get('member_name', '')),
        )


class JsonBindingStore:
    def __init__(self, path: Path):
        self.path = path
        self._bindings: dict[str, Binding] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        async with self._lock:
            if not self.path.exists():
                self._bindings = {}
                return
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            raw_bindings = payload.get('bindings', {})
            self._bindings = {str(group_id): Binding.from_dict(binding) for group_id, binding in raw_bindings.items()}

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
        binding = Binding(
            group_id=str(group_id),
            member_id=str(member_id),
            bound_by=str(bound_by),
            bound_at=datetime.now(timezone.utc).isoformat(),
            member_name=str(member_name),
        )
        async with self._lock:
            self._bindings[binding.group_id] = binding
            self._write_locked()
        return binding

    async def remove(self, group_id: str) -> Binding | None:
        async with self._lock:
            binding = self._bindings.pop(str(group_id), None)
            if binding is not None:
                self._write_locked()
            return binding

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f'{self.path.suffix}.tmp')
        payload = {
            'version': 1,
            'bindings': {group_id: asdict(binding) for group_id, binding in sorted(self._bindings.items())},
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        os.replace(temporary, self.path)
        if os.name != 'nt':
            self.path.chmod(0o600)
