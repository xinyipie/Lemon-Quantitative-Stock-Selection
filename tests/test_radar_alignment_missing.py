from web_app.services.sector_service import _market_data_alignment


def test_missing_industry_date_does_not_claim_alignment():
    result = _market_data_alignment({}, {'news': {'source_date': '20260904'}, 'concepts': {'source_date': '20260904'}})
    assert not result['aligned']
    assert '缺少' in result['message']


def test_all_dates_missing_does_not_claim_alignment():
    assert not _market_data_alignment({}, {})['aligned']
