from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class JsonlAuditLog:
    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        self.path = path
        self.max_bytes = max(1, int(max_bytes))
        self.backup_count = max(0, int(backup_count))
        self._lock = Lock()

    async def append(
        self,
        *,
        command: str,
        outcome: str,
        reason: str,
        group_id: str,
        user_id: str,
        member_id: str,
        request_id: str,
        duration_ms: int,
    ) -> None:
        event = {
            'version': 1,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'command': self._safe_text(command, 40),
            'outcome': self._safe_text(outcome, 40),
            'reason': self._safe_text(reason, 80),
            'group_id': self._safe_text(group_id, 160),
            'user_id': self._safe_text(user_id, 160),
            'member_id': self._safe_text(member_id, 160),
            'request_id': self._safe_text(request_id, 160),
            'duration_ms': max(0, min(int(duration_ms), 3_600_000)),
        }
        line = json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n'
        encoded_size = len(line.encode('utf-8'))

        await asyncio.to_thread(self._write_line, line, encoded_size)

    def _write_line(self, line: str, encoded_size: int) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
            if self.path.exists() and self.path.stat().st_size + encoded_size > self.max_bytes:
                self._rotate()
            self._append_line(line)

    def _append_line(self, line: str) -> None:
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, 'a', encoding='utf-8', newline='\n') as audit_file:
            audit_file.write(line)
            audit_file.flush()
            os.fsync(audit_file.fileno())
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _rotate(self) -> None:
        if self.backup_count == 0:
            self.path.unlink(missing_ok=True)
            return

        oldest = self.path.with_name(f'{self.path.name}.{self.backup_count}')
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f'{self.path.name}.{index}')
            if source.exists():
                os.replace(source, self.path.with_name(f'{self.path.name}.{index + 1}'))
        if self.path.exists():
            os.replace(self.path, self.path.with_name(f'{self.path.name}.1'))

    @staticmethod
    def _safe_text(value: object, limit: int) -> str:
        text = str(value or '')
        return ''.join(character for character in text if ord(character) >= 32 and ord(character) != 127)[:limit]
