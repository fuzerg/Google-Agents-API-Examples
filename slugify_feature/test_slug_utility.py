import unittest
from slug_utility import slugify

class TestSlugify(unittest.TestCase):
    def test_basic_slugify(self):
        self.assertEqual(slugify("Hello World"), "hello-world")
        
    def test_mixed_case(self):
        self.assertEqual(slugify("lOwEr AnD uPpEr CaSe"), "lower-and-upper-case")
        
    def test_punctuation_and_spaces(self):
        self.assertEqual(slugify("Hello, World!!! This is a test..."), "hello-world-this-is-a-test")
        
    def test_leading_trailing_hyphens_trimmed(self):
        self.assertEqual(slugify("---hello world---"), "hello-world")
        self.assertEqual(slugify("  hello world  "), "hello-world")
        
    def test_unicode_normalization(self):
        self.assertEqual(slugify("Café Frédéric"), "cafe-frederic")
        self.assertEqual(slugify("München"), "munchen")
        
    def test_numeric_and_hyphens(self):
        self.assertEqual(slugify("Route-66!"), "route-66")
        self.assertEqual(slugify("100% pure"), "100-pure")

    def test_empty_and_invalid_inputs(self):
        self.assertEqual(slugify(""), "")
        self.assertEqual(slugify("   "), "")
        self.assertEqual(slugify("---"), "")
        self.assertEqual(slugify(None), "")
        self.assertEqual(slugify(12345), "")

if __name__ == "__main__":
    unittest.main()
