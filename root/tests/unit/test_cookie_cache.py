import unittest

from workers.cookie_cache import (
    clear_site_cookiejars,
    get_site_cookiejar,
    set_site_cookiejar,
)


class TestCookieCache(unittest.TestCase):
    def setUp(self):
        clear_site_cookiejars()

    def test_set_and_get_cookiejar_same_personal_ini(self):
        jar = object()
        set_site_cookiejar("ao3", jar)
        self.assertIs(get_site_cookiejar("ao3", "ini_v1"), jar)

    def test_invalidates_when_personal_ini_changes(self):
        jar = object()
        set_site_cookiejar("ao3", jar)
        self.assertIs(get_site_cookiejar("ao3", "ini_v1"), jar)
        self.assertIsNone(get_site_cookiejar("ao3", "ini_v2"))

    def test_get_cookiejar_without_personal_ini_does_not_invalidate(self):
        jar = object()
        set_site_cookiejar("ao3", jar)
        # Seed personal.ini tracking with ini_v1
        self.assertIs(get_site_cookiejar("ao3", "ini_v1"), jar)
        # Calling without personal_ini_content preserves jar and tracking
        self.assertIs(get_site_cookiejar("ao3"), jar)
        # Subsequent call with same ini_v1 is still valid
        self.assertIs(get_site_cookiejar("ao3", "ini_v1"), jar)

    def test_clear_all_cookiejars(self):
        jar = object()
        set_site_cookiejar("ao3", jar)
        clear_site_cookiejars()
        self.assertIsNone(get_site_cookiejar("ao3", "ini_v1"))

    def test_empty_site_returns_none(self):
        self.assertIsNone(get_site_cookiejar("", "ini_v1"))
        set_site_cookiejar("", object())


if __name__ == "__main__":
    unittest.main()
