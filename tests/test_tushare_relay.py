import os
import unittest
from unittest.mock import patch

import requests

os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")

import main


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def __bool__(self):
        return self.status_code < 400


class FakePro:
    def __init__(self):
        self._DataApi__http_url = "http://relay.test"
        self._DataApi__token = "token"
        self._DataApi__timeout = 3

    def query(self, api_name, fields="", **kwargs):
        raise AssertionError("patched query should replace the original relay call")


class TushareRelayTest(unittest.TestCase):
    def test_relay_http_error_is_not_silently_converted_to_empty_dataframe(self):
        pro = main._patch_tushare_http_errors(FakePro())

        with patch("main.requests.post", return_value=FakeResponse(status_code=502)):
            with self.assertRaisesRegex(requests.HTTPError, "HTTP 502"):
                pro.query("trade_cal", fields="cal_date,is_open", start_date="20260624", end_date="20260630")

    def test_relay_success_response_is_converted_to_dataframe(self):
        pro = main._patch_tushare_http_errors(FakePro())
        response = FakeResponse(
            status_code=200,
            text='{"code":0,"msg":"","data":{"fields":["cal_date","is_open"],"items":[["20260625",1]]}}',
        )

        with patch("main.requests.post", return_value=response):
            df = pro.query("trade_cal", fields="cal_date,is_open", start_date="20260624", end_date="20260630")

        self.assertEqual(df.to_dict("records"), [{"cal_date": "20260625", "is_open": 1}])


if __name__ == "__main__":
    unittest.main()
