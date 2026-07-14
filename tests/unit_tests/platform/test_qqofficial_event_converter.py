import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import ed25519
from quart import Quart

import langbot_plugin.api.entities.builtin.platform.message as platform_message
from langbot.libs.qq_official_api.api import QQOfficialClient
from langbot.libs.qq_official_api.qqofficialevent import QQOfficialEvent
from langbot.pkg.api.http.controller.groups.webhooks import QQWebhookRouterGroup, WebhookRouterGroup
from langbot.pkg.platform.sources.qqofficial import QQOfficialAdapter, QQOfficialEventConverter


def _logger():
    return SimpleNamespace(info=AsyncMock(), warning=AsyncMock(), error=AsyncMock())


def _qq_secret_seed(secret: str) -> bytes:
    seed = secret
    while len(seed) < 32:
        seed *= 2
    return seed[:32].encode()


def _signed_request(body: bytes, secret: str, timestamp: str | None = None):
    timestamp = timestamp or str(int(time.time()))
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(_qq_secret_seed(secret))
    signature = private_key.sign(timestamp.encode() + body).hex()
    return SimpleNamespace(
        headers={
            'X-Signature-Ed25519': signature,
            'X-Signature-Timestamp': timestamp,
        },
        get_data=AsyncMock(return_value=body),
    )


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


def _valid_message_payload(event_type: str) -> dict:
    event_data = {
        'id': f'message-{event_type.lower()}',
        'content': '帮助',
        'timestamp': '2026-07-11T04:00:00.123Z',
        'author': {},
    }
    if event_type == 'C2C_MESSAGE_CREATE':
        event_data['author'] = {'user_openid': 'user-openid'}
    elif event_type == 'GROUP_AT_MESSAGE_CREATE':
        event_data.update(
            {
                'group_openid': 'group-openid',
                'author': {'member_openid': 'member-openid'},
            }
        )
    elif event_type == 'DIRECT_MESSAGE_CREATE':
        event_data.update(
            {
                'guild_id': 'guild-id',
                'author': {'id': 'channel-user-id'},
            }
        )
    elif event_type == 'AT_MESSAGE_CREATE':
        event_data.update(
            {
                'channel_id': 'channel-id',
                'author': {'id': 'channel-user-id'},
            }
        )
    return {'op': 0, 't': event_type, 'd': event_data}


@pytest.mark.asyncio
async def test_group_message_preserves_member_and_group_openids():
    converted = await QQOfficialEventConverter.target2yiri(_group_event())

    assert converted.sender.id == 'member-openid'
    assert converted.sender.member_name == 'Customer'
    assert converted.sender.group.id == 'group-openid'
    assert converted.sender.group.name == 'group-openid'
    assert isinstance(list(converted.message_chain)[0], platform_message.At)


@pytest.mark.asyncio
async def test_channel_direct_message_uses_author_identity_and_fractional_timestamp():
    converted = await QQOfficialEventConverter.target2yiri(
        QQOfficialEvent(
            {
                't': 'DIRECT_MESSAGE_CREATE',
                'content': '帮助',
                'd_id': 'message-direct',
                'd_author_id': 'channel-user-id',
                'username': 'Channel User',
                'guild_id': 'direct-message-guild',
                'timestamp': '2026-07-11T04:00:00.123Z',
                'content_type': 'text/plain',
            }
        )
    )

    assert converted.sender.id == 'channel-user-id'
    assert converted.sender.nickname == 'Channel User'
    assert converted.time == 1783742400


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
    converted = await QQOfficialEventConverter.target2yiri(_group_event(content='<@!123456789>  查IP 1.1.1.1'))
    plain_parts = [item.text for item in converted.message_chain if isinstance(item, platform_message.Plain)]

    assert plain_parts == ['查IP 1.1.1.1']


@pytest.mark.asyncio
async def test_group_message_allows_empty_text_content():
    converted = await QQOfficialEventConverter.target2yiri(_group_event(content=None))
    plain_parts = [item for item in converted.message_chain if isinstance(item, platform_message.Plain)]

    assert plain_parts == []


def test_qqofficial_defaults_to_webhook_and_does_not_require_legacy_token():
    with open('src/langbot/pkg/platform/sources/qqofficial.yaml', encoding='utf-8') as file:
        config_items = yaml.safe_load(file)['spec']['config']

    config_by_name = {item['name']: item for item in config_items}
    assert config_by_name['enable-webhook']['default'] is True
    assert config_by_name['token']['required'] is False


