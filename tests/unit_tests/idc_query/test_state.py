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


@pytest.mark.asyncio
async def test_binding_store_removes_bindings(tmp_path):
    store = JsonBindingStore(tmp_path / 'bindings.json')
    await store.load()
    await store.put(group_id='group-1', member_id='member-1', bound_by='user-1')

    removed = await store.remove('group-1')

    assert removed.member_id == 'member-1'
    assert await store.get('group-1') is None
