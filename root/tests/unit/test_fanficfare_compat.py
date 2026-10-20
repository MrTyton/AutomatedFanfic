"""
FanFicFare API Compatibility Tests

These tests validate that the installed version of FanFicFare exposes the exact
API surfaces that AutomatedFanfic depends on. They run against the real library
with NO mocking, so any breaking upstream change causes an immediate, clear failure
before it can reach a Docker image.

When one of these tests fails after a FanFicFare update, the fix is either:
  1. Update AutomatedFanfic to use the new API (and update the assertion here), OR
  2. Pin FanFicFare to the last known-good version until the new API is understood.
"""

import unittest

import fanficfare.adapters as adapters
import fanficfare.configurable as configurable
import fanficfare.exceptions as exceptions
import fanficfare.geturls as geturls


class TestFanFicFareGeturlsAPI(unittest.TestCase):
    """Verify the fanficfare.geturls API contract."""

    def test_geturls_exposes_GetURLs_class(self):
        self.assertTrue(
            hasattr(geturls, "GetURLs"),
            "fanficfare.geturls must export a 'GetURLs' class",
        )
        self.assertTrue(
            isinstance(geturls.GetURLs, type),
            "geturls.GetURLs must be a class",
        )

    def test_GetURLs_is_instantiable_without_args(self):
        instance = geturls.GetURLs()
        self.assertIsNotNone(instance)

    def test_GetURLs_has_get_urls_from_imap(self):
        instance = geturls.GetURLs()
        self.assertTrue(
            hasattr(instance, "get_urls_from_imap"),
            "GetURLs instance must have a 'get_urls_from_imap' method",
        )
        self.assertTrue(
            callable(instance.get_urls_from_imap),
            "GetURLs.get_urls_from_imap must be callable",
        )

    def test_GetURLs_has_get_urls_from_html(self):
        instance = geturls.GetURLs()
        self.assertTrue(
            hasattr(instance, "get_urls_from_html"),
            "GetURLs instance must have a 'get_urls_from_html' method",
        )

    def test_GetURLs_has_get_urls_from_text(self):
        instance = geturls.GetURLs()
        self.assertTrue(
            hasattr(instance, "get_urls_from_text"),
            "GetURLs instance must have a 'get_urls_from_text' method",
        )


class TestFanFicFareAdaptersAPI(unittest.TestCase):
    """Verify the fanficfare.adapters API contract."""

    def test_adapters_has_getSiteExamples(self):
        self.assertTrue(
            hasattr(adapters, "getSiteExamples"),
            "fanficfare.adapters must export 'getSiteExamples'",
        )
        self.assertTrue(callable(adapters.getSiteExamples))

    def test_getSiteExamples_returns_non_empty(self):
        examples = adapters.getSiteExamples()
        self.assertIsNotNone(examples)
        self.assertGreater(
            len(examples), 0, "getSiteExamples() must return at least one site"
        )

    def test_adapters_has_getAdapter(self):
        self.assertTrue(
            hasattr(adapters, "getAdapter"),
            "fanficfare.adapters must export 'getAdapter'",
        )
        self.assertTrue(callable(adapters.getAdapter))


class TestFanFicFareConfigurableAPI(unittest.TestCase):
    """Verify the fanficfare.configurable API contract."""

    def test_configurable_has_Configuration_class(self):
        self.assertTrue(
            hasattr(configurable, "Configuration"),
            "fanficfare.configurable must export 'Configuration'",
        )
        self.assertTrue(isinstance(configurable.Configuration, type))

    def test_Configuration_instantiable_with_lightweight(self):
        """Configuration must accept the (sites, output_type, lightweight=True) signature."""
        config = configurable.Configuration(["test.com"], "EPUB", lightweight=True)
        self.assertIsNotNone(config)


class TestFanFicFareExceptionsAPI(unittest.TestCase):
    """Verify the fanficfare.exceptions API contract."""

    def test_exceptions_has_UnknownSite(self):
        self.assertTrue(
            hasattr(exceptions, "UnknownSite"),
            "fanficfare.exceptions must export 'UnknownSite'",
        )

    def test_UnknownSite_is_exception(self):
        self.assertTrue(
            issubclass(exceptions.UnknownSite, Exception),
            "exceptions.UnknownSite must be an Exception subclass",
        )

    def test_exceptions_has_FetchEmailFailed(self):
        self.assertTrue(
            hasattr(exceptions, "FetchEmailFailed"),
            "fanficfare.exceptions must export 'FetchEmailFailed'",
        )


