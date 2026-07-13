from idc_query_core.formatting import format_gateway_response


def test_formatter_uses_labels_and_drops_secret_fields():
    result = format_gateway_response(
        'IP 查询结果',
        {
            'data': {
                'ip': '1.1.1.1',
                'line': 'BGP',
                'api_token': 'must-not-leak',
                'updated_at': '2026-07-11 12:00:00',
            }
        },
    )

    assert 'IP：1.1.1.1' in result
    assert '线路：BGP' in result
    assert '数据更新时间：2026-07-11 12:00:00' in result
    assert 'must-not-leak' not in result


def test_formatter_drops_secret_fields_inside_lists():
    result = format_gateway_response(
        '工单',
        {'data': [{'ticket_id': 'T-1', 'upstream_api_token': 'must-not-leak'}]},
    )

    assert '工单号=T-1' in result
    assert 'must-not-leak' not in result


def test_formatter_drops_secret_fields_from_structured_fields():
    result = format_gateway_response(
        '账户',
        {
            'data': {
                'fields': [
                    {'name': 'balance', 'label': '余额', 'value': '100.00'},
                    {'name': 'api_token', 'label': 'API Token', 'value': 'must-not-leak'},
                    {'label': '访问令牌', 'value': 'also-must-not-leak'},
                ]
            }
        },
    )

    assert '余额：100.00' in result
    assert 'must-not-leak' not in result
    assert 'also-must-not-leak' not in result


def test_formatter_does_not_render_non_string_preformatted_text_objects():
    result = format_gateway_response(
        '账户',
        {'data': {'text': {'api_token': 'must-not-leak'}, 'balance': '100.00'}},
    )

    assert '余额：100.00' in result
    assert 'must-not-leak' not in result


def test_formatter_checks_all_structured_field_identifiers_for_secrets():
    result = format_gateway_response(
        '账户',
        {
            'data': {
                'fields': [
                    {
                        'name': 'value',
                        'key': 'value',
                        'label': '访问令牌',
                        'value': 'must-not-leak',
                    },
                    {
                        'name': 'balance',
                        'label': '余额',
                        'value': '100.00',
                    },
                ]
            }
        },
    )

    assert '余额：100.00' in result
    assert 'must-not-leak' not in result


def test_formatter_detects_obfuscated_and_compatibility_secret_keys():
    result = format_gateway_response(
        '账户',
        {
            'data': {
                'to\u200bken': 'zero-width-secret',
                'ＰＡＳＳＷＯＲＤ': 'fullwidth-secret',
                'Authori-zation': 'authorization-secret',
                'balance': '100.00',
            }
        },
    )

    assert '余额：100.00' in result
    assert 'zero-width-secret' not in result
    assert 'fullwidth-secret' not in result
    assert 'authorization-secret' not in result


def test_formatter_removes_control_characters_and_bounds_labels_and_values():
    result = format_gateway_response(
        '工单',
        {
            'data': {
                'fields': [
                    {
                        'name': 'ticket_status',
                        'label': '状态\r\nInjected\u202eTXT' + 'L' * 100,
                        'value': '正常\x00\r\nInjected\u202eTXT' + 'V' * 600,
                    }
                ]
            }
        },
    )

    assert '\r' not in result
    assert '\x00' not in result
    assert '\u202e' not in result
    assert '状态 Injected' in result
    assert len(result) <= 1800


def test_formatter_bounds_nested_data_depth():
    nested = {'value': 'visible'}
    for index in range(20):
        nested = {f'level_{index}': nested}

    result = format_gateway_response('查询', {'data': nested})

    assert result == '查询\n查询成功，但没有可展示的数据。'


def test_formatter_reports_empty_objects_and_lists_as_no_data():
    assert format_gateway_response('查询', {'data': {}}) == '查询\n查询成功，但没有可展示的数据。'
    assert format_gateway_response('查询', {'data': []}) == '查询\n查询成功，但没有可展示的数据。'


def test_formatter_ignores_upstream_message_when_no_data_is_available():
    result = format_gateway_response(
        '查询',
        {'ok': True, 'data': None, 'message': 'private-db:5432 password=secret'},
    )

    assert result == '查询\n查询成功，但没有可展示的数据。'
    assert 'private-db' not in result


def test_formatter_does_not_render_success_envelope_metadata_as_business_data():
    result = format_gateway_response(
        '查询',
        {'ok': True, 'message': 'private internal status', 'trace_id': 'private-trace'},
    )

    assert result == '查询\n查询成功，但没有可展示的数据。'
    assert 'private' not in result


def test_formatter_enforces_line_limit_for_preformatted_text():
    result = format_gateway_response(
        '查询',
        {'data': {'text': '\n'.join(f'line-{index}' for index in range(100))}},
    )

    assert len(result.splitlines()) == 32
    assert 'line-30' in result
    assert 'line-31' not in result


def test_formatter_character_truncation_does_not_add_an_extra_line():
    result = format_gateway_response(
        '查询',
        {'data': {'text': '\n'.join('x' * 500 for _ in range(32))}},
    )

    assert len(result) <= 1800
    assert len(result.splitlines()) <= 32
    assert result.endswith('...结果已截断')
