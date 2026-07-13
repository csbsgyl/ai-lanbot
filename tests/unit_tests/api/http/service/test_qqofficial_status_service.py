from types import SimpleNamespace

from langbot.pkg.api.http.service.qqofficial_status import QQOfficialStatusService


def _qq_runtime_bot(
    *,
    uuid: str,
    name: str,
    app_id: str,
    enabled: bool = True,
    webhook: bool = True,
):
    metrics = {
        'started_at': '2026-07-13T10:00:00+00:00',
        'requests_total': 3,
        'validations_total': 1,
        'events_total': 2,
        'duplicates_total': 0,
        'rejected_total': 0,
        'overloaded_total': 0,
        'pending_events': 0,
        'pending_limit': 256,
        'last_request_at': '2026-07-13T10:05:00+00:00',
        'last_valid_at': '2026-07-13T10:05:00+00:00',
        'last_event_at': '2026-07-13T10:05:00+00:00',
        'last_rejected_at': None,
        'last_overloaded_at': None,
    }
    client = SimpleNamespace(app_id=app_id, get_webhook_status=lambda: metrics)
    return SimpleNamespace(
        enable=enabled,
        bot_entity=SimpleNamespace(uuid=uuid, name=name, adapter='qqofficial'),
        adapter=SimpleNamespace(enable_webhook=webhook, bot=client),
    )


async def test_reports_ready_webhook_without_secrets():
    runtime_bot = _qq_runtime_bot(uuid='bot-1', name='IDC Bot', app_id='1029384756')
    ap = SimpleNamespace(
        instance_config=SimpleNamespace(data={'api': {'webhook_prefix': 'https://bot.example.com/'}}),
        platform_mgr=SimpleNamespace(bots=[runtime_bot]),
    )

    result = await QQOfficialStatusService(ap).get_status()

    assert result['status'] == 'ready'
    assert result['configured_callback_url'] == 'https://bot.example.com/qq/callback'
    assert result['configured_bots'] == 1
    assert result['active_webhook_bots'] == 1
    assert result['bots'][0]['app_id'] == '1029384756'
    assert result['bots'][0]['metrics']['events_total'] == 2
    assert result['bots'][0]['metrics']['pending_limit'] == 256
    assert 'secret' not in str(result).lower()
    assert 'token' not in str(result).lower()


async def test_distinguishes_modes_and_app_id_conflicts():
    websocket_bot = _qq_runtime_bot(
        uuid='bot-ws',
        name='WebSocket Bot',
        app_id='app-ws',
        webhook=False,
    )
    ap = SimpleNamespace(
        instance_config=SimpleNamespace(data={'api': {}}),
        platform_mgr=SimpleNamespace(bots=[websocket_bot]),
    )
    service = QQOfficialStatusService(ap)

    websocket_result = await service.get_status()
    assert websocket_result['status'] == 'websocket_mode'
    assert websocket_result['bots'][0]['metrics'] is None

    ap.platform_mgr.bots = [
        _qq_runtime_bot(uuid='bot-1', name='First', app_id='duplicate-app'),
        _qq_runtime_bot(uuid='bot-2', name='Second', app_id='duplicate-app'),
    ]
    conflict_result = await service.get_status()
    assert conflict_result['status'] == 'conflict'
    assert conflict_result['active_webhook_bots'] == 2


async def test_reports_when_no_bot_is_configured():
    ap = SimpleNamespace(
        instance_config=SimpleNamespace(data={'api': {}}),
        platform_mgr=SimpleNamespace(bots=[]),
    )

    result = await QQOfficialStatusService(ap).get_status()

    assert result['status'] == 'not_configured'
    assert result['bots'] == []
