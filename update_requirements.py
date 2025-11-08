#!/usr/bin/env python3
"""
Script to update requirements.txt with latest versions from PyPI.
Preserves extras (e.g., package[extra1,extra2]).
Outputs updated requirements to stdout.
"""

import re
import sys
import requests
from typing import Optional, Tuple


def parse_requirement(line: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse a requirement line.

    Returns: (package_name, extras, operator, version) or None if not a valid requirement
    """
    line = line.strip()

    # Skip empty lines and comments
    if not line or line.startswith('#'):
        return None

    # Pattern to match: package[extras]==version or package==version
    pattern = r'^([a-zA-Z0-9_-]+)(\[[^\]]+\])?(==|>=|<=|>|<|!=|~=)(.+)$'
    match = re.match(pattern, line)

    if match:
        package = match.group(1)
        extras = match.group(2) or ''
        operator = match.group(3)
        version = match.group(4)
        return (package, extras, operator, version)

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
    """Main function to process requirements.txt"""
    try:
        with open('requirements.txt', 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("Error: requirements.txt not found in current directory", file=sys.stderr)
        sys.exit(1)

    updated_lines = []

    for line in lines:
        line = line.rstrip('\n')

        # Preserve empty lines and comments
        if not line.strip() or line.strip().startswith('#'):
            updated_lines.append(line)
            continue

        # Parse the requirement
        parsed = parse_requirement(line)

        if parsed:
            package, extras, operator, current_version = parsed

            # Fetch latest version
            latest_version = get_latest_version(package)

            if latest_version:
                # Create updated requirement line
                updated_line = f"{package}{extras}=={latest_version}"
                updated_lines.append(updated_line)

                # Log the change to stdout (console)
                if latest_version != current_version:
                    print(f"# {package}: {current_version} -> {latest_version}")
                else:
                    print(f"# {package}: already at latest ({latest_version})")
            else:
                # Keep original if we couldn't fetch latest
                updated_lines.append(line)
        else:
            # Keep unparseable lines as-is
            updated_lines.append(line)

    # Write updated requirements back to file
    with open('requirements.txt', 'w') as f:
        for line in updated_lines:
            f.write(line + '\n')

    print("\n✓ requirements.txt updated successfully")


if __name__ == "__main__":
    main()