class TestFanFicFareCliAndIntegrationAPI(unittest.TestCase):
    """Verify fanficfare.cli entry points and real GetURLs/Configuration integration."""

    def test_cli_exports_mkParser_expandOptions_do_download(self):
        import inspect
        import fanficfare.cli as fff_cli

        self.assertTrue(callable(getattr(fff_cli, "mkParser", None)))
        self.assertTrue(callable(getattr(fff_cli, "expandOptions", None)))
        self.assertTrue(callable(getattr(fff_cli, "do_download", None)))

        parser = fff_cli.mkParser(calibre=False)
        options, args = parser.parse_args(
            [
                "-u",
                "--update-cover",
                "--non-interactive",
                "https://archiveofourown.org/works/123",
            ]
        )
        fff_cli.expandOptions(options)
        self.assertEqual(args, ["https://archiveofourown.org/works/123"])

        target_fn = fff_cli.do_download
        closure = getattr(target_fn, "__closure__", None)
        if closure is not None:
            for cell in closure:
                if callable(cell.cell_contents):
                    target_fn = cell.cell_contents
                    break
        sig = inspect.signature(target_fn)
        for param in (
            "arg",
            "options",
            "passed_defaultsini",
            "passed_personalini",
            "warn",
            "fail",
        ):
            self.assertIn(
                param,
                sig.parameters,
                f"fanficfare.cli.do_download must accept '{param}' parameter",
            )

    def test_getAdapter_anyurl_false_rejects_series_and_accepts_single_story(self):
        config = configurable.Configuration(["test.com"], "EPUB", lightweight=True)
        adapter = adapters.getAdapter(
            config, "https://archiveofourown.org/works/12345", anyurl=False
        )
        self.assertEqual(adapter.story.getMetadata("storyId"), "12345")

        with self.assertRaises(Exception):
            adapters.getAdapter(
                config, "https://archiveofourown.org/series/12345", anyurl=False
            )

    def test_make_fff_get_configuration_with_real_GetURLs_html_extraction(self):
        """Real _make_fff_get_configuration + GetURLs extracts URLs from HTML without AttributeError."""
        from pathlib import Path
        from config.config_store import ConfigStore
        from services.url_ingester import _make_fff_get_configuration

        defaults_ini = (
            Path(__file__).resolve().parents[2] / "config.default" / "defaults.ini"
        )
        store = ConfigStore()
        store.update("calibre.default_ini", str(defaults_ini))
        get_config_fn = _make_fff_get_configuration(store)
        initial_config = get_config_fn("test1.com")
        gu = geturls.GetURLs(config=initial_config, get_config=get_config_fn)

        html = (
            "<html><body>"
            '<a href="https://archiveofourown.org/works/987654">AO3 Work</a>'
            '<a href="https://www.fanfiction.net/s/11223344/1/Test">FFNet Work</a>'
            "</body></html>"
        )
        urls = gu.get_urls_from_html(html)
        self.assertIn("https://archiveofourown.org/works/987654", urls)
        self.assertTrue(any("fanfiction.net/s/11223344" in u for u in urls))


