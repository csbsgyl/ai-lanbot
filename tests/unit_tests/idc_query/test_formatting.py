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
