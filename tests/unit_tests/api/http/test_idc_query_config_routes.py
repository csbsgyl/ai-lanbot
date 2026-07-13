from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
import quart

from langbot.pkg.api.http.controller.groups.system import SystemRouterGroup
from langbot.pkg.api.http.service.idc_query_config import IDCQueryConfigValidationError
from tests.factories import FakeApp


@pytest.fixture
async def idc_config_route_client():
    app = FakeApp()
    app.user_service = Mock()
    app.user_service.verify_jwt_token = AsyncMock(return_value='admin@example.com')
    app.user_service.get_user_by_email = AsyncMock(return_value=Mock())
    app.idc_query_config_service = Mock()
    app.idc_query_config_service.get_config = AsyncMock(
        return_value={
            'base_url': 'https://query.example.com',
            'timeout_seconds': 8,
            'verify_tls': True,
            'token_configured': True,
            'configured': True,
            'requests_per_minute': 20,
            'bind_attempts_per_10_minutes': 5,
        }
    )
    app.idc_query_config_service.update_config = AsyncMock(
        return_value={
            'base_url': 'https://new-query.example.com',
            'timeout_seconds': 10,
            'verify_tls': True,
            'token_configured': True,
            'configured': True,
            'requests_per_minute': 30,
            'bind_attempts_per_10_minutes': 4,
        }
    )
    app.idc_query_config_service.test_connection = AsyncMock(
        return_value={
            'status': 'reachable',
            'reachable': True,
            'http_status': 204,
            'latency_ms': 18,
            'tls_status': 'verified',
            'auth_status': 'not_verified',
            'token_configured': True,
            'checked_at': '2026-07-13T10:00:00+00:00',
        }
    )
    app.idc_query_config_service.get_audit_events = AsyncMock(
        return_value={
            'events': [
                {
                    'timestamp': '2026-07-12T10:00:00+00:00',
                    'command': 'ip',
                    'outcome': 'success',
                    'reason': 'queried',
                    'group_id': 'group-1',
                    'user_id': 'user-1',
                    'member_id': 'member-1',
                    'request_id': 'request-1',
                    'duration_ms': 12,
                }
            ],
            'count': 1,
            'generated_at': '2026-07-12T10:00:01+00:00',
        }
    )
    app.idc_query_config_service.get_bindings = AsyncMock(
        return_value={
            'bindings': [
                {
                    'group_id': 'group-1',
                    'member_id': 'member-1',
                    'bound_by': 'user-1',
                    'bound_at': '2026-07-12T10:00:00+00:00',
                    'member_name': 'Customer One',
                }
            ],
            'count': 1,
            'total': 1,
            'generated_at': '2026-07-12T10:00:01+00:00',
        }
    )

    quart_app = quart.Quart(__name__)
    router = SystemRouterGroup(app, quart_app)
    await router.initialize()
    return quart_app.test_client(), app


@pytest.mark.asyncio
async def test_idc_config_routes_require_user_authentication(idc_config_route_client):
    client, _ = idc_config_route_client

    get_response = await client.get('/api/v1/system/idc-query')
    put_response = await client.put('/api/v1/system/idc-query', json={})
    audit_response = await client.get('/api/v1/system/idc-query/audit')
    bindings_response = await client.get('/api/v1/system/idc-query/bindings')
    test_response = await client.post('/api/v1/system/idc-query/test', json={})

    assert get_response.status_code == 401
    assert put_response.status_code == 401
    assert audit_response.status_code == 401
    assert bindings_response.status_code == 401
    assert test_response.status_code == 401


