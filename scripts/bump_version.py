#!/usr/bin/env python3
"""Local version bump script for AutomatedFanfic.

This script mimics the functionality of the GitHub Action bump-version,
allowing you to bump the project version locally.

Usage:
    python bump_version.py [patch|minor|major] [reason]

Examples:
    python bump_version.py                    # Default: patch bump
    python bump_version.py patch dependency   # Patch bump for dependency update
    python bump_version.py minor feature      # Minor bump for new feature
    python bump_version.py major breaking     # Major bump for breaking changes
"""

import argparse
import re
import sys
from pathlib import Path


def read_current_version(version_file: Path) -> str:
    """Read current version from the latest.txt file."""
    try:
        with open(version_file, "r", encoding="utf-8") as f:
            version = f.read().strip()
        print(f"📖 Current version: {version}")
        return version
    except FileNotFoundError:
        print(f"❌ Version file {version_file} not found. Using default 1.0.0")
        return "1.0.0"


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse semantic version string into components."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version)
    if not match:
        raise ValueError(
            f"Invalid version format: {version}. Expected MAJOR.MINOR.PATCH"
        )

    major, minor, patch = map(int, match.groups())
    print(f"🔍 Parsed version components: {major}.{minor}.{patch}")
    return major, minor, patch


def calculate_new_version(major: int, minor: int, patch: int, bump_type: str) -> str:
    """Calculate new version based on bump type."""
    if bump_type == "major":
        new_version = f"{major + 1}.0.0"
    elif bump_type == "minor":
        new_version = f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        new_version = f"{major}.{minor}.{patch + 1}"
    else:
        raise ValueError(
            f"Invalid bump type: {bump_type}. Expected patch, minor, or major"
        )

    return new_version


def update_version_file(version_file: Path, new_version: str) -> None:
    """Update the version in release-versions/latest.txt."""
    print(f"📝 Updating {version_file}...")
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(f"{new_version}\n")
    print(f"✅ Updated {version_file}")


def update_python_version(python_file: Path, new_version: str) -> None:
    """Update the __version__ in fanficdownload.py."""
    print(f"📝 Updating {python_file}...")

    # Read current content
    with open(python_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if __version__ line exists
    if not re.search(r"^__version__ = ", content, re.MULTILINE):
        raise ValueError(f"No __version__ line found in {python_file}")

    # Update the version
    new_content = re.sub(
        r'^__version__ = ".*"',
        f'__version__ = "{new_version}"',
        content,
        flags=re.MULTILINE,
    )

    # Write back
    with open(python_file, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Verify the replacement
    with open(python_file, "r", encoding="utf-8") as f:
        verify_content = f.read()

    if f'__version__ = "{new_version}"' not in verify_content:
        raise ValueError(f"Failed to update version in {python_file}")

    print(f"✅ Updated {python_file}")

    # Show the updated line for verification
    for line_num, line in enumerate(verify_content.splitlines(), 1):
        if line.startswith("__version__ = "):
            print(f"🔍 Verification: Line {line_num}: {line}")
            break


def main():
    """Main function for local version bumping."""
    parser = argparse.ArgumentParser(
        description="Bump AutomatedFanfic version locally",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Patch bump (default)
  %(prog)s patch dependency   # Patch bump for dependency update
  %(prog)s minor feature      # Minor bump for new feature
  %(prog)s major breaking     # Major bump for breaking changes
        """,
    )

    parser.add_argument(
        "bump_type",
        nargs="?",
        choices=["patch", "minor", "major"],
        default="patch",
        help="Type of version bump (default: patch)",
    )

    parser.add_argument(
        "reason",
        nargs="?",
        default="manual",
        help="Reason for version bump (default: manual)",
    )

    args = parser.parse_args()

    # Define file paths
    script_dir = Path(__file__).parent.parent
    version_file = script_dir / "release-versions" / "latest.txt"
    python_file = script_dir / "root" / "app" / "fanficdownload.py"

    # Verify files exist
    if not version_file.exists():
        print(f"❌ Version file not found: {version_file}")
        sys.exit(1)

    if not python_file.exists():
        print(f"❌ Python file not found: {python_file}")
        sys.exit(1)

    try:
        print(f"🚀 Starting version bump: {args.bump_type} ({args.reason})")
        print()

        # Read and parse current version
        current_version = read_current_version(version_file)
        major, minor, patch = parse_version(current_version)

        # Calculate new version
        new_version = calculate_new_version(major, minor, patch, args.bump_type)

        print()
        print(f"📈 Version bump: {current_version} → {new_version}")
        print(f"🔧 Bump type: {args.bump_type}")
        print(f"📋 Reason: {args.reason}")
        print()

        # Confirm the change
        if current_version == new_version:
            print("ℹ️ No version change needed.")
            return

        response = input("❓ Proceed with version bump? (y/N): ").strip().lower()
        if response not in ["y", "yes"]:
            print("❌ Version bump cancelled.")
            return

        print()

        # Update files
        update_version_file(version_file, new_version)
        update_python_version(python_file, new_version)

        print()
        print("🎉 Version bump complete!")
        print(f"📊 Summary: {current_version} → {new_version} ({args.bump_type} bump)")
        print()
        print("💡 Next steps:")
        print("   1. Review the changes")
        print("   2. Test the application")
        print("   3. Commit and push the changes")
        print("   4. Create a release tag if desired")

    except Exception as e:
        print(f"❌ Error during version bump: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
