import asyncio
import gzip
import json

from aiohttp import web
import pytest

from idc_query_core.commands import CommandType
from idc_query_core.gateway import GATEWAY_BUSY_MESSAGE, MAX_RESPONSE_BYTES, GatewayError, IDCQueryGateway


async def _start_server(app: web.Application) -> tuple[web.AppRunner, int]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]


async def _query(gateway: IDCQueryGateway, **overrides):
    arguments = overrides.pop('arguments', {'ip': '1.1.1.1'})
    return await gateway.query(
        command_type=overrides.pop('command_type', CommandType.IP),
        arguments=arguments,
        group_id=overrides.pop('group_id', 'group-1'),
        user_id=overrides.pop('user_id', 'user-1'),
        member_id=overrides.pop('member_id', 'member-1'),
        request_id=overrides.pop('request_id', 'message-1'),
        **overrides,
    )


@pytest.mark.asyncio
async def test_gateway_sends_service_auth_and_tenant_headers():
    captured = {}

    async def handle_summary(request):
        captured['headers'] = dict(request.headers)
        captured['ip'] = request.match_info['ip']
        return web.json_response({'ok': True, 'data': {'ip': request.match_info['ip']}})

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_summary)
    runner, port = await _start_server(app)

    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='service-token',
        timeout_seconds=2,
        verify_tls=True,
    )
    try:
        payload = await _query(gateway)
    finally:
        await runner.cleanup()

    assert payload['data']['ip'] == '1.1.1.1'
    assert captured['ip'] == '1.1.1.1'
    assert captured['headers']['Authorization'] == 'Bearer service-token'
    assert captured['headers']['X-QQ-Group-ID'] == 'group-1'
    assert captured['headers']['X-QQ-User-ID'] == 'user-1'
    assert captured['headers']['X-IDC-Member-ID'] == 'member-1'
    assert captured['headers']['X-Request-ID'] == 'message-1'


@pytest.mark.asyncio
async def test_gateway_bounds_concurrent_outbound_requests():
    active_requests = 0
    max_active_requests = 0
    saturated = asyncio.Event()
    release_requests = asyncio.Event()

    async def handle_summary(request):
        nonlocal active_requests, max_active_requests
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        if active_requests == 2:
            saturated.set()
        try:
            await release_requests.wait()
            return web.json_response({'ok': True, 'data': {'ip': request.match_info['ip']}})
        finally:
            active_requests -= 1

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_summary)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
        max_concurrent_requests=2,
    )
    tasks = [asyncio.create_task(_query(gateway, request_id=f'message-{index}')) for index in range(6)]
    payloads = []

    try:
        await asyncio.wait_for(saturated.wait(), timeout=1)
        await asyncio.sleep(0.05)
        assert active_requests == 2
        release_requests.set()
        payloads = await asyncio.gather(*tasks)
    finally:
        release_requests.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await runner.cleanup()

    assert max_active_requests == 2
    assert len(payloads) == 6
    assert all(payload['ok'] is True for payload in payloads)


@pytest.mark.asyncio
async def test_gateway_does_not_start_network_when_request_slots_time_out(monkeypatch: pytest.MonkeyPatch):
    class UnexpectedSession:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError('network access must not start')

    monkeypatch.setattr('idc_query_core.gateway.aiohttp.ClientSession', UnexpectedSession)
    gateway = IDCQueryGateway(
        base_url='https://query.example.com',
        token='',
        timeout_seconds=1,
        verify_tls=True,
        max_concurrent_requests=1,
    )
    gateway.timeout_seconds = 0.01
    await gateway._request_slots.acquire()
    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        gateway._request_slots.release()

    assert exc_info.value.public_message == GATEWAY_BUSY_MESSAGE


