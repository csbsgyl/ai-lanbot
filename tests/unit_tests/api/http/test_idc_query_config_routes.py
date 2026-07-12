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
        }
    )
    app.idc_query_config_service.update_config = AsyncMock(
        return_value={
            'base_url': 'https://new-query.example.com',
            'timeout_seconds': 10,
            'verify_tls': True,
            'token_configured': True,
            'configured': True,
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

    assert get_response.status_code == 401
    assert put_response.status_code == 401


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


@pytest.mark.asyncio
async def test_idc_config_routes_read_and_update_settings(idc_config_route_client):
    client, app = idc_config_route_client
    headers = {'Authorization': 'Bearer test-token'}
    payload = {
        'base_url': 'https://new-query.example.com',
        'token': 'replacement-token',
        'timeout_seconds': 10,
        'verify_tls': True,
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
