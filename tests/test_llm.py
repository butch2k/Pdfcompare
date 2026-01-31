import unittest
import sys
import os
import urllib.error

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import llm

class TestLLM(unittest.TestCase):

    def test_detect_field(self):
        """Test domain detection logic."""
        legal_text = "The contract liability indemnification clause breach"
        self.assertEqual(llm._detect_field(legal_text), "contract law")
        
        tech_text = "The API endpoint database server bug"
        self.assertEqual(llm._detect_field(tech_text), "software engineering")
        
        generic_text = "This is just some random text about apples."
        self.assertEqual(llm._detect_field(generic_text), "document analysis")

    def test_validate_endpoint_valid(self):
        """Test valid endpoints."""
        try:
            llm._validate_endpoint("https://api.openai.com/v1/chat")
            llm._validate_endpoint("http://example.com/api")
        except ValueError:
            self.fail("Valid endpoints raised ValueError")

    def test_validate_endpoint_ssrf_blocked(self):
        """Test that SSRF attempts are blocked."""
        # Cloud metadata IPs
        with self.assertRaises(ValueError):
            llm._validate_endpoint("http://169.254.169.254/latest/meta-data/")
        
        with self.assertRaises(ValueError):
            llm._validate_endpoint("http://metadata.google.internal/computeMetadata/v1/")
            
        # Localhost/Private IPs (should be blocked by default)
        with self.assertRaises(ValueError):
            llm._validate_endpoint("http://localhost:5000")
            
        with self.assertRaises(ValueError):
            llm._validate_endpoint("http://127.0.0.1:8080")
            
        with self.assertRaises(ValueError):
            llm._validate_endpoint("http://192.168.1.1/admin")
            
    def test_validate_endpoint_allow_local(self):
        """Test that local endpoints are allowed when explicitly permitted (e.g. Ollama)."""
        try:
            llm._validate_endpoint("http://localhost:11434", allow_local=True)
            llm._validate_endpoint("http://127.0.0.1:1234", allow_local=True)
        except ValueError:
            self.fail("Local endpoints raised ValueError when allow_local=True")

    def test_validate_endpoint_schemes(self):
        """Test invalid schemes."""
        with self.assertRaises(ValueError):
            llm._validate_endpoint("ftp://example.com")
        with self.assertRaises(ValueError):
            llm._validate_endpoint("file:///etc/passwd")

    def test_extract_response_valid(self):
        """Test robust JSON response extraction."""
        data = {"choices": [{"message": {"content": "Hello"}}]}
        result = llm._extract_response(data, "choices", 0, "message", "content")
        self.assertEqual(result, "Hello")

    def test_extract_response_invalid(self):
        """Test handling of unexpected JSON structures."""
        data = {"error": "Something went wrong"}
        with self.assertRaises(ValueError):
            llm._extract_response(data, "choices", 0)

if __name__ == '__main__':
    unittest.main()
