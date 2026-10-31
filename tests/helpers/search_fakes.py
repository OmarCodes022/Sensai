"""A scripted search page and HTTP response for web search tests."""
import requests

DUCK = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Ftrends">Skin <b>trends</b></a>'
        '<a class="result__snippet">Barrier care is in.</a>'
        '<a class="result__a" href="javascript:void(0)">bad</a>')


class Response:
    def __init__(self, text="", payload=None, status=200):
        self.text, self.payload, self.status_code = text, payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))
