from pathlib import Path
import unittest
from unittest.mock import MagicMock

from calibre_integration.calibre_info import CalibreInfo
from models.fanfic_info import FanficInfo
from utils import anubis_solver
from utils.system_utils import get_packaged_defaults_ini_path
from workers import fff_runner


class TestFffRunner(unittest.TestCase):
    def setUp(self):
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_cdb.update_method = "update"
        self.mock_cdb.default_ini = None
        self.mock_cdb.personal_ini = None

        self.mock_fanfic = MagicMock(spec=FanficInfo)
        self.mock_fanfic.behavior = None
        self.mock_fanfic.site = "archiveofourown"
        self.mock_fanfic.url = "https://archiveofourown.org/works/12345"

        parser = fff_runner.fff_cli.mkParser(calibre=False)
        self.options, _ = parser.parse_args(["-u"])
        fff_runner.fff_cli.expandOptions(self.options)

        defaults_path = get_packaged_defaults_ini_path()
        self.defaults_ini = (
            Path(defaults_path).read_text(encoding="utf-8")
            if defaults_path and Path(defaults_path).is_file()
            else None
        )

    def test_extract_output_filename_template_fallback(self):
        template = fff_runner.extract_output_filename_template("", "ao3")
        self.assertEqual(template, "${title}-${siteabbrev}_${storyId}.epub")

    def test_resolve_fanficfare_user_agent_empty_url(self):
        ua = fff_runner.resolve_fanficfare_user_agent(
            "", self.defaults_ini, "", self.options
        )
        self.assertEqual(ua, anubis_solver.DEFAULT_USER_AGENT)

    def test_resolve_fanficfare_user_agent_with_site_override(self):
        personal = (
            f"[defaults]\nuser_agent: {anubis_solver.DEFAULT_USER_AGENT}\n\n"
            "[www.royalroad.com]\nuser_agent: CustomRRUA/1.0\n"
        )
        ua = fff_runner.resolve_fanficfare_user_agent(
            "https://www.royalroad.com/fiction/129182",
            self.defaults_ini,
            personal,
            self.options,
        )
        self.assertEqual(ua, "CustomRRUA/1.0")

    def test_resolve_target_url(self):
        url = fff_runner.resolve_target_url(self.mock_fanfic, "/tmp/story.epub", "")
        self.assertEqual(url, "https://archiveofourown.org/works/12345")

    def test_build_argv_update_always(self):
        self.mock_cdb.update_method = "update_always"
        argv = fff_runner.build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("-U", argv)

    def test_build_argv_force(self):
        self.mock_cdb.update_method = "force"
        argv = fff_runner.build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("--force", argv)

    def test_get_fanficfare_version(self):
        version = fff_runner.get_fanficfare_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)


if __name__ == "__main__":
    unittest.main()
