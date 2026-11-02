import importlib.util
from pathlib import Path


def load_bump_version_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version_script", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_pyproject_version_updates_project_version(tmp_path):
    module = load_bump_version_module()
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        '[project]\nname = "automatedfanfic"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )

    module.update_pyproject_version(pyproject_path, "2.0.0")

    content = pyproject_path.read_text(encoding="utf-8")
    assert 'version = "2.0.0"' in content


def test_update_python_version_updates_version_py(tmp_path):
    module = load_bump_version_module()
    version_file = tmp_path / "version.py"
    version_file.write_text(
        '"""Application version definition for AutomatedFanfic."""\n\n__version__ = "1.2.3"\n',
        encoding="utf-8",
    )

    module.update_python_version(version_file, "2.0.0")

    content = version_file.read_text(encoding="utf-8")
    assert '__version__ = "2.0.0"' in content


def test_workflow_and_action_version_files_reference_version_py():
    repo_root = Path(__file__).resolve().parents[3]
    bump_action = repo_root / ".github" / "actions" / "bump-version" / "action.yml"
    process_dependabot = (
        repo_root / ".github" / "workflows" / "process-dependabot-pr.yml"
    )
    update_deps = repo_root / ".github" / "workflows" / "update-dependencies.yml"

    for path in (bump_action, process_dependabot, update_deps):
        text = path.read_text(encoding="utf-8")
        assert (
            "fanficdownload.py" not in text
        ), f"{path.name} still references fanficdownload.py for version bumping"