@pytest.mark.asyncio
async def test_gateway_does_not_follow_redirects_or_forward_identity_headers():
    redirect_target_calls = []

    async def handle_redirect(_request):
        raise web.HTTPFound('/redirect-target')

    async def handle_redirect_target(request):
        redirect_target_calls.append(dict(request.headers))
        return web.json_response({'ok': True, 'data': {}})

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_redirect)
    app.router.add_get('/redirect-target', handle_redirect_target)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='service-token',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError, match='重定向'):
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert redirect_target_calls == []


@pytest.mark.asyncio
async def test_gateway_limits_decompressed_response_size():
    response_body = json.dumps(
        {'ok': True, 'data': {'text': 'x' * MAX_RESPONSE_BYTES}},
        separators=(',', ':'),
    ).encode()
    compressed_body = gzip.compress(response_body)
    assert len(compressed_body) < MAX_RESPONSE_BYTES

    async def handle_large_response(_request):
        return web.Response(
            body=compressed_body,
            headers={'Content-Encoding': 'gzip'},
            content_type='application/json',
        )

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_large_response)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError, match='数据过大'):
            await _query(gateway)
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('status', 'expected_message'),
    [
        (401, '查询服务鉴权失败，请联系管理员检查网关服务令牌。'),
        (403, '当前会员无权执行该操作，请联系管理员确认权限。'),
        (429, '查询请求过于频繁，请稍后重试。'),
        (500, '查询服务暂时不可用，请稍后重试。'),
    ],
)
async def test_gateway_maps_http_errors_without_returning_upstream_details(status: int, expected_message: str):
    upstream_secret = 'postgresql://admin:password@private-db/customer?token=secret'

    async def handle_error(_request):
        return web.json_response(
            {'ok': False, 'message': upstream_secret, 'debug': {'sql': 'SELECT * FROM customer'}},
            status=status,
        )

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_error)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == expected_message
    assert upstream_secret not in exc_info.value.public_message
    assert 'SELECT' not in exc_info.value.public_message


@pytest.mark.asyncio
async def test_gateway_does_not_parse_an_error_response_body():
    async def handle_error(_request):
        return web.Response(
            body=b'private stack trace: {malformed-json' + b'x' * (MAX_RESPONSE_BYTES + 1),
            status=500,
            content_type='application/json',
        )

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_error)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询服务暂时不可用，请稍后重试。'
    assert 'private stack trace' not in exc_info.value.public_message


@pytest.mark.parametrize(
    ('timeout_seconds', 'expected'),
    [
        (0, 1.0),
        (3600, 120.0),
        (float('inf'), 8.0),
        (float('nan'), 8.0),
        ('invalid', 8.0),
    ],
)
def test_gateway_bounds_invalid_or_extreme_timeouts(timeout_seconds, expected: float):
    gateway = IDCQueryGateway(
        base_url='https://query.example.com',
        token='',
        timeout_seconds=timeout_seconds,
        verify_tls=True,
    )

    assert gateway.timeout_seconds == expected


@pytest.mark.asyncio
async def test_gateway_maps_allowlisted_binding_error_code_without_returning_raw_message():
    async def handle_binding(_request):
        return web.json_response(
            {
                'ok': False,
                'error': {'code': 'invalid_verification_code'},
                'message': 'verification SQL failed at private-auth:5432',
            }
        )

    app = web.Application()
    app.router.add_post('/v1/bindings/verify', handle_binding)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await gateway.verify_binding(
                group_id='group-1',
                user_id='user-1',
                member_id='member-1',
                verification_code='938421',
                request_id='message-1',
            )
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '绑定验证未通过，请检查会员号和验证码后重试。'
    assert 'private-auth' not in exc_info.value.public_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('operation', 'expected_message'),
    [
        ('binding', '绑定验证请求过于频繁，请稍后重试。'),
        ('query', '查询请求过于频繁，请稍后重试。'),
    ],
)
async def test_gateway_maps_rate_limit_error_code_by_operation(operation: str, expected_message: str):
    async def handle_rate_limit(_request):
        return web.json_response({'ok': False, 'error': {'code': 'RATE_LIMITED'}})

    app = web.Application()
    app.router.add_post('/v1/bindings/verify', handle_rate_limit)
    app.router.add_get('/v1/ip/{ip}/summary', handle_rate_limit)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            if operation == 'binding':
                await gateway.verify_binding(
                    group_id='group-1',
                    user_id='user-1',
                    member_id='member-1',
                    verification_code='938421',
                    request_id='message-1',
                )
            else:
                await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == expected_message