class TestRequirementsAndDockerDependencies(unittest.TestCase):
    """Verify requirements.txt satisfies all runtime dependencies for Docker builds.

    Because the Dockerfile installs FanFicFare with `pip install --no-deps`,
    every runtime dependency declared by FanFicFare's package metadata MUST be
    present in requirements.txt, and all third-party imports in root/app must
    be covered by requirements.txt.
    """

    @staticmethod
    def _parse_requirements_txt() -> dict[str, str]:
        from pathlib import Path
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name

        req_path = Path(__file__).resolve().parents[3] / "requirements.txt"
        parsed: dict[str, str] = {}
        for raw_line in req_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            req = Requirement(line)
            parsed[canonicalize_name(req.name)] = line
        return parsed

    def test_requirements_txt_contains_all_fanficfare_runtime_dependencies(self):
        """Every Linux runtime requirement of FanFicFare must be in requirements.txt."""
        import importlib.metadata as m
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
        from packaging.version import Version

        reqs_txt = self._parse_requirements_txt()
        fff_requires = m.requires("FanFicFare") or []
        self.assertGreater(
            len(fff_requires),
            0,
            "FanFicFare package metadata must declare its dependencies",
        )

        missing: list[str] = []
        version_mismatches: list[str] = []

        for extra in ("", "image-processing"):
            env = {"extra": extra, "platform_system": "Linux"}
            for req_str in fff_requires:
                req = Requirement(req_str)
                if req.marker and not req.marker.evaluate(env):
                    continue
                pkg_name = canonicalize_name(req.name)
                if pkg_name not in reqs_txt:
                    if req_str not in missing:
                        missing.append(req_str)
                    continue
                pinned_req = Requirement(reqs_txt[pkg_name])
                for spec in pinned_req.specifier:
                    if spec.operator == "==":
                        pinned_ver = Version(spec.version)
                        if req.specifier and not req.specifier.contains(
                            pinned_ver, prereleases=True
                        ):
                            version_mismatches.append(
                                f"{pkg_name}: pinned {pinned_ver} does not satisfy FanFicFare requirement '{req_str}'"
                            )

        self.assertEqual(
            missing,
            [],
            f"FanFicFare is installed with --no-deps in Dockerfile, so all its "
            f"runtime dependencies must be in requirements.txt. Missing: {missing}",
        )
        self.assertEqual(
            version_mismatches,
            [],
            f"Pinned versions in requirements.txt do not satisfy FanFicFare requirements: {version_mismatches}",
        )

    def test_requirements_txt_covers_all_app_third_party_imports(self):
        """Every third-party module imported in root/app must be covered by requirements.txt."""
        import ast
        import importlib.metadata as m
        from pathlib import Path
        import sys
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name

        app_root = Path(__file__).resolve().parents[2] / "app"
        local_modules = {p.stem for p in app_root.glob("*.py")} | {
            p.name for p in app_root.iterdir() if p.is_dir()
        }

        imported_top: set[str] = set()
        for pyfile in app_root.rglob("*.py"):
            tree = ast.parse(pyfile.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_top.add(alias.name.split(".")[0])
                elif (
                    isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                ):
                    imported_top.add(node.module.split(".")[0])

        third_party_imports = (
            imported_top - sys.stdlib_module_names - local_modules - {"fanficfare"}
        )

        reqs_txt = self._parse_requirements_txt()
        closure = set(reqs_txt.keys())
        queue = list(closure)
        while queue:
            pkg = queue.pop()
            try:
                sub_reqs = m.requires(pkg) or []
            except m.PackageNotFoundError:
                continue
            for sr in sub_reqs:
                sreq = Requirement(sr)
                if sreq.marker and not sreq.marker.evaluate(
                    {"extra": "", "platform_system": "Linux"}
                ):
                    continue
                cname = canonicalize_name(sreq.name)
                if cname not in closure:
                    closure.add(cname)
                    queue.append(cname)

        pkg_dist_map = m.packages_distributions()
        uncovered: list[str] = []
        for imp_name in sorted(third_party_imports):
            dists = [
                canonicalize_name(d) for d in pkg_dist_map.get(imp_name, [imp_name])
            ]
            if not any(d in closure for d in dists):
                uncovered.append(f"{imp_name} (distributions: {dists})")

        self.assertEqual(
            uncovered,
            [],
            f"Third-party imports in root/app not covered by requirements.txt: {uncovered}",
        )

    def test_fanficdownload_entrypoint_runs_help_cleanly(self):
        """Running fanficdownload.py --help in a subprocess must succeed with exit code 0."""
        from pathlib import Path
        import subprocess
        import sys

        entrypoint = Path(__file__).resolve().parents[2] / "app" / "fanficdownload.py"
        result = subprocess.run(
            [sys.executable, str(entrypoint), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"fanficdownload.py --help failed with stderr:\n{result.stderr}",
        )

    def test_dockerfile_does_not_use_no_deps_and_verifies_entrypoint(self):
        """Dockerfile must resolve FanFicFare dependencies (no --no-deps) and verify entrypoint imports."""
        from pathlib import Path
        import re

        dockerfile = Path(__file__).resolve().parents[3] / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        non_comment_lines = [
            line for line in content.splitlines() if not line.strip().startswith("#")
        ]
        active_dockerfile = "\n".join(non_comment_lines)

        self.assertIsNone(
            re.search(r"pip\s+install[^\n]*--no-deps", active_dockerfile),
            "Dockerfile must not use 'pip install --no-deps', which skips transitive dependency resolution",
        )
        self.assertIn(
            "FROM python-deps AS fanficfare-installer",
            active_dockerfile,
            "fanficfare-installer stage must inherit from python-deps so pip sees pre-installed packages while still resolving any missing dependencies",
        )
        self.assertIn(
            "python /app/fanficdownload.py --help",
            active_dockerfile,
            "Dockerfile runtime stage must verify that /app/fanficdownload.py --help executes cleanly at build time",
        )

    def test_dockerfile_defines_slim_and_standalone_targets(self):
        """Dockerfile must define runtime-slim (without /opt/calibre or CALIBRE_RELEASE) and runtime-standalone."""
        from pathlib import Path

        dockerfile = Path(__file__).resolve().parents[3] / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")
        non_comment_lines = [
            line for line in content.splitlines() if not line.strip().startswith("#")
        ]
        active_dockerfile = "\n".join(non_comment_lines)

        self.assertIn("AS runtime-slim", active_dockerfile)
        self.assertIn("AS runtime-standalone", active_dockerfile)

        # Extract runtime-slim stage and ensure it does not copy /opt/calibre or depend on CALIBRE_RELEASE
        slim_start = active_dockerfile.index("AS runtime-slim")
        next_from = active_dockerfile.index("FROM ", slim_start)
        slim_stage = active_dockerfile[slim_start:next_from]

        self.assertNotIn("/opt/calibre", slim_stage)
        self.assertNotIn("CALIBRE_RELEASE", slim_stage)
        self.assertIn("COPY --chown=abc:abc --chmod=755 root/app/ /app/", slim_stage)
