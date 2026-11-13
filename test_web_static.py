import unittest
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from web_app.app import create_app


class FakeService:
    async def health(self):
        return {"ollama": True}

    async def list_models(self):
        return []


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])


class WebStaticTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(FakeService()))

    def test_root_serves_the_complete_chat_interface(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        parser = IdCollector()
        parser.feed(response.text)
        self.assertTrue(
            {
                "health-status",
                "model-select",
                "prompt-input",
                "submit-button",
                "cancel-button",
                "summary-output",
                "content-output",
                "error-output",
            }.issubset(parser.ids)
        )

    def test_static_assets_are_served_with_correct_types(self):
        css = self.client.get("/static/app.css")
        javascript = self.client.get("/static/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertIn("text/css", css.headers["content-type"])
        self.assertEqual(javascript.status_code, 200)
        self.assertIn("javascript", javascript.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
