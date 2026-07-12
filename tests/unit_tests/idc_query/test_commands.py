from idc_query_core.commands import CommandType, parse_command


def test_parse_binding_command():
    result = parse_command('绑定 10086 938421')

    assert result.error is None
    assert result.command.kind == CommandType.BIND
    assert result.command.arguments == {'member_id': '10086', 'verification_code': '938421'}


def test_parse_ip_command_normalizes_ipv6():
    result = parse_command('查IP 2001:0db8:0:0:0:0:0:1')

    assert result.error is None
    assert result.command.kind == CommandType.IP
    assert result.command.arguments['ip'] == '2001:db8::1'


def test_parse_invalid_ip_returns_usage_error():
    result = parse_command('查防护 not-an-ip')

    assert result.command is None
    assert result.error == 'IP 地址格式不正确，请检查后重试。'


def test_unknown_text_is_not_a_command():
    result = parse_command('今天天气怎么样')

    assert result.command is None
    assert result.error is None


def test_binding_rejects_unsafe_member_identifier():
    result = parse_command('绑定 ../customer 938421')

    assert result.command is None
    assert result.error == '格式错误，请发送：绑定 <会员号> <验证码>'


def test_parse_command_ignores_qq_bot_mention_markup():
    result = parse_command('<@!123456789>  查IP 1.1.1.1')

    assert result.error is None
    assert result.command.kind == CommandType.IP
    assert result.command.arguments['ip'] == '1.1.1.1'
