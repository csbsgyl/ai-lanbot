import asyncio
import json
import os
import stat

import pytest

from idc_query_core.audit import JsonlAuditLog


@pytest.mark.asyncio
async def test_audit_log_writes_only_bounded_schema_fields(tmp_path):
    path = tmp_path / 'audit.jsonl'
    audit_log = JsonlAuditLog(path)

    await audit_log.append(
        command='bind',
        outcome='success',
        reason='bound',
        group_id='group-1\nignored',
        user_id='user-1',
        member_id='member-1',
        request_id='request-1',
        duration_ms=14,
    )

    event = json.loads(path.read_text(encoding='utf-8'))
    assert set(event) == {
        'version',
        'timestamp',
        'command',
        'outcome',
        'reason',
        'group_id',
        'user_id',
        'member_id',
        'request_id',
        'duration_ms',
    }
    assert event['group_id'] == 'group-1ignored'
    assert event['duration_ms'] == 14
    if os.name != 'nt':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_audit_log_serializes_concurrent_events_as_valid_json_lines(tmp_path):
    path = tmp_path / 'audit.jsonl'
    audit_log = JsonlAuditLog(path)

    await asyncio.gather(
        *(
            audit_log.append(
                command='ip',
                outcome='success',
                reason='queried',
                group_id='group-1',
                user_id=f'user-{index}',
                member_id='member-1',
                request_id=f'request-{index}',
                duration_ms=index,
            )
            for index in range(20)
        )
    )

    events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(events) == 20
    assert {event['request_id'] for event in events} == {f'request-{index}' for index in range(20)}


@pytest.mark.asyncio
async def test_audit_log_rotates_at_bounded_size(tmp_path):
    path = tmp_path / 'audit.jsonl'
    audit_log = JsonlAuditLog(path, max_bytes=350, backup_count=2)

    for index in range(4):
        await audit_log.append(
            command='traffic',
            outcome='success',
            reason='queried',
            group_id='group-1',
            user_id='user-1',
            member_id='member-1',
            request_id=f'request-{index}',
            duration_ms=10,
        )

    assert path.is_file()
    assert path.with_name('audit.jsonl.1').is_file()
    assert path.with_name('audit.jsonl.2').is_file()