@pytest.mark.parametrize('event_type', sorted(QQOfficialClient.MESSAGE_EVENT_TYPES))
def test_qq_message_event_validator_accepts_documented_shapes(event_type):
    assert QQOfficialClient.validate_message_event(_valid_message_payload(event_type)) is None


@pytest.mark.parametrize(
    ('event_type', 'invalid_fields', 'expected_error'),
    [
        ('C2C_MESSAGE_CREATE', {'author': {}}, 'invalid_user_openid'),
        ('GROUP_AT_MESSAGE_CREATE', {'group_openid': ''}, 'invalid_group_openid'),
        ('GROUP_AT_MESSAGE_CREATE', {'author': {}}, 'invalid_member_openid'),
        ('DIRECT_MESSAGE_CREATE', {'author': {}}, 'invalid_author_id'),
        ('DIRECT_MESSAGE_CREATE', {'guild_id': ''}, 'invalid_guild_id'),
        ('AT_MESSAGE_CREATE', {'author': {}}, 'invalid_author_id'),
        ('AT_MESSAGE_CREATE', {'channel_id': ''}, 'invalid_channel_id'),
    ],
)
def test_qq_message_event_validator_reports_missing_routing_identifiers(
    event_type,
    invalid_fields,
    expected_error,
):
    payload = _valid_message_payload(event_type)
    payload['d'].update(invalid_fields)

    assert QQOfficialClient.validate_message_event(payload) == expected_error


@pytest.mark.parametrize('event_type', [[], {}])
@pytest.mark.asyncio
async def test_qq_webhook_rejects_non_string_event_type(event_type):
    body = json.dumps({'id': 'invalid-type-event', 'op': 0, 't': event_type, 'd': {}}).encode()
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    client._handle_message = AsyncMock()

    response = await client.handle_unified_webhook(_signed_request(body, 'test-secret'))

    assert response == ({'error': 'invalid callback event'}, 400)
    assert QQOfficialClient.validate_message_event({'t': event_type}) == 'invalid_event_type'
    client._handle_message.assert_not_awaited()
    assert client.get_webhook_status()['rejected_total'] == 1
    assert client.get_webhook_status()['events_total'] == 0
    assert not client._seen_webhook_events


@pytest.mark.asyncio
async def test_qq_webhook_validation_returns_secret_signature():
    secret = 'test-secret'
    event_ts = str(int(time.time()))
    body = json.dumps(
        {'op': 13, 'd': {'plain_token': 'plain-token', 'event_ts': event_ts}},
        separators=(',', ':'),
    ).encode()
    request = SimpleNamespace(
        headers={'X-Bot-Appid': 'test-app'},
        get_data=AsyncMock(return_value=body),
    )
    client = QQOfficialClient(
        app_id='test-app',
        secret=secret,
        token='',
        logger=_logger(),
        unified_mode=True,
    )

    response, status = await client.handle_unified_webhook(request)

    assert status == 200
    assert response['plain_token'] == 'plain-token'
    metrics = client.get_webhook_status()
    assert metrics['requests_total'] == 1
    assert metrics['validations_total'] == 1
    assert metrics['rejected_total'] == 0
    assert metrics['last_valid_at'] is not None
    ed25519.Ed25519PrivateKey.from_private_bytes(_qq_secret_seed(secret)).public_key().verify(
        bytes.fromhex(response['signature']),
        f'{event_ts}plain-token'.encode(),
    )


@pytest.mark.asyncio
async def test_qq_webhook_validation_rejects_mismatching_app_id():
    event_ts = str(int(time.time()))
    body = json.dumps(
        {'op': 13, 'd': {'plain_token': 'plain-token', 'event_ts': event_ts}},
        separators=(',', ':'),
    ).encode()
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )

    wrong_header_response = await client.handle_unified_webhook(
        SimpleNamespace(
            headers={'X-Bot-Appid': 'different-app'},
            get_data=AsyncMock(return_value=body),
        )
    )

    assert wrong_header_response == ({'error': 'invalid bot app id'}, 401)
    assert client.get_webhook_status()['validations_total'] == 0
    assert client.get_webhook_status()['rejected_total'] == 1