@pytest.mark.asyncio
async def test_gateway_maps_unknown_error_code_to_fixed_operation_message():
    async def handle_unknown(_request):
        return web.json_response(
            {
                'ok': False,
                'error': {'code': 'INTERNAL_SQL_FAILURE'},
                'message': 'private-db password=secret',
            }
        )

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_unknown)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询未成功，请稍后重试。'
    assert 'private-db' not in exc_info.value.public_message


@pytest.mark.asyncio
async def test_gateway_rejects_malformed_json_with_a_fixed_message():
    async def handle_malformed(_request):
        return web.Response(text='private stack trace: {broken', content_type='application/json')

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_malformed)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询服务返回了无法识别的数据。'
    assert 'private stack trace' not in exc_info.value.public_message


@pytest.mark.asyncio
async def test_gateway_rejects_json_with_excessive_item_count():
    response_payload = {'ok': True, 'data': list(range(4097))}

    async def handle_many_items(_request):
        return web.json_response(response_payload)

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_many_items)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询服务返回的数据结构过于复杂。'


@pytest.mark.asyncio
async def test_gateway_rejects_non_standard_json_constants():
    async def handle_nan(_request):
        return web.Response(body=b'{"ok":true,"data":{"value":NaN}}', content_type='application/json')

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_nan)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询服务返回了无法识别的数据。'


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid_ok', ['true', 1, None])
async def test_gateway_rejects_non_boolean_ok_field(invalid_ok):
    async def handle_invalid_ok(_request):
        return web.json_response({'ok': invalid_ok, 'data': {}})

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_invalid_ok)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询服务返回了无法识别的数据。'


@pytest.mark.asyncio
async def test_gateway_rejects_missing_ok_without_rendering_error_metadata():
    upstream_secret = 'private-db password=secret'

    async def handle_missing_ok(_request):
        return web.json_response(
            {'error': {'code': 'INTERNAL_SQL_FAILURE', 'message': upstream_secret}},
        )

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_missing_ok)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询服务返回了无法识别的数据。'
    assert upstream_secret not in exc_info.value.public_message


@pytest.mark.asyncio
async def test_gateway_accepts_empty_successful_unbind_response():
    captured = {}

    async def handle_unbind(request):
        captured['headers'] = dict(request.headers)
        return web.Response(status=204)

    app = web.Application()
    app.router.add_delete('/v1/bindings/{group_id}', handle_unbind)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        await gateway.unbind(
            group_id='group-1',
            user_id='user-1',
            member_id='member-1',
            request_id='message-1',
        )
    finally:
        await runner.cleanup()

    assert captured['headers']['X-IDC-Member-ID'] == 'member-1'


@pytest.mark.asyncio
async def test_gateway_rejects_non_utf8_json():
    async def handle_non_utf8(_request):
        return web.Response(body=b'{"ok":true,"data":{"text":"\xff"}}', content_type='application/json')

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_non_utf8)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询服务返回了无法识别的数据。'


