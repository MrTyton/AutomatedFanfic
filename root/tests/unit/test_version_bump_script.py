import importlib.util
from pathlib import Path


def load_bump_version_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version_script", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
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