@pytest.mark.asyncio
async def test_qq_webhook_validation_blocks_stale_and_json_signing_challenges():
    current_timestamp = str(int(time.time()))
    stale_timestamp = str(int(time.time()) - QQOfficialClient.CALLBACK_SIGNATURE_MAX_AGE_SECONDS - 1)
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )

    stale_body = json.dumps({'op': 13, 'd': {'plain_token': 'plain-token', 'event_ts': stale_timestamp}}).encode()
    signing_oracle_body = json.dumps(
        {
            'op': 13,
            'd': {
                'plain_token': '{"op":0,"d":{}}',
                'event_ts': current_timestamp,
            },
        }
    ).encode()

    stale_response = await client.handle_unified_webhook(
        SimpleNamespace(headers={}, get_data=AsyncMock(return_value=stale_body))
    )
    oracle_response = await client.handle_unified_webhook(
        SimpleNamespace(headers={}, get_data=AsyncMock(return_value=signing_oracle_body))
    )

    assert stale_response == ({'error': 'invalid callback validation payload'}, 400)
    assert oracle_response == ({'error': 'invalid callback validation payload'}, 400)
    assert client.get_webhook_status()['validations_total'] == 0
    assert client.get_webhook_status()['rejected_total'] == 2


@pytest.mark.asyncio
async def test_qq_webhook_rejects_unsigned_event():
    body = json.dumps({'op': 0, 't': 'GROUP_AT_MESSAGE_CREATE', 'd': {}}).encode()
    request = SimpleNamespace(headers={}, get_data=AsyncMock(return_value=body))
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )

    response, status = await client.handle_unified_webhook(request)

    assert status == 401
    assert response == {'error': 'invalid callback signature'}
    assert client.get_webhook_status()['rejected_total'] == 1


@pytest.mark.asyncio
async def test_qq_webhook_rejects_stale_signed_event():
    body = json.dumps({'op': 0, 't': 'GROUP_AT_MESSAGE_CREATE', 'd': {'id': 'message-stale'}}).encode()
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    stale_timestamp = str(int(time.time()) - client.CALLBACK_SIGNATURE_MAX_AGE_SECONDS - 1)

    response, status = await client.handle_unified_webhook(_signed_request(body, 'test-secret', stale_timestamp))

    assert status == 401
    assert response == {'error': 'invalid callback signature'}


@pytest.mark.asyncio
async def test_qq_webhook_acknowledges_signed_event_before_dispatch():
    body = json.dumps(
        {
            'op': 0,
            't': 'GROUP_AT_MESSAGE_CREATE',
            'd': {
                'id': 'message-1',
                'content': '帮助',
                'timestamp': '2026-07-11T12:00:00+08:00',
                'group_openid': 'group-openid',
                'author': {'member_openid': 'member-openid'},
            },
        },
        separators=(',', ':'),
    ).encode()
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    client._handle_message = AsyncMock()

    response, status = await client.handle_unified_webhook(_signed_request(body, 'test-secret'))
    await asyncio.sleep(0)

    assert status == 200
    assert response == {'op': 12}
    client._handle_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_qq_webhook_acknowledges_duplicate_event_without_dispatching_twice():
    body = json.dumps(
        {
            'id': 'event-duplicate',
            'op': 0,
            't': 'GROUP_AT_MESSAGE_CREATE',
            'd': {
                'id': 'message-duplicate',
                'content': '查余额',
                'timestamp': '2026-07-11T12:00:00+08:00',
                'group_openid': 'group-openid',
                'author': {'member_openid': 'member-openid'},
            },
        },
        separators=(',', ':'),
    ).encode()
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    client._handle_message = AsyncMock()

    first_response = await client.handle_unified_webhook(_signed_request(body, 'test-secret'))
    second_response = await client.handle_unified_webhook(_signed_request(body, 'test-secret'))
    await asyncio.sleep(0)

    assert first_response == ({'op': 12}, 200)
    assert second_response == ({'op': 12}, 200)
    client._handle_message.assert_awaited_once()
    metrics = client.get_webhook_status()
    assert metrics['requests_total'] == 2
    assert metrics['events_total'] == 1
    assert metrics['duplicates_total'] == 1
    assert metrics['last_event_at'] is not None


