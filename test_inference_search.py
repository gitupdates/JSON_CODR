import unittest


class OptimizedModelSearchTests(unittest.TestCase):
    def test_search_is_bounded_filtered_and_provider_qualified(self):
        from web_app.inference.search import OptimizedModelSearch

        payload = [
            {"id":"OpenVINO/qwen-coder-ov", "sha":"abc", "tags":["openvino", "license:apache-2.0"]},
            {"id":"bad/unsafe", "sha":"def", "tags":["openvino", "license:unknown"]},
        ]
        search = OptimizedModelSearch(fetcher=lambda url: payload)
        result = search.search("openvino", "qwen", limit=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["provider"], "openvino")
        self.assertEqual(result[0]["revision"], "abc")

    def test_network_failure_returns_pinned_catalog_without_raising(self):
        from web_app.inference.search import OptimizedModelSearch

        def fail(url): raise OSError("offline")
        result = OptimizedModelSearch(fetcher=fail).search("openvino", "qwen")
        self.assertTrue(result)
        self.assertTrue(all(item["source"] == "pinned" for item in result))


if __name__ == "__main__": unittest.main()
