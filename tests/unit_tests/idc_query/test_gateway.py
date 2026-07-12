from aiohttp import web
import pytest

from idc_query_core.commands import CommandType
from idc_query_core.gateway import IDCQueryGateway


@pytest.mark.asyncio
async def test_gateway_sends_service_auth_and_tenant_headers():
    captured = {}

    async def handle_summary(request):
        captured['headers'] = dict(request.headers)
        captured['ip'] = request.match_info['ip']
        return web.json_response({'ok': True, 'data': {'ip': request.match_info['ip']}})

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_summary)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='service-token',
        timeout_seconds=2,
        verify_tls=True,
    )
    try:
        payload = await gateway.query(
            command_type=CommandType.IP,
            arguments={'ip': '1.1.1.1'},
            group_id='group-1',
            user_id='user-1',
            member_id='member-1',
            request_id='message-1',
        )
    finally:
        await runner.cleanup()

    assert payload['data']['ip'] == '1.1.1.1'
    assert captured['ip'] == '1.1.1.1'
    assert captured['headers']['Authorization'] == 'Bearer service-token'
    assert captured['headers']['X-QQ-Group-ID'] == 'group-1'
    assert captured['headers']['X-QQ-User-ID'] == 'user-1'
    assert captured['headers']['X-IDC-Member-ID'] == 'member-1'
    assert captured['headers']['X-Request-ID'] == 'message-1'
