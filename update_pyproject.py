#!/usr/bin/env python3
"""
Script to update pyproject.toml dependencies with latest versions from PyPI.
Preserves extras (e.g., package[extra1,extra2]).
Preserves entries without version pins (no operator/version).
"""

import re
import sys
import tomllib
import tomli_w
import requests
from typing import Optional, Tuple


def parse_dependency(dep: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse a dependency string from pyproject.toml.

    Returns: (package_name, extras, operator, version) or None if no version pin
    """
    pattern = r'^([a-zA-Z0-9_-]+)(\[[^\]]+\])?(==|>=|<=|>|<|!=|~=)(.+)$'
    match = re.match(pattern, dep.strip())
    if match:
        return (match.group(1), match.group(2) or '', match.group(3), match.group(4))
    return None


def get_latest_version(package_name: str) -> Optional[str]:
    """
    Fetch the latest version of a package from PyPI.

    Returns: Latest version string or None if not found
    """
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data['info']['version']
    except Exception as e:
        print(f"# Error fetching {package_name}: {e}", file=sys.stderr)
        return None


def main():
    pyproject_path = 'pyproject.toml'

    try:
        with open(pyproject_path, 'rb') as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        print(f"Error: {pyproject_path} not found in current directory", file=sys.stderr)
        sys.exit(1)

    dependencies = data.get('project', {}).get('dependencies', [])
    if not dependencies:
        print("No dependencies found under [project.dependencies]", file=sys.stderr)
        sys.exit(1)

    updated_dependencies = []

    for dep in dependencies:
        parsed = parse_dependency(dep)

        if parsed:
            package, extras, operator, current_version = parsed
            latest_version = get_latest_version(package)

            if latest_version:
                updated_dep = f"{package}{extras}=={latest_version}"
                updated_dependencies.append(updated_dep)
                if latest_version != current_version:
                    print(f"# {package}: {current_version} -> {latest_version}")
                else:
                    print(f"# {package}: already at latest ({latest_version})")
            else:
                updated_dependencies.append(dep)
        else:
            # No version pin — keep as-is
            updated_dependencies.append(dep)
            package_name = re.match(r'^([a-zA-Z0-9_-]+)', dep)
            if package_name:
                print(f"# {package_name.group(1)}: no version pin, skipping")

    data['project']['dependencies'] = updated_dependencies

    with open(pyproject_path, 'wb') as f:
        tomli_w.dump(data, f)

    print("\n✓ pyproject.toml updated successfully")


if __name__ == "__main__":
    main()
