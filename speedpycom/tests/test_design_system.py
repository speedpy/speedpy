"""Design-system classes used in templates must exist in the compiled CSS.

Tailwind compiles only the classes it can actually see. A class declared in
`input.css` but referenced nowhere is absent from `styles.css`, and using it then
does *nothing* — no error, no warning, just an element with no styling. That
failure has shipped twice: a warning box with a transparent background, and a
submit button that rendered as plain text.

Neither was caught by any test, because every test asserted behaviour and the
behaviour was fine. This asserts the styling exists at all.
"""

import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

BASE = pathlib.Path(settings.BASE_DIR)
INPUT_CSS = BASE / "static" / "mainapp" / "input.css"
STYLES_CSS = BASE / "static" / "mainapp" / "styles.css"

#: Prefixes of the component families the design system owns. Utility classes
#: (flex, px-4, text-sm) are Tailwind's own and always available, so they are
#: not the risk — a bespoke component variant is.
COMPONENT_PREFIXES = ("btn-", "alert-", "badge-", "input-", "card-", "paper-", "progress-")

#: Base names too. Excluding them meant deleting `.btn` from the compiled CSS
#: could still pass, which is the most catastrophic version of this failure.
COMPONENT_BASES = ("btn", "alert", "badge", "card", "paper", "progress", "chip")


def _is_component(name):
    return name.startswith(COMPONENT_PREFIXES) or name in COMPONENT_BASES


def _declared_component_classes():
    text = INPUT_CSS.read_text()
    declared = set()
    for match in re.finditer(
        r"^\s*((?:\.[a-zA-Z0-9_-]+)(?:[.\s,]+\.[a-zA-Z0-9_-]+)*)\s*\{", text, re.M
    ):
        declared.update(re.findall(r"\.([a-zA-Z0-9_-]+)", match.group(1)))
    return declared


def _classes_used_in_templates():
    used = set()
    for path in (BASE / "templates").rglob("*.html"):
        text = path.read_text(errors="ignore")
        for attr in re.findall(r'class="([^"]*)"', text):
            for token in attr.split():
                # Skip template expressions like {{ alert_class }}.
                if "{" in token or "}" in token:
                    continue
                used.add(token)
    return used


#: This module names the offending class in its own docstrings as the example,
#: so it must not police itself.
SELF = pathlib.Path(__file__).resolve()


def _python_files():
    for path in BASE.rglob("*.py"):
        if any(part in (".venv", "node_modules", "migrations") for part in path.parts):
            continue
        if path.resolve() == SELF:
            continue
        yield path


def _classes_used_in_python():
    """Class names in crispy `css_class=` arguments — where the button bug lived.

    Uses the AST rather than a regex, because the original bug was written as two
    implicitly concatenated literals::

        css_class="... text-gray-900 "
        "bg-[#7582EB] ..."

    A regex anchored on ``css_class="`` captures only the first of those, so the
    part containing the actual defect was invisible to it. Python has already
    joined them by the time the AST has a Constant node.
    """
    import ast

    used = set()
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg != "css_class":
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                used.update(node.value.value.split())
    return used


class CompiledCssTests(SimpleTestCase):
    def test_every_component_class_used_anywhere_is_compiled(self):
        """The guard. If this fails, run `npm run tailwind:build`; if that does
        not fix it, the class is referenced only from a place Tailwind does not
        scan, and belongs in the preview gallery."""
        styles = STYLES_CSS.read_text()
        declared = _declared_component_classes()
        used = _classes_used_in_templates() | _classes_used_in_python()

        relevant = {
            c
            for c in used
            if c in declared and _is_component(c)
        }
        missing = sorted(c for c in relevant if f".{c}" not in styles)
        self.assertEqual(
            missing,
            [],
            "design-system classes are used but absent from the compiled CSS, "
            f"so they render as nothing: {missing}",
        )

    def test_the_stylesheet_is_not_stale_for_the_gallery(self):
        """The preview gallery is what forces variants into the build, so every
        component class IT names must be compiled. If the gallery grows a new
        variant and nobody rebuilds, this catches it."""
        styles = STYLES_CSS.read_text()
        gallery = BASE / "templates" / "mainapp" / "speedpyui_preview.html"
        declared = _declared_component_classes()

        used = set()
        for attr in re.findall(r'class="([^"]*)"', gallery.read_text()):
            used.update(t for t in attr.split() if "{" not in t)

        missing = sorted(
            c
            for c in used
            if c in declared and _is_component(c) and f".{c}" not in styles
        )
        self.assertEqual(missing, [], f"gallery names uncompiled classes: {missing}")

    def test_no_hardcoded_theme_colour_anywhere_in_python(self):
        """The signup button hardcoded bg-[#7582EB] — the DARK theme's primary
        token inlined, so in light mode it was the wrong colour with near-black
        text, and its hover dropped below WCAG AA.

        Scans whole files rather than `css_class=` values, because the original
        defect lived in a second implicitly concatenated literal and an
        argument-anchored search walked straight past it. A test that cannot see
        the bug it names is worse than no test.
        """
        pattern = re.compile(r"(?:bg|text|border|ring|from|to|via)-\[#[0-9a-fA-F]{3,8}\]")
        offenders = []
        for path in _python_files():
            for match in pattern.finditer(path.read_text(errors="ignore")):
                offenders.append(f"{path.relative_to(BASE)}: {match.group(0)}")
        self.assertEqual(
            offenders,
            [],
            "hardcoded theme colours — use design-system classes so both themes "
            f"work: {offenders}",
        )

    def test_no_hardcoded_theme_colour_in_shipped_templates(self):
        """Same rule for templates. The gallery is exempt: it deliberately shows
        raw values alongside the tokens as documentation."""
        pattern = re.compile(r"(?:bg|text|border|ring)-\[#[0-9a-fA-F]{3,8}\]")
        offenders = []
        for path in (BASE / "templates").rglob("*.html"):
            if "speedpyui_preview" in path.name:
                continue
            for match in pattern.finditer(path.read_text(errors="ignore")):
                offenders.append(f"{path.relative_to(BASE)}: {match.group(0)}")
        self.assertEqual(offenders, [], f"hardcoded theme colours: {offenders}")
