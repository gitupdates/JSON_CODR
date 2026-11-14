import unittest

from web_app.version import APP_VERSION


class VersionTests(unittest.TestCase):
    def test_canonical_application_version(self):
        self.assertEqual(APP_VERSION, "V1.0.4")


if __name__ == "__main__":
    unittest.main()
