import asyncio

import pytest

from idc_query_core.commands import CommandType
from idc_query_core.service import IDCQueryService
from idc_query_core.state import JsonBindingStore


class FakeGateway:
    def __init__(self):
        self.verify_calls = []
        self.query_calls = []
        self.unbind_calls = []

    async def verify_binding(self, **kwargs):
        self.verify_calls.append(kwargs)
        return {'member_id': kwargs['member_id'], 'member_name': 'Example IDC'}

    async def unbind(self, **kwargs):
        self.unbind_calls.append(kwargs)

    async def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return {
            'ok': True,
            'data': {
                'ip': kwargs['arguments'].get('ip'),
                'line': 'BGP',
                'protection_status': '正常',
            },
        }


async def _service(tmp_path, **overrides):
    gateway = FakeGateway()
    service = IDCQueryService(
        store=JsonBindingStore(tmp_path / 'bindings.json'),
        gateway=gateway,
        exclusive_mode=overrides.get('exclusive_mode', True),
        sensitive_binder_only=overrides.get('sensitive_binder_only', True),
    )
    await service.initialize()
    return service, gateway


@pytest.mark.asyncio
async def test_unbound_group_can_bind_and_query(tmp_path):
    service, gateway = await _service(tmp_path)

    unbound = await service.handle(text='查IP 1.1.1.1', group_id='group-1', user_id='user-1', message_id='message-1')
    bound = await service.handle(text='绑定 10086 938421', group_id='group-1', user_id='user-1', message_id='message-2')
    queried = await service.handle(text='查IP 1.1.1.1', group_id='group-1', user_id='user-2', message_id='message-3')

    assert '尚未绑定' in unbound.reply
    assert bound.reply == '绑定成功：会员 10086（Example IDC）'
    assert 'IP：1.1.1.1' in queried.reply
    assert gateway.query_calls[0]['member_id'] == '10086'
    assert gateway.query_calls[0]['command_type'] == CommandType.IP


@pytest.mark.asyncio
async def test_sensitive_queries_are_limited_to_binder(tmp_path):
    service, _gateway = await _service(tmp_path)
    await service.handle(text='绑定 10086 938421', group_id='group-1', user_id='binder', message_id='message-1')

    denied = await service.handle(text='查余额', group_id='group-1', user_id='other-user', message_id='message-2')

    assert denied.reply == '该指令包含敏感账户信息，仅执行群绑定的成员可以查询。'


@pytest.mark.asyncio
async def test_only_binder_can_unbind(tmp_path):
    service, gateway = await _service(tmp_path)
    await service.handle(text='绑定 10086 938421', group_id='group-1', user_id='binder', message_id='message-1')

    denied = await service.handle(text='解绑', group_id='group-1', user_id='other-user', message_id='message-2')
    removed = await service.handle(text='解绑', group_id='group-1', user_id='binder', message_id='message-3')

    assert denied.reply == '只有执行群绑定的成员可以解绑。'
    assert removed.reply == '已解除当前群与会员 10086 的绑定。'
    assert len(gateway.unbind_calls) == 1


@pytest.mark.asyncio
async def test_duplicate_message_is_not_processed_twice(tmp_path):
    service, gateway = await _service(tmp_path)

    first = await service.handle(text='绑定 10086 938421', group_id='group-1', user_id='binder', message_id='message-1')
    duplicate = await service.handle(
        text='绑定 10086 938421', group_id='group-1', user_id='binder', message_id='message-1'
    )

    assert first.reply
    assert duplicate.handled is True
    assert duplicate.reply is None
    assert len(gateway.verify_calls) == 1


@pytest.mark.asyncio
async def test_duplicate_unknown_message_does_not_reply_twice(tmp_path):
    service, _gateway = await _service(tmp_path)

    first = await service.handle(text='未知指令', group_id='group-1', user_id='user-1', message_id='message-1')
    duplicate = await service.handle(text='未知指令', group_id='group-1', user_id='user-1', message_id='message-1')

    assert first.reply
    assert duplicate.handled is True
    assert duplicate.reply is None


@pytest.mark.asyncio
async def test_concurrent_binding_does_not_overwrite_existing_member(tmp_path):
    service, gateway = await _service(tmp_path)

    first, second = await asyncio.gather(
        service.handle(text='绑定 10086 938421', group_id='group-1', user_id='user-1', message_id='message-1'),
        service.handle(text='绑定 20001 123456', group_id='group-1', user_id='user-2', message_id='message-2'),
    )

    binding = await service.store.get('group-1')
    replies = [first.reply, second.reply]
    assert binding.member_id in {'10086', '20001'}
    assert sum(reply.startswith('绑定成功') for reply in replies) == 1
    assert sum('已绑定会员' in reply for reply in replies) == 1
    assert len(gateway.verify_calls) == 1


@pytest.mark.asyncio
async def test_binding_rejects_mismatched_gateway_identity(tmp_path):
    service, gateway = await _service(tmp_path)

    async def verify_wrong_member(**kwargs):
        gateway.verify_calls.append(kwargs)
        return {'member_id': 'another-member'}

    gateway.verify_binding = verify_wrong_member
    result = await service.handle(
        text='绑定 10086 938421',
        group_id='group-1',
        user_id='binder',
        message_id='message-1',
    )

    assert result.reply == '绑定验证结果异常，请联系管理员检查 IDC 查询网关。'
    assert await service.store.get('group-1') is None
