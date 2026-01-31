import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add project root to sys.path so we can import app and llm
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app
import llm

class TestApp(unittest.TestCase):

    def setUp(self):
        self.app = app.app.test_client()
        self.app.testing = True

    def test_index(self):
        """Test that the index page loads."""
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'PDFCompare', response.data)

    def test_config_api(self):
        """Test the config API endpoint."""
        response = self.app.get('/api/config')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('version', data)
        self.assertIn('has_api_key', data)

    def test_sanitize_metadata(self):
        """Test metadata sanitization for XSS prevention."""
        dangerous = "<script>alert(1)</script>Hello"
        safe = app._sanitize_metadata_value(dangerous)
        # The code strips brackets, not the whole tag content
        self.assertEqual(safe, "scriptalert(1)/scriptHello")
        
        null_byte = "Value\x00WithNull"
        safe_null = app._sanitize_metadata_value(null_byte)
        self.assertEqual(safe_null, "ValueWithNull")

    def test_page_index_build(self):
        """Test the O(1) page index builder."""
        # Simulate 3 pages
        lines = [
            f"{app.PAGE_MARKER_PREFIX}1", "Line 1", "Line 2",
            f"{app.PAGE_MARKER_PREFIX}2", "Line 3",
            f"{app.PAGE_MARKER_PREFIX}3", "Line 4"
        ]
        index = app._build_page_index(lines)
        # Expected: 
        # index[0] -> P1 (Marker)
        # index[1] -> P1 (Line 1)
        # index[2] -> P1 (Line 2)
        # index[3] -> P2 (Marker)
        # index[4] -> P2 (Line 3)
        # index[5] -> P3 (Marker)
        # index[6] -> P3 (Line 4)
        expected = [1, 1, 1, 2, 2, 3, 3]
        self.assertEqual(index, expected)

    def test_compute_diff_basic(self):
        """Test basic diff functionality."""
        lines_a = ["A", "B", "C"]
        lines_b = ["A", "X", "C"]
        
        # We need to insert page markers for the function to work correctly
        # because it calls _build_page_index internally
        lines_a_full = [f"{app.PAGE_MARKER_PREFIX}1"] + lines_a
        lines_b_full = [f"{app.PAGE_MARKER_PREFIX}1"] + lines_b

        blocks, stats = app.compute_diff(lines_a_full, lines_b_full)
        
        self.assertEqual(stats["equal"], 2)  # A and C
        self.assertEqual(stats["replace"], 1) # B -> X
        
        # Verify block structure
        self.assertTrue(any(b['tag'] == 'replace' for b in blocks))
        
    def test_ignore_rules_whitespace(self):
        """Test whitespace ignoring rule."""
        lines = ["  Hello   World  ", f"{app.PAGE_MARKER_PREFIX}1"]
        options = {"ignore_whitespace": True}
        result = app.apply_ignore_rules(lines, options)
        
        self.assertEqual(result[0], "Hello World")
        self.assertEqual(result[1], f"{app.PAGE_MARKER_PREFIX}1") # Sentinel untouched

    def test_ignore_rules_case(self):
        """Test case ignoring rule."""
        lines = ["HeLLo"]
        options = {"ignore_case": True}
        result = app.apply_ignore_rules(lines, options)
        self.assertEqual(result[0], "hello")

    def test_ignore_rules_regex_timeout(self):
        """Test that catastrophic regexes don't hang the server (ReDoS protection)."""
        # A classic evil regex that causes exponential backtracking
        # (a+)+$ matches aaaa... but fails on aaaa...b
        evil_pattern = r"(a+)+$"
        # Long string of 'a's followed by 'b' - 30 'a's should be enough for > 2s
        target = "a" * 30 + "b"
        
        options = {"ignore_pattern": evil_pattern}
        
        import time
        start = time.time()
        # Should timeout internally after 2 seconds and return the line as is
        result = app.apply_ignore_rules([target], options)
        duration = time.time() - start
        
        # It should take at least 2 seconds (the timeout)
        self.assertGreaterEqual(duration, 2.0) 
        self.assertEqual(result[0], target)


if __name__ == '__main__':
    unittest.main()