@pytest.mark.asyncio
async def test_qq_webhook_retries_an_event_after_pending_queue_recovers():
    def event_body(event_id: str) -> bytes:
        return json.dumps(
            {
                'id': f'event-{event_id}',
                'op': 0,
                't': 'GROUP_AT_MESSAGE_CREATE',
                'd': {
                    'id': event_id,
                    'content': '查余额',
                    'timestamp': '2026-07-11T12:00:00+08:00',
                    'group_openid': 'group-openid',
                    'author': {'member_openid': 'member-openid'},
                },
            },
            separators=(',', ':'),
        ).encode()

    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    client.CALLBACK_MAX_PENDING_EVENTS = 1
    handler_started = asyncio.Event()
    release_handler = asyncio.Event()
    handled_message_ids: list[str] = []

    async def slow_handler(event: QQOfficialEvent):
        handled_message_ids.append(event.d_id)
        handler_started.set()
        await release_handler.wait()

    client._handle_message = AsyncMock(side_effect=slow_handler)
    first_body = event_body('message-1')
    second_body = event_body('message-2')

    first_response = await client.handle_unified_webhook(_signed_request(first_body, 'test-secret'))
    await asyncio.wait_for(handler_started.wait(), timeout=1)
    overloaded_response = await client.handle_unified_webhook(_signed_request(second_body, 'test-secret'))

    assert first_response == ({'op': 12}, 200)
    assert overloaded_response == ({'error': 'callback temporarily unavailable'}, 503)
    assert handled_message_ids == ['message-1']
    metrics = client.get_webhook_status()
    assert metrics['pending_events'] == 1
    assert metrics['pending_limit'] == 1
    assert metrics['overloaded_total'] == 1
    assert metrics['rejected_total'] == 1
    assert metrics['last_overloaded_at'] is not None

    release_handler.set()
    await asyncio.gather(*tuple(client._webhook_tasks))
    retry_response = await client.handle_unified_webhook(_signed_request(second_body, 'test-secret'))
    await asyncio.gather(*tuple(client._webhook_tasks))

    assert retry_response == ({'op': 12}, 200)
    assert handled_message_ids == ['message-1', 'message-2']
    assert client.get_webhook_status()['pending_events'] == 0


@pytest.mark.asyncio
async def test_qq_webhook_rejects_invalid_message_before_ack_and_allows_corrected_retry():
    def event_body(author: object) -> bytes:
        return json.dumps(
            {
                'id': 'event-structure',
                'op': 0,
                't': 'GROUP_AT_MESSAGE_CREATE',
                'd': {
                    'id': 'message-structure',
                    'content': '帮助',
                    'timestamp': '2026-07-11T12:00:00+08:00',
                    'group_openid': 'group-openid',
                    'author': author,
                },
            },
            separators=(',', ':'),
        ).encode()

    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    client._handle_message = AsyncMock()

    rejected = await client.handle_unified_webhook(_signed_request(event_body([]), 'test-secret'))
    accepted = await client.handle_unified_webhook(
        _signed_request(event_body({'member_openid': 'member-openid'}), 'test-secret')
    )
    await asyncio.sleep(0)

    assert rejected == ({'error': 'invalid callback event'}, 400)
    assert accepted == ({'op': 12}, 200)
    client._handle_message.assert_awaited_once()
    metrics = client.get_webhook_status()
    assert metrics['rejected_total'] == 1
    assert metrics['events_total'] == 1


@pytest.mark.asyncio
async def test_qq_webhook_accepts_attachment_only_message_with_fractional_timestamp():
    body = json.dumps(
        {
            'op': 0,
            't': 'GROUP_AT_MESSAGE_CREATE',
            'd': {
                'id': 'message-image',
                'content': '',
                'timestamp': '2026-07-11T04:00:00.123Z',
                'group_openid': 'group-openid',
                'author': {'member_openid': 'member-openid'},
                'attachments': [{'content_type': 'image/png', 'url': 'example.qq.com/image.png'}],
            },
        },
        separators=(',', ':'),
    ).encode()
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    client._handle_message = AsyncMock()

    response = await client.handle_unified_webhook(_signed_request(body, 'test-secret'))
    await asyncio.sleep(0)

    assert response == ({'op': 12}, 200)
    event = client._handle_message.await_args.args[0]
    assert event.attachments == 'https://example.qq.com/image.png'
    assert event.content == ''