@pytest.mark.asyncio
async def test_gateway_rejects_excessively_nested_json_with_a_fixed_message():
    nested_json = b'{"ok":true,"data":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}'

    async def handle_nested(_request):
        return web.Response(body=nested_json, content_type='application/json')

    app = web.Application()
    app.router.add_get('/v1/ip/{ip}/summary', handle_nested)
    runner, port = await _start_server(app)
    gateway = IDCQueryGateway(
        base_url=f'http://127.0.0.1:{port}',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    try:
        with pytest.raises(GatewayError) as exc_info:
            await _query(gateway)
    finally:
        await runner.cleanup()

    assert exc_info.value.public_message == '查询服务返回的数据结构过于复杂。'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('gateway_kwargs', 'query_kwargs', 'expected_message'),
    [
        ({'token': 'secret\r\nX-Injected: yes'}, {}, '服务令牌配置无效'),
        ({'token': '令牌'}, {}, '服务令牌配置无效'),
        ({'token': ''}, {'group_id': 'group-1\r\nX-Injected: yes'}, '身份信息无效'),
        ({'token': ''}, {'group_id': '群组'}, '身份信息无效'),
        ({'token': ''}, {'group_id': 'group-1\u202eTXT'}, '身份信息无效'),
        ({'token': '', 'base_url': 'https://user:pass@query.example.com'}, {}, '网关配置无效'),
        ({'token': '', 'base_url': 'https://query.example.com/\u202eTXT'}, {}, '网关配置无效'),
        ({'token': '', 'base_url': None}, {}, '网关配置无效'),
        ({'token': '', 'verify_tls': 'true'}, {}, 'TLS 配置无效'),
    ],
)
async def test_gateway_rejects_invalid_outbound_configuration_before_network_access(
    monkeypatch: pytest.MonkeyPatch,
    gateway_kwargs: dict,
    query_kwargs: dict,
    expected_message: str,
):
    class UnexpectedSession:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError('network access must not start')

    monkeypatch.setattr('idc_query_core.gateway.aiohttp.ClientSession', UnexpectedSession)
    defaults = {
        'base_url': 'https://query.example.com',
        'token': '',
        'timeout_seconds': 2,
        'verify_tls': True,
    }
    defaults.update(gateway_kwargs)
    gateway = IDCQueryGateway(**defaults)

    with pytest.raises(GatewayError, match=expected_message):
        await _query(gateway, **query_kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('member_id', 'verification_code', 'expected_message'),
    [
        ('m', '938421', '身份信息无效'),
        ('member-1', '12ab', '验证码格式无效'),
        ('member-1', '123', '验证码格式无效'),
        ('member-1', 938421, '验证码格式无效'),
    ],
)
async def test_gateway_validates_binding_body_before_network_access(
    monkeypatch: pytest.MonkeyPatch,
    member_id,
    verification_code,
    expected_message: str,
):
    class UnexpectedSession:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError('network access must not start')

    monkeypatch.setattr('idc_query_core.gateway.aiohttp.ClientSession', UnexpectedSession)
    gateway = IDCQueryGateway(
        base_url='https://query.example.com',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    with pytest.raises(GatewayError, match=expected_message):
        await gateway.verify_binding(
            group_id='group-1',
            user_id='user-1',
            member_id=member_id,
            verification_code=verification_code,
            request_id='message-1',
        )


@pytest.mark.asyncio
async def test_gateway_validates_ip_argument_before_network_access(monkeypatch: pytest.MonkeyPatch):
    class UnexpectedSession:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError('network access must not start')

    monkeypatch.setattr('idc_query_core.gateway.aiohttp.ClientSession', UnexpectedSession)
    gateway = IDCQueryGateway(
        base_url='https://query.example.com',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    for arguments in ({}, {'ip': 'not-an-ip'}):
        with pytest.raises(GatewayError, match='查询条件无效'):
            await _query(gateway, arguments=arguments)


@pytest.mark.asyncio
async def test_gateway_validates_unbind_group_before_path_encoding(monkeypatch: pytest.MonkeyPatch):
    class UnexpectedSession:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError('network access must not start')

    monkeypatch.setattr('idc_query_core.gateway.aiohttp.ClientSession', UnexpectedSession)
    gateway = IDCQueryGateway(
        base_url='https://query.example.com',
        token='',
        timeout_seconds=2,
        verify_tls=True,
    )

    with pytest.raises(GatewayError, match='身份信息无效'):
        await gateway.unbind(
            group_id={'invalid': 'object'},
            user_id='user-1',
            member_id='member-1',
            request_id='message-1',
        )
