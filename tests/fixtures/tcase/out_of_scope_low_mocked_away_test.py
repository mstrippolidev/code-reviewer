from unittest.mock import patch

from out_of_scope_low_mocked_away_source import total_with_tax


def test_total_with_tax_calls_calculate_tax():
    with patch("out_of_scope_low_mocked_away_source.calculate_tax", return_value=1.0) as mock_tax:
        total_with_tax(10.0)

        mock_tax.assert_called_once_with(10.0)
