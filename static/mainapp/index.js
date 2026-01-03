// Theme Management System
(function() {
    'use strict';

    const STORAGE_KEY = 'theme-preference';
    const THEMES = ['light', 'dark', 'auto'];

    // Get current theme preference
    function getThemePreference() {
        return localStorage.getItem(STORAGE_KEY) || window.__themePreference || 'auto';
    }

    // Calculate effective theme (resolves 'auto' to light/dark)
    function getEffectiveTheme(preference) {
        if (preference === 'auto') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return preference;
    }

    // Apply theme to DOM
    function applyTheme(preference) {
        const effectiveTheme = getEffectiveTheme(preference);
        const htmlElement = document.documentElement;

        if (effectiveTheme === 'dark') {
            htmlElement.classList.add('dark');
        } else {
            htmlElement.classList.remove('dark');
        }

        // Update button icon if it exists
        updateThemeButton(preference);
    }

    // Cycle to next theme: light -> dark -> auto -> light
    function cycleTheme() {
        const current = getThemePreference();
        const currentIndex = THEMES.indexOf(current);
        const nextIndex = (currentIndex + 1) % THEMES.length;
        const nextTheme = THEMES[nextIndex];

        localStorage.setItem(STORAGE_KEY, nextTheme);
        applyTheme(nextTheme);

        return nextTheme;
    }

    // Update theme toggle button
    function updateThemeButton(preference) {
        const button = document.getElementById('theme-toggle');
        if (!button) return;

        const icons = {
            light: button.querySelector('[data-theme-icon="light"]'),
            dark: button.querySelector('[data-theme-icon="dark"]'),
            auto: button.querySelector('[data-theme-icon="auto"]')
        };

        // Hide all icons
        Object.values(icons).forEach(icon => {
            if (icon) icon.classList.add('hidden');
        });

        // Show current theme icon
        if (icons[preference]) {
            icons[preference].classList.remove('hidden');
        }
    }

    // Listen for system theme changes (only matters in auto mode)
    function watchSystemTheme() {
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

        mediaQuery.addEventListener('change', (e) => {
            const preference = getThemePreference();
            if (preference === 'auto') {
                applyTheme('auto');
            }
        });
    }

    // Listen for localStorage changes from other tabs
    function watchStorageChanges() {
        window.addEventListener('storage', (e) => {
            if (e.key === STORAGE_KEY) {
                applyTheme(e.newValue || 'auto');
            }
        });
    }

    // Initialize on DOM ready
    function init() {
        const preference = getThemePreference();
        applyTheme(preference);
        watchSystemTheme();
        watchStorageChanges();

        // Attach click handler to theme toggle button
        const toggleButton = document.getElementById('theme-toggle');
        if (toggleButton) {
            toggleButton.addEventListener('click', cycleTheme);
        }
    }

    // Run on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose for external use if needed
    window.themeManager = {
        getPreference: getThemePreference,
        cycle: cycleTheme,
        apply: applyTheme
    };
})();