@pytest.mark.asyncio
async def test_qq_webhook_acknowledges_unknown_signed_event_without_dispatching():
    body = json.dumps({'op': 0, 't': 'GUILD_CREATE', 'd': 'future-compatible-payload'}).encode()
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    client._handle_message = AsyncMock()

    response = await client.handle_unified_webhook(_signed_request(body, 'test-secret'))

    assert response == ({'op': 12}, 200)
    client._handle_message.assert_not_awaited()
    assert client.get_webhook_status()['events_total'] == 1
    assert client.get_webhook_status()['pending_events'] == 0


@pytest.mark.asyncio
async def test_qq_adapter_kill_stops_client_background_tasks():
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    adapter = QQOfficialAdapter.model_construct(
        config={'enable-webhook': True},
        logger=_logger(),
        bot=client,
        bot_account_id='test-app',
        enable_webhook=True,
    )
    adapter._ws_task = None
    adapter.bot.CALLBACK_SHUTDOWN_TIMEOUT_SECONDS = 0
    webhook_task = asyncio.create_task(asyncio.Event().wait())
    token_task = asyncio.create_task(asyncio.Event().wait())
    adapter.bot._webhook_tasks.add(webhook_task)
    adapter.bot._token_refresh_task = token_task
    await asyncio.sleep(0)

    assert await adapter.kill() is True

    assert webhook_task.cancelled()
    assert token_task.cancelled()
    assert adapter.bot._token_refresh_task is None
    assert adapter.bot.get_webhook_status()['pending_events'] == 0


@pytest.mark.asyncio
async def test_qq_webhook_rejects_oversized_body_before_reading_it():
    request = SimpleNamespace(
        headers={},
        content_length=QQOfficialClient.CALLBACK_MAX_BODY_BYTES + 1,
        get_data=AsyncMock(),
    )
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )

    response, status = await client.handle_unified_webhook(request)

    assert status == 413
    assert response == {'error': 'callback payload too large'}
    request.get_data.assert_not_awaited()
    metrics = client.get_webhook_status()
    assert metrics['requests_total'] == 1
    assert metrics['rejected_total'] == 1


@pytest.mark.asyncio
async def test_qq_webhook_returns_generic_error_for_invalid_json():
    request = SimpleNamespace(headers={}, get_data=AsyncMock(return_value=b'{private-invalid-json'))
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )

    response, status = await client.handle_unified_webhook(request)

    assert status == 400
    assert response == {'error': 'invalid callback payload'}
    assert 'private-invalid-json' not in json.dumps(response)
    assert client.get_webhook_status()['rejected_total'] == 1


def test_qq_webhook_dedup_window_expires_and_remains_time_ordered(monkeypatch):
    client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    current_time = 1000.0
    monkeypatch.setattr(
        'langbot.libs.qq_official_api.api.time.monotonic',
        lambda: current_time,
    )
    payload = {'id': 'event-1', 'd': {}}

    assert client._is_duplicate_webhook_event(payload) is False
    current_time += client.CALLBACK_DEDUP_TTL_SECONDS - 1
    assert client._is_duplicate_webhook_event(payload) is True
    current_time += client.CALLBACK_DEDUP_TTL_SECONDS + 1
    assert client._is_duplicate_webhook_event(payload) is False


