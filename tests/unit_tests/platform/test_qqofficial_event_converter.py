import pytest

import langbot_plugin.api.entities.builtin.platform.message as platform_message
from langbot.libs.qq_official_api.api import QQOfficialClient
from langbot.libs.qq_official_api.qqofficialevent import QQOfficialEvent
from langbot.pkg.platform.sources.qqofficial import QQOfficialEventConverter


def _group_event(**overrides) -> QQOfficialEvent:
    payload = {
        't': 'GROUP_AT_MESSAGE_CREATE',
        'content': '查IP 1.1.1.1',
        'd_id': 'message-1',
        'timestamp': '2026-07-11T12:00:00+08:00',
        'group_openid': 'group-openid',
        'member_openid': 'member-openid',
        'username': 'Customer',
        'content_type': 'text/plain',
    }
    payload.update(overrides)
    return QQOfficialEvent(payload)


@pytest.mark.asyncio
async def test_group_message_preserves_member_and_group_openids():
    converted = await QQOfficialEventConverter.target2yiri(_group_event())

    assert converted.sender.id == 'member-openid'
    assert converted.sender.member_name == 'Customer'
    assert converted.sender.group.id == 'group-openid'
    assert converted.sender.group.name == 'group-openid'
    assert isinstance(list(converted.message_chain)[0], platform_message.At)


@pytest.mark.asyncio
async def test_group_message_falls_back_to_group_id_when_member_openid_is_missing():
    converted = await QQOfficialEventConverter.target2yiri(_group_event(member_openid='', username=''))

    assert converted.sender.id == 'group-openid'
    assert converted.sender.group.id == 'group-openid'


def test_event_model_accepts_legacy_openid_field():
    event = QQOfficialEvent({'openid': 'legacy-member-openid'})

    assert event.member_openid == 'legacy-member-openid'


@pytest.mark.asyncio
async def test_normalized_qq_payload_keeps_group_member_identity():
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='test-token',
        logger=None,
        unified_mode=True,
    )
    normalized = await client.get_message(
        {
            't': 'GROUP_AT_MESSAGE_CREATE',
            'd': {
                'id': 'message-1',
                'content': '查IP 1.1.1.1',
                'timestamp': '2026-07-11T12:00:00+08:00',
                'group_openid': 'group-openid',
                'author': {'member_openid': 'member-openid', 'username': 'Customer'},
            },
        }
    )

    converted = await QQOfficialEventConverter.target2yiri(QQOfficialEvent.from_payload(normalized))

    assert converted.sender.id == 'member-openid'
    assert converted.sender.group.id == 'group-openid'


@pytest.mark.asyncio
async def test_normalized_qq_payload_accepts_legacy_author_openid():
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='test-token',
        logger=None,
        unified_mode=True,
    )
    normalized = await client.get_message(
        {
            't': 'GROUP_AT_MESSAGE_CREATE',
            'd': {
                'id': 'message-1',
                'content': '帮助',
                'timestamp': '2026-07-11T12:00:00+08:00',
                'group_openid': 'group-openid',
                'author': {'openid': 'legacy-member-openid'},
            },
        }
    )

    assert normalized['member_openid'] == 'legacy-member-openid'


@pytest.mark.asyncio
async def test_text_message_without_attachment_does_not_download_image(monkeypatch):
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError('image downloader should not be called for text-only messages')

    monkeypatch.setattr(
        'langbot.pkg.platform.sources.qqofficial.image.get_qq_official_image_base64',
        fail_if_called,
    )

    converted = await QQOfficialEventConverter.target2yiri(_group_event())
    plain_parts = [item.text for item in converted.message_chain if isinstance(item, platform_message.Plain)]

    assert plain_parts == ['查IP 1.1.1.1']


@pytest.mark.asyncio
async def test_group_message_removes_bot_mention_from_plain_text():
    converted = await QQOfficialEventConverter.target2yiri(
        _group_event(content='<@!123456789>  查IP 1.1.1.1')
    )
    plain_parts = [item.text for item in converted.message_chain if isinstance(item, platform_message.Plain)]

    assert plain_parts == ['查IP 1.1.1.1']


@pytest.mark.asyncio
async def test_group_message_allows_empty_text_content():
    converted = await QQOfficialEventConverter.target2yiri(_group_event(content=None))
    plain_parts = [item for item in converted.message_chain if isinstance(item, platform_message.Plain)]

    assert plain_parts == []
