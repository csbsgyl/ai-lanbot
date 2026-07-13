import json
import os
import stat

import pytest

from idc_query_core.state import JsonBindingStore


@pytest.mark.asyncio
async def test_binding_store_persists_bindings(tmp_path):
    path = tmp_path / 'bindings.json'
    store = JsonBindingStore(path)
    await store.load()
    await store.put(
        group_id='group-1',
        member_id='member-1',
        bound_by='user-1',
        member_name='Test Customer',
    )

    reloaded = JsonBindingStore(path)
    await reloaded.load()
    binding = await reloaded.get('group-1')

    assert binding.member_id == 'member-1'
    assert binding.bound_by == 'user-1'
    assert binding.member_name == 'Test Customer'
    assert path.with_name('bindings.json.bak').is_file()
    if os.name != 'nt':
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.with_name('bindings.json.bak').stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_binding_store_removes_bindings(tmp_path):
    store = JsonBindingStore(tmp_path / 'bindings.json')
    await store.load()
    await store.put(group_id='group-1', member_id='member-1', bound_by='user-1')

    removed = await store.remove('group-1')

    assert removed.member_id == 'member-1'
    assert await store.get('group-1') is None


@pytest.mark.asyncio
async def test_binding_store_sanitizes_invisible_member_name_characters(tmp_path):
    store = JsonBindingStore(tmp_path / 'bindings.json')
    await store.load()

    binding = await store.put(
        group_id='group-1',
        member_id='member-1',
        bound_by='user-1',
        member_name=' Example\r\nIDC\u202eTXT ',
    )

    assert binding.member_name == 'Example IDC TXT'
    assert '\u202e' not in binding.member_name


@pytest.mark.asyncio
async def test_binding_store_recovers_corrupted_primary_from_committed_backup(tmp_path):
    path = tmp_path / 'bindings.json'
    store = JsonBindingStore(path)
    await store.load()
    await store.put(group_id='group-1', member_id='member-1', bound_by='user-1')

    path.write_text('{broken', encoding='utf-8')
    reloaded = JsonBindingStore(path)
    await reloaded.load()

    assert (await reloaded.get('group-1')).member_id == 'member-1'
    assert json.loads(path.read_text(encoding='utf-8'))['bindings']['group-1']['bound_by'] == 'user-1'


@pytest.mark.asyncio
async def test_binding_store_rejects_uncommitted_newer_backup(tmp_path):
    path = tmp_path / 'bindings.json'
    store = JsonBindingStore(path)
    await store.load()
    await store.put(group_id='group-1', member_id='member-1', bound_by='user-1')

    path.write_text('{broken', encoding='utf-8')
    backup_path = path.with_name('bindings.json.bak')
    newer = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(backup_path, ns=(newer, newer))

    with pytest.raises(ValueError, match='no committed backup'):
        await JsonBindingStore(path).load()


@pytest.mark.asyncio
async def test_failed_binding_write_does_not_change_in_memory_state(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / 'bindings.json'
    store = JsonBindingStore(path)
    await store.load()
    await store.put(group_id='group-1', member_id='member-1', bound_by='user-1')

    original_atomic_write = store._atomic_write

    def fail_primary(target, content):
        if target == path:
            raise OSError('disk full')
        original_atomic_write(target, content)

    monkeypatch.setattr(store, '_atomic_write', fail_primary)
    with pytest.raises(OSError, match='disk full'):
        await store.put(group_id='group-2', member_id='member-2', bound_by='user-2')

    assert await store.get('group-2') is None
    assert (await store.get('group-1')).member_id == 'member-1'
    reloaded = JsonBindingStore(path)
    await reloaded.load()
    assert await reloaded.get('group-2') is None
    assert (await reloaded.get('group-1')).member_id == 'member-1'


@pytest.mark.asyncio
async def test_binding_store_rejects_mismatched_group_key(tmp_path):
    path = tmp_path / 'bindings.json'
    path.write_text(
        json.dumps(
            {
                'version': 1,
                'bindings': {
                    'group-1': {
                        'group_id': 'group-2',
                        'member_id': 'member-1',
                        'bound_by': 'user-1',
                        'bound_at': '2026-07-12T10:00:00+00:00',
                        'member_name': '',
                    }
                },
            }
        ),
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='corrupted and has no committed backup'):
        await JsonBindingStore(path).load()
