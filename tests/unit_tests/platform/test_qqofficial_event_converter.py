import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import ed25519
from quart import Quart

import langbot_plugin.api.entities.builtin.platform.message as platform_message
from langbot.libs.qq_official_api.api import QQOfficialClient
from langbot.libs.qq_official_api.qqofficialevent import QQOfficialEvent
from langbot.pkg.api.http.controller.groups.webhooks import QQWebhookRouterGroup, WebhookRouterGroup
from langbot.pkg.platform.sources.qqofficial import QQOfficialEventConverter


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
