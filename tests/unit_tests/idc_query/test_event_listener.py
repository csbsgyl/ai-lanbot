from types import SimpleNamespace

import pytest

from langbot_plugin.api.entities import events
import langbot_plugin.api.entities.builtin.platform.message as platform_message

from components.events.idc_query import IDCQueryEventListener
from idc_query_core.service import HandleResult


class FakePlugin:
    def __init__(self):
        self.calls = []

    async def handle_idc_query(self, **kwargs):
        self.calls.append(kwargs)
        return HandleResult(True, '查询成功')


class FailingPlugin(FakePlugin):
    async def handle_idc_query(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError('gateway wiring failed')


class FakeEventContext:
    def __init__(self, event):
        self.event = event
        self.prevented_default = False
        self.prevented_postorder = False
        self.replies = []

    def prevent_default(self):
        self.prevented_default = True

    def prevent_postorder(self):
        self.prevented_postorder = True

    async def reply(self, message_chain):
        self.replies.append(message_chain)


@pytest.mark.asyncio
async def test_listener_uses_raw_qq_member_identity_and_blocks_llm():
    plugin = FakePlugin()
    listener = IDCQueryEventListener()
    listener.plugin = plugin
    await listener.initialize()
    handler = listener.registered_handlers[events.GroupMessageReceived][0]
    source = SimpleNamespace(
        t='GROUP_AT_MESSAGE_CREATE',
        group_openid='group-openid',
        member_openid='member-openid',
        d_id='message-id',
    )
    event = SimpleNamespace(
        launcher_id='normalized-group',
        sender_id='normalized-member',
        message_event=SimpleNamespace(source_platform_object=source),
        message_chain=platform_message.MessageChain(
            [platform_message.At(target='justbot'), platform_message.Plain(text='查IP 1.1.1.1')]
        ),
    )
    event_context = FakeEventContext(event)

    await handler(event_context)

    assert plugin.calls == [
        {
            'text': '查IP 1.1.1.1',
            'group_id': 'group-openid',
            'user_id': 'member-openid',
            'message_id': 'message-id',
        }
    ]
    assert event_context.prevented_default is True
    assert event_context.prevented_postorder is True
    assert list(event_context.replies[0])[0].text == '查询成功'


@pytest.mark.asyncio
async def test_listener_ignores_non_qq_group_events():
    plugin = FakePlugin()
    listener = IDCQueryEventListener()
    listener.plugin = plugin
    await listener.initialize()
    handler = listener.registered_handlers[events.GroupMessageReceived][0]
    event = SimpleNamespace(
        launcher_id='group-1',
        sender_id='user-1',
        message_event=SimpleNamespace(source_platform_object=SimpleNamespace(t='OTHER_PLATFORM_EVENT')),
        message_chain=platform_message.MessageChain([platform_message.Plain(text='查IP 1.1.1.1')]),
    )
    event_context = FakeEventContext(event)

    await handler(event_context)

    assert plugin.calls == []
    assert event_context.prevented_default is False
    assert event_context.replies == []


@pytest.mark.asyncio
async def test_listener_reads_normalized_member_id_from_legacy_raw_event_dict():
    plugin = FakePlugin()
    listener = IDCQueryEventListener()
    listener.plugin = plugin
    await listener.initialize()
    handler = listener.registered_handlers[events.GroupMessageReceived][0]
    event = SimpleNamespace(
        launcher_id='group-openid',
        sender_id='group-openid',
        message_event=SimpleNamespace(
            source_platform_object={
                't': 'GROUP_AT_MESSAGE_CREATE',
                'group_openid': 'group-openid',
                'member_openid': 'member-openid',
                'd_id': 'message-id',
            }
        ),
        message_chain=platform_message.MessageChain([platform_message.Plain(text='帮助')]),
    )

    await handler(FakeEventContext(event))

    assert plugin.calls[0] == {
        'text': '帮助',
        'group_id': 'group-openid',
        'user_id': 'member-openid',
        'message_id': 'message-id',
    }


@pytest.mark.asyncio
async def test_listener_rejects_qq_group_event_without_member_identity():
    plugin = FakePlugin()
    listener = IDCQueryEventListener()
    listener.plugin = plugin
    await listener.initialize()
    handler = listener.registered_handlers[events.GroupMessageReceived][0]
    event = SimpleNamespace(
        launcher_id='group-openid',
        sender_id='group-openid',
        message_event=SimpleNamespace(
            source_platform_object={
                't': 'GROUP_AT_MESSAGE_CREATE',
                'group_openid': 'group-openid',
                'd_id': 'message-id',
            }
        ),
        message_chain=platform_message.MessageChain([platform_message.Plain(text='解绑')]),
    )
    event_context = FakeEventContext(event)

    await handler(event_context)

    assert plugin.calls == []
    assert event_context.prevented_default is False
    assert event_context.prevented_postorder is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('group_id', 'member_id', 'message_id'),
    [
        ('group-openid', 'member-openid', ''),
        ('group-openid\u202eTXT', 'member-openid', 'message-id'),
        ('group-openid', '成员', 'message-id'),
    ],
)
async def test_listener_rejects_missing_or_unsafe_qq_identifiers(group_id, member_id, message_id):
    plugin = FakePlugin()
    listener = IDCQueryEventListener()
    listener.plugin = plugin
    await listener.initialize()
    handler = listener.registered_handlers[events.GroupMessageReceived][0]
    event = SimpleNamespace(
        launcher_id='fallback-group',
        sender_id='fallback-member',
        message_event=SimpleNamespace(
            source_platform_object={
                't': 'GROUP_AT_MESSAGE_CREATE',
                'group_openid': group_id,
                'member_openid': member_id,
                'd_id': message_id,
            }
        ),
        message_chain=platform_message.MessageChain([platform_message.Plain(text='查余额')]),
    )
    event_context = FakeEventContext(event)

    await handler(event_context)

    assert plugin.calls == []
    assert event_context.prevented_default is False


@pytest.mark.asyncio
async def test_listener_blocks_llm_when_query_processing_crashes():
    plugin = FailingPlugin()
    listener = IDCQueryEventListener()
    listener.plugin = plugin
    await listener.initialize()
    handler = listener.registered_handlers[events.GroupMessageReceived][0]
    event = SimpleNamespace(
        launcher_id='group-openid',
        sender_id='member-openid',
        message_event=SimpleNamespace(
            source_platform_object={
                't': 'GROUP_AT_MESSAGE_CREATE',
                'group_openid': 'group-openid',
                'member_openid': 'member-openid',
                'd_id': 'message-id',
            }
        ),
        message_chain=platform_message.MessageChain([platform_message.Plain(text='查余额')]),
    )
    event_context = FakeEventContext(event)

    await handler(event_context)

    assert event_context.prevented_default is True
    assert event_context.prevented_postorder is True
    assert list(event_context.replies[0])[0].text == '查询处理异常，请稍后重试或联系管理员。'
