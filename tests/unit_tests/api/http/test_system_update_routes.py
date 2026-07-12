from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
import quart

from langbot.pkg.api.http.controller.groups.system import SystemRouterGroup
from langbot.pkg.api.http.service.system_update import UpdateDisabledError
from tests.factories import FakeApp


@pytest.fixture
async def update_route_client():
    app = FakeApp()
    app.user_service = Mock()
    app.user_service.verify_jwt_token = AsyncMock(return_value='admin@example.com')
    app.user_service.get_user_by_email = AsyncMock(return_value=Mock())
    app.system_update_service = Mock()
    app.system_update_service.get_status = AsyncMock(
        return_value={
            'enabled': True,
            'current_revision': '1' * 40,
            'latest_revision': '2' * 40,
            'update_available': True,
            'can_update': True,
            'state': 'idle',
        }
    )
    app.system_update_service.request_update = AsyncMock(
        return_value={
            'enabled': True,
            'state': 'queued',
            'target_revision': '2' * 40,
        }
    )

    quart_app = quart.Quart(__name__)
    router = SystemRouterGroup(app, quart_app)
    await router.initialize()
    return quart_app.test_client(), app


@pytest.mark.asyncio
async def test_update_routes_require_user_authentication(update_route_client):
    client, _ = update_route_client

    get_response = await client.get('/api/v1/system/update')
    post_response = await client.post('/api/v1/system/update')

    assert get_response.status_code == 401
    assert post_response.status_code == 401


@pytest.mark.asyncio
async def test_update_routes_reject_api_key_authentication(update_route_client):
    client, app = update_route_client

    response = await client.post(
        '/api/v1/system/update',
        headers={'X-API-Key': 'automation-key'},
    )

    assert response.status_code == 401
    app.system_update_service.request_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_routes_return_status_and_queue_request(update_route_client):
    client, app = update_route_client
    headers = {'Authorization': 'Bearer test-token'}

    status_response = await client.get('/api/v1/system/update?refresh=true', headers=headers)
    request_response = await client.post('/api/v1/system/update', headers=headers)

    assert status_response.status_code == 200
    assert (await status_response.get_json())['data']['update_available'] is True
    assert request_response.status_code == 200
    assert (await request_response.get_json())['data']['state'] == 'queued'
    app.system_update_service.get_status.assert_awaited_once_with(force_refresh=True)
    app.system_update_service.request_update.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_update_route_maps_disabled_host_to_conflict(update_route_client):
    client, app = update_route_client
    app.system_update_service.request_update.side_effect = UpdateDisabledError('disabled')

    response = await client.post(
        '/api/v1/system/update',
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 409
