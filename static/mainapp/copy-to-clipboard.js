/**
 * Copy-to-clipboard buttons that tell you they worked.
 *
 * The old inline `onclick="navigator.clipboard.writeText(...)"` buttons copied
 * silently: no label change, no error when the write was rejected (a non-secure
 * origin, or a browser that denies the permission). This is one delegated
 * handler for all of them.
 *
 * Markup contract — see templates/components/copy_button.html:
 *
 *   <button class="btn btn-outlined btn-secondary"
 *           data-copy-target="#embed-snippet"     <!-- or data-copy-value="…" -->
 *           data-copy-done="Copied!"              <!-- optional labels -->
 *           data-copy-failed="Press Ctrl+C"
 *           data-copy-done-class="btn-success"
 *           aria-live="polite">Copy</button>
 *
 * The target's text is read from `value` (inputs), `href` (links), or
 * `textContent`. `data-copy-done-class` is named in the TEMPLATE, not here,
 * because Tailwind only scans templates and Python files for class names.
 */
(function () {
    'use strict';

    const RESET_MS = 2000;
    // Button color classes the done-state swaps out, so the restore is exact.
    const COLOR_CLASSES = [
        'btn-primary', 'btn-secondary', 'btn-success', 'btn-info',
        'btn-warning', 'btn-error', 'btn-inherit'
    ];

    function textToCopy(button) {
        if (button.hasAttribute('data-copy-value')) {
            return button.getAttribute('data-copy-value');
        }
        const selector = button.getAttribute('data-copy-target');
        const target = selector ? document.querySelector(selector) : null;
        if (!target) return null;
        if (typeof target.value === 'string') return target.value;
        if (target.tagName === 'A') return target.href;
        return (target.textContent || '').trim();
    }

    function writeToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            // The async API rejects on an unfocused document and under some
            // permission policies, so fall through to the legacy path before
            // telling the user it failed.
            return navigator.clipboard.writeText(text).catch(function () {
                return legacyCopy(text);
            });
        }
        return legacyCopy(text);
    }

    function legacyCopy(text) {
        // For non-secure origins (plain http:// dev hosts), older browsers, and
        // whenever the async API refuses.
        return new Promise(function (resolve, reject) {
            const area = document.createElement('textarea');
            area.value = text;
            area.setAttribute('readonly', '');
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            let ok = false;
            try {
                ok = document.execCommand('copy');
            } catch (e) {
                ok = false;
            }
            document.body.removeChild(area);
            ok ? resolve() : reject(new Error('copy command rejected'));
        });
    }

    function selectTarget(button) {
        // Copy failed: at least put the text under the user's cursor so the
        // keyboard shortcut finishes the job.
        const selector = button.getAttribute('data-copy-target');
        const target = selector ? document.querySelector(selector) : null;
        if (!target) return;
        if (typeof target.select === 'function') {
            target.focus();
            target.select();
            return;
        }
        const selection = window.getSelection();
        if (!selection) return;
        const range = document.createRange();
        range.selectNodeContents(target);
        selection.removeAllRanges();
        selection.addRange(range);
    }

    function showState(button, doneLabel, doneClass) {
        if (button.dataset.copyIdleLabel === undefined) {
            button.dataset.copyIdleLabel = button.textContent;
        }
        window.clearTimeout(Number(button.dataset.copyTimer || 0));

        const idleColor = COLOR_CLASSES.filter(function (name) {
            return button.classList.contains(name);
        });
        if (doneClass && idleColor.length) {
            button.dataset.copyIdleColor = idleColor.join(' ');
            idleColor.forEach(function (name) { button.classList.remove(name); });
            button.classList.add(doneClass);
        }
        button.textContent = doneLabel;

        button.dataset.copyTimer = String(window.setTimeout(function () {
            button.textContent = button.dataset.copyIdleLabel;
            if (doneClass) {
                button.classList.remove(doneClass);
                (button.dataset.copyIdleColor || '').split(' ')
                    .filter(Boolean)
                    .forEach(function (name) { button.classList.add(name); });
            }
        }, RESET_MS));
    }

    document.addEventListener('click', function (event) {
        const origin = event.target;
        if (!origin || typeof origin.closest !== 'function') return;
        const button = origin.closest('[data-copy-target], [data-copy-value]');
        if (!button) return;

        const text = textToCopy(button);
        if (text === null || text === '') {
            showState(button, button.getAttribute('data-copy-failed') || 'Nothing to copy', 'btn-error');
            return;
        }
        writeToClipboard(text).then(function () {
            showState(
                button,
                button.getAttribute('data-copy-done') || 'Copied!',
                button.getAttribute('data-copy-done-class') || 'btn-success'
            );
        }).catch(function () {
            selectTarget(button);
            showState(
                button,
                button.getAttribute('data-copy-failed') || 'Copy failed — press Ctrl+C',
                button.getAttribute('data-copy-failed-class') || 'btn-error'
            );
        });
    });
})();
