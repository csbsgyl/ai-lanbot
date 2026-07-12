from __future__ import annotations

import logging
from typing import Any

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import context, events
import langbot_plugin.api.entities.builtin.platform.message as platform_message


logger = logging.getLogger(__name__)
_PROCESSING_ERROR = '查询处理异常，请稍后重试或联系管理员。'


def _identifier(value: Any) -> str:
    return str(value).strip() if value not in (None, '', {}) else ''


def _source_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, '')


def _plain_text(message_chain: Any) -> str:
    parts: list[str] = []
    for component in message_chain or []:
        if isinstance(component, platform_message.Plain):
            parts.append(component.text)
    return ''.join(parts).strip()


class IDCQueryEventListener(EventListener):
    async def initialize(self) -> None:
        await super().initialize()

        @self.handler(events.GroupMessageReceived)
        async def on_group_message(event_context: context.EventContext) -> None:
            event = event_context.event
            message_event = getattr(event, 'message_event', None)
            source = getattr(message_event, 'source_platform_object', None)
            source_type = _identifier(_source_value(source, 't'))

            if source_type != 'GROUP_AT_MESSAGE_CREATE':
                is_simulated = source is None and getattr(self.plugin, 'allow_simulated_events', False)
                if not is_simulated:
                    return

            text = _plain_text(getattr(event, 'message_chain', None))
            if not text:
                return

            group_id = _identifier(_source_value(source, 'group_openid')) or _identifier(event.launcher_id)
            raw_user_id = (
                _identifier(_source_value(source, 'member_openid'))
                or _identifier(_source_value(source, 'openid'))
                or _identifier(_source_value(source, 'd_author_id'))
            )
            user_id = raw_user_id or (_identifier(event.sender_id) if source is None else '')
            message_id = (
                _identifier(_source_value(source, 'd_id'))
                or _identifier(_source_value(source, 'id'))
                or _identifier(getattr(getattr(event, 'query', None), 'query_id', ''))
            )
            if not group_id or not user_id:
                if group_id and source_type == 'GROUP_AT_MESSAGE_CREATE':
                    logger.warning('Ignoring QQ group query event without a member identity')
                return

            try:
                result = await self.plugin.handle_idc_query(
                    text=text,
                    group_id=group_id,
                    user_id=user_id,
                    message_id=message_id,
                )
            except Exception:
                logger.exception('IDC query plugin failed to process a group message')
                result = None

            if result is None:
                event_context.prevent_default()
                event_context.prevent_postorder()
                await event_context.reply(
                    platform_message.MessageChain([platform_message.Plain(text=_PROCESSING_ERROR)])
                )
                return

            if not result.handled:
                return

            event_context.prevent_default()
            event_context.prevent_postorder()
            if result.reply:
                await event_context.reply(platform_message.MessageChain([platform_message.Plain(text=result.reply)]))