@pytest.mark.asyncio
async def test_qq_webhook_is_reachable_through_per_bot_http_route():
    body = json.dumps(
        {
            'op': 0,
            't': 'GROUP_AT_MESSAGE_CREATE',
            'd': {
                'id': 'message-1',
                'content': '帮助',
                'timestamp': '2026-07-11T12:00:00+08:00',
                'group_openid': 'group-openid',
                'author': {'member_openid': 'member-openid'},
            },
        },
        separators=(',', ':'),
    ).encode()
    qq_client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    qq_client._handle_message = AsyncMock()

    async def handle_unified_webhook(*, bot_uuid, path, request):
        assert bot_uuid == 'test-bot-uuid'
        assert path == ''
        return await qq_client.handle_unified_webhook(request)

    runtime_bot = SimpleNamespace(
        enable=True,
        adapter=SimpleNamespace(handle_unified_webhook=handle_unified_webhook),
    )
    application = SimpleNamespace(
        platform_mgr=SimpleNamespace(get_bot_by_uuid=AsyncMock(return_value=runtime_bot)),
        logger=_logger(),
    )
    quart_app = Quart(__name__)
    router = WebhookRouterGroup(application, quart_app)
    await router.initialize()
    signed_headers = _signed_request(body, 'test-secret').headers

    response = await quart_app.test_client().post(
        '/bots/test-bot-uuid',
        data=body,
        headers={**signed_headers, 'Content-Type': 'application/json'},
    )
    await asyncio.sleep(0)

    assert response.status_code == 200
    assert await response.get_json() == {'op': 12}
    qq_client._handle_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_qq_webhook_is_reachable_through_stable_callback_route():
    body = json.dumps(
        {
            'op': 0,
            't': 'GROUP_AT_MESSAGE_CREATE',
            'd': {
                'id': 'message-2',
                'content': '查IP 1.1.1.1',
                'timestamp': '2026-07-11T12:00:00+08:00',
                'group_openid': 'group-openid',
                'author': {'member_openid': 'member-openid'},
            },
        },
        separators=(',', ':'),
    ).encode()
    qq_client = QQOfficialClient(
        app_id='test-app',
        secret='test-secret',
        token='',
        logger=_logger(),
        unified_mode=True,
    )
    qq_client._handle_message = AsyncMock()

    async def handle_unified_webhook(*, bot_uuid, path, request):
        assert bot_uuid == 'test-bot-uuid'
        assert path == ''
        return await qq_client.handle_unified_webhook(request)

    adapter = SimpleNamespace(
        bot=SimpleNamespace(app_id='test-app'),
        enable_webhook=True,
        handle_unified_webhook=handle_unified_webhook,
    )
    runtime_bot = SimpleNamespace(
        enable=True,
        adapter=adapter,
        bot_entity=SimpleNamespace(uuid='test-bot-uuid', adapter='qqofficial'),
    )
    application = SimpleNamespace(
        platform_mgr=SimpleNamespace(bots=[runtime_bot]),
        logger=_logger(),
    )
    quart_app = Quart(__name__)
    router = QQWebhookRouterGroup(application, quart_app)
    await router.initialize()
    signed_headers = _signed_request(body, 'test-secret').headers

    response = await quart_app.test_client().post(
        '/qq/callback',
        data=body,
        headers={
            **signed_headers,
            'Content-Type': 'application/json',
            'X-Bot-Appid': 'test-app',
        },
    )
    await asyncio.sleep(0)

    assert response.status_code == 200
    assert await response.get_json() == {'op': 12}
    qq_client._handle_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_per_bot_webhook_route_hides_internal_dispatch_errors():
    secret = 'token=/private/runtime/config.env'
    application = SimpleNamespace(
        platform_mgr=SimpleNamespace(get_bot_by_uuid=AsyncMock(side_effect=RuntimeError(secret))),
        logger=SimpleNamespace(error=Mock()),
    )
    quart_app = Quart(__name__)
    router = WebhookRouterGroup(application, quart_app)
    await router.initialize()

    response = await quart_app.test_client().post('/bots/test-bot-uuid', data=b'{}')
    response_data = await response.get_json()

    assert response.status_code == 500
    assert response_data == {'error': 'Webhook dispatch failed'}
    assert secret not in json.dumps(response_data)


@pytest.mark.asyncio
async def test_stable_qq_webhook_route_hides_internal_dispatch_errors():
    secret = 'secret loaded from /private/qq-config.yaml'
    adapter = SimpleNamespace(
        bot=SimpleNamespace(app_id='test-app'),
        enable_webhook=True,
        handle_unified_webhook=AsyncMock(side_effect=RuntimeError(secret)),
    )
    runtime_bot = SimpleNamespace(
        enable=True,
        adapter=adapter,
        bot_entity=SimpleNamespace(uuid='test-bot-uuid', adapter='qqofficial'),
    )
    application = SimpleNamespace(
        platform_mgr=SimpleNamespace(bots=[runtime_bot]),
        logger=SimpleNamespace(error=Mock()),
    )
    quart_app = Quart(__name__)
    router = QQWebhookRouterGroup(application, quart_app)
    await router.initialize()

    response = await quart_app.test_client().post(
        '/qq/callback',
        data=b'{}',
        headers={'X-Bot-Appid': 'test-app'},
    )
    response_data = await response.get_json()

    assert response.status_code == 500
    assert response_data == {'error': 'QQ webhook dispatch failed'}
    assert secret not in json.dumps(response_data)
