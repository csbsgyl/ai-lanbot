import datetime
from typing import Any, Dict, Optional


def parse_qq_event_timestamp(value: Any) -> int:
    """Parse an RFC3339 QQ event timestamp into Unix seconds."""
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError('invalid QQ event timestamp')
    normalized = f'{value[:-1]}+00:00' if value.endswith('Z') else value
    parsed = datetime.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('QQ event timestamp must include a timezone')
    return int(parsed.timestamp())


class QQOfficialEvent(dict):
    @staticmethod
    def from_payload(payload: Dict[str, Any]) -> Optional['QQOfficialEvent']:
        if not isinstance(payload, dict):
            return None
        return QQOfficialEvent(payload)

    @property
    def t(self) -> str:
        """
        事件类型
        """
        return self.get('t', '')

    @property
    def user_openid(self) -> str:
        """
        用户openid
        """
        return self.get('user_openid', '')

    @property
    def timestamp(self) -> str:
        """
        时间戳
        """
        return self.get('timestamp', '')

    @property
    def d_author_id(self) -> str:
        """
        作者id
        """
        return self.get('d_author_id', '')

    @property
    def content(self) -> str:
        """
        内容
        """
        return self.get('content', '')

    @property
    def d_id(self) -> str:
        """
        d_id
        """
        return self.get('d_id', '')

    @property
    def id(self) -> str:
        """
        消息id，msg_id
        """
        return self.get('id', '')

    @property
    def channel_id(self) -> str:
        """
        频道id
        """
        return self.get('channel_id', '')

    @property
    def username(self) -> str:
        """
        用户名
        """
        return self.get('username', '')

    @property
    def guild_id(self) -> str:
        """
        频道id
        """
        return self.get('guild_id', '')

    @property
    def member_openid(self) -> str:
        """
        成员openid
        """
        return self.get('member_openid') or self.get('openid', '')

    @property
    def attachments(self) -> str:
        """
        附件url
        """
        url = self.get('image_attachments', '')
        if not isinstance(url, str):
            return ''
        if url and not url.startswith('https://'):
            url = 'https://' + url
        return url

    @property
    def group_openid(self) -> str:
        """
        群组id
        """
        return self.get('group_openid', '')

    @property
    def content_type(self) -> str:
        """
        文件类型
        """
        return self.get('content_type', '')
