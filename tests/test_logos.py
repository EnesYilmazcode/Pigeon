import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch_logos  # noqa: E402


class DomainTest(unittest.TestCase):
    def test_domain_field_wins(self):
        row = {"domain": "Globex.com", "email": "jonah@mail.globex.com"}
        self.assertEqual(fetch_logos.domain_of(row), "globex.com")

    def test_company_email(self):
        self.assertEqual(fetch_logos.domain_of({"email": "maya@northwind.io"}), "northwind.io")

    def test_personal_email_is_not_a_company(self):
        self.assertEqual(fetch_logos.domain_of({"email": "someone@gmail.com"}), "")
        self.assertEqual(fetch_logos.domain_of({"email": ""}), "")

    def test_slug(self):
        self.assertEqual(fetch_logos.slug("Acme Robotics, Inc."), "acme-robotics--inc")


if __name__ == "__main__":
    unittest.main()
