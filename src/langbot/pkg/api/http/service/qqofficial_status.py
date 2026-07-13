from __future__ import annotations

import datetime
from typing import Any


class QQOfficialStatusService:
    def __init__(self, ap: Any) -> None:
        self.ap = ap

    async def get_status(self) -> dict[str, Any]:
        """Return secret-free QQ Official callback readiness and runtime metrics."""
        callback_path = '/qq/callback'
        webhook_prefix = str(self.ap.instance_config.data.get('api', {}).get('webhook_prefix', '')).rstrip('/')
        qq_bots: list[dict[str, Any]] = []

        for runtime_bot in getattr(self.ap.platform_mgr, 'bots', []):
            bot_entity = getattr(runtime_bot, 'bot_entity', None)
            if getattr(bot_entity, 'adapter', '') != 'qqofficial':
                continue

            adapter = getattr(runtime_bot, 'adapter', None)
            client = getattr(adapter, 'bot', None)
            webhook_mode = bool(getattr(adapter, 'enable_webhook', False))
            status_reader = getattr(client, 'get_webhook_status', None)
            metrics = status_reader() if webhook_mode and callable(status_reader) else None
            qq_bots.append(
                {
                    'uuid': str(getattr(bot_entity, 'uuid', '')),
                    'name': str(getattr(bot_entity, 'name', '')),
                    'app_id': str(getattr(client, 'app_id', '')),
                    'enabled': bool(getattr(runtime_bot, 'enable', False)),
                    'mode': 'webhook' if webhook_mode else 'websocket',
                    'metrics': metrics,
                }
            )

        active_webhook_bots = [bot for bot in qq_bots if bot['enabled'] and bot['mode'] == 'webhook']
        active_app_ids = [bot['app_id'] for bot in active_webhook_bots]
        if not qq_bots:
            status = 'not_configured'
        elif not active_webhook_bots:
            status = 'websocket_mode' if any(bot['enabled'] for bot in qq_bots) else 'disabled'
        elif any(not app_id for app_id in active_app_ids) or len(set(active_app_ids)) != len(active_app_ids):
            status = 'conflict'
        else:
            status = 'ready'

        return {
            'status': status,
            'callback_path': callback_path,
            'configured_callback_url': f'{webhook_prefix}{callback_path}' if webhook_prefix else '',
            'configured_bots': len(qq_bots),
            'active_webhook_bots': len(active_webhook_bots),
            'bots': sorted(qq_bots, key=lambda bot: (bot['name'].lower(), bot['uuid'])),
            'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