@pytest.mark.asyncio
async def test_idc_config_routes_reject_api_key_authentication(idc_config_route_client):
    client, app = idc_config_route_client

    response = await client.put(
        '/api/v1/system/idc-query',
        headers={'X-API-Key': 'automation-key'},
        json={'token': 'must-not-be-accepted'},
    )

    assert response.status_code == 401
    app.idc_query_config_service.update_config.assert_not_awaited()

    audit_response = await client.get(
        '/api/v1/system/idc-query/audit',
        headers={'X-API-Key': 'automation-key'},
    )
    assert audit_response.status_code == 401
    app.idc_query_config_service.get_audit_events.assert_not_awaited()

    bindings_response = await client.get(
        '/api/v1/system/idc-query/bindings',
        headers={'X-API-Key': 'automation-key'},
    )
    assert bindings_response.status_code == 401
    app.idc_query_config_service.get_bindings.assert_not_awaited()

    test_response = await client.post(
        '/api/v1/system/idc-query/test',
        headers={'X-API-Key': 'automation-key'},
        json={'token': 'must-not-be-accepted'},
    )
    assert test_response.status_code == 401
    app.idc_query_config_service.test_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_idc_config_routes_read_and_update_settings(idc_config_route_client):
    client, app = idc_config_route_client
    headers = {'Authorization': 'Bearer test-token'}
    payload = {
        'base_url': 'https://new-query.example.com',
        'token': 'replacement-token',
        'timeout_seconds': 10,
        'verify_tls': True,
        'requests_per_minute': 30,
        'bind_attempts_per_10_minutes': 4,
    }

    get_response = await client.get('/api/v1/system/idc-query', headers=headers)
    put_response = await client.put('/api/v1/system/idc-query', headers=headers, json=payload)

    assert get_response.status_code == 200
    assert (await get_response.get_json())['data']['token_configured'] is True
    assert put_response.status_code == 200
    response_data = (await put_response.get_json())['data']
    assert response_data['base_url'] == 'https://new-query.example.com'
    assert 'token' not in response_data
    app.idc_query_config_service.update_config.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_idc_connection_test_uses_user_login_and_returns_sanitized_result(idc_config_route_client):
    client, app = idc_config_route_client
    payload = {
        'base_url': 'https://pending.example.com',
        'token': 'replacement-token',
        'timeout_seconds': 10,
        'verify_tls': True,
    }

    response = await client.post(
        '/api/v1/system/idc-query/test',
        headers={'Authorization': 'Bearer test-token'},
        json=payload,
    )

    assert response.status_code == 200
    response_data = (await response.get_json())['data']
    assert response_data['status'] == 'reachable'
    assert 'token' not in response_data
    assert 'base_url' not in response_data
    app.idc_query_config_service.test_connection.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_idc_config_route_maps_validation_errors_to_bad_request(idc_config_route_client):
    client, app = idc_config_route_client
    app.idc_query_config_service.update_config.side_effect = IDCQueryConfigValidationError('invalid gateway')

    response = await client.put(
        '/api/v1/system/idc-query',
        headers={'Authorization': 'Bearer test-token'},
        json={'base_url': 'invalid'},
    )

    assert response.status_code == 400
    assert (await response.get_json())['msg'] == 'invalid gateway'


@pytest.mark.asyncio
async def test_idc_config_route_does_not_expose_filesystem_errors(idc_config_route_client):
    client, app = idc_config_route_client
    app.idc_query_config_service.update_config.side_effect = OSError('/private/path/config.env is read-only')

    response = await client.put(
        '/api/v1/system/idc-query',
        headers={'Authorization': 'Bearer test-token'},
        json={},
    )

    assert response.status_code == 500
    assert (await response.get_json())['msg'] == 'Failed to save IDC query configuration.'
    assert '/private/path' not in (await response.get_data(as_text=True))


@pytest.mark.asyncio
async def test_idc_audit_route_returns_recent_events(idc_config_route_client):
    client, app = idc_config_route_client

    response = await client.get(
        '/api/v1/system/idc-query/audit?limit=25',
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 200
    assert (await response.get_json())['data']['events'][0]['command'] == 'ip'
    app.idc_query_config_service.get_audit_events.assert_awaited_once_with(25)


@pytest.mark.asyncio
async def test_idc_audit_route_rejects_invalid_limit(idc_config_route_client):
    client, app = idc_config_route_client

    response = await client.get(
        '/api/v1/system/idc-query/audit?limit=invalid',
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 400
    app.idc_query_config_service.get_audit_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_idc_audit_route_does_not_expose_filesystem_errors(idc_config_route_client):
    client, app = idc_config_route_client
    app.idc_query_config_service.get_audit_events.side_effect = OSError('/private/path/audit.jsonl denied')

    response = await client.get(
        '/api/v1/system/idc-query/audit',
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 500
    assert (await response.get_json())['msg'] == 'Failed to read IDC query audit log.'
    assert '/private/path' not in (await response.get_data(as_text=True))


@pytest.mark.asyncio
async def test_idc_bindings_route_returns_active_bindings(idc_config_route_client):
    client, app = idc_config_route_client

    response = await client.get(
        '/api/v1/system/idc-query/bindings?limit=50',
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 200
    assert (await response.get_json())['data']['bindings'][0]['member_name'] == 'Customer One'
    app.idc_query_config_service.get_bindings.assert_awaited_once_with(50)


@pytest.mark.asyncio
async def test_idc_bindings_route_rejects_invalid_limit(idc_config_route_client):
    client, app = idc_config_route_client

    response = await client.get(
        '/api/v1/system/idc-query/bindings?limit=invalid',
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 400
    app.idc_query_config_service.get_bindings.assert_not_awaited()


@pytest.mark.asyncio
async def test_idc_bindings_route_does_not_expose_state_errors(idc_config_route_client):
    client, app = idc_config_route_client
    app.idc_query_config_service.get_bindings.side_effect = OSError('/private/path/bindings.json denied')

    response = await client.get(
        '/api/v1/system/idc-query/bindings',
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 500
    assert (await response.get_json())['msg'] == 'Failed to read IDC query bindings.'
    assert '/private/path' not in (await response.get_data(as_text=True))
