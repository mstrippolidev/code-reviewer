from priority_out_of_scope_low_source import parse_config_value


def test_parse_config_value_with_content():
    result = parse_config_value("42")
    assert result is not None


def test_parse_config_value_with_empty_string():
    try:
        parse_config_value("")
    except ValueError:
        pass
