let tailwindDirectories;
try {
    tailwindDirectories = require('./tailwind_directories.json');
} catch (e) {
    tailwindDirectories = [];
}

module.exports = {
    darkMode: 'class',
    content: [
        "./templates/**/*.{html,js}",
        "./usermodel/**/*.py",
        "./mainapp/**/*.py",
        ...tailwindDirectories
    ],
    theme: {
        "extend": {
            "fontFamily": {
                "sans": "\"Inter\",-apple-system,BlinkMacSystemFont,\"Segoe UI\",Helvetica,Arial,sans-serif,\"Apple Color Emoji\",\"Segoe UI Emoji\""
            },
            "spacing": {
                "112": "28rem",
                "128": "32rem",
                "144": "36rem",
                "160": "40rem",
                "192": "48rem"
            },
            "colors": {
                // Theme-sensitive tokens — values come from CSS variables defined in input.css.
                // These auto-swap on `.dark` without needing `dark:` prefix.
                "primary": {
                    // Theme-sensitive main values (auto-swap via CSS variables)
                    "DEFAULT": "rgb(var(--color-primary-main) / <alpha-value>)",
                    "light": "rgb(var(--color-primary-light) / <alpha-value>)",
                    "dark": "rgb(var(--color-primary-dark) / <alpha-value>)",
                    "contrast": "rgb(var(--color-primary-contrast) / <alpha-value>)",
                    // Numbered scale around primary #5048E5 (static in both themes,
                    // kept for backwards compatibility with existing template utilities like
                    // bg-primary-500 / text-primary-700 / bg-primary-50)
                    "50":  "#EEEEFC",
                    "100": "#DDDAF9",
                    "200": "#BDB8F2",
                    "300": "#9B92ED",
                    "400": "#7D71E9",
                    "500": "#5048E5",
                    "600": "#3A34C7",
                    "700": "#2E299B",
                    "800": "#221F71",
                    "900": "#16144A"
                },
                "secondary": {
                    "DEFAULT": "rgb(var(--color-secondary-main) / <alpha-value>)",
                    "light": "rgb(var(--color-secondary-light) / <alpha-value>)",
                    "dark": "rgb(var(--color-secondary-dark) / <alpha-value>)",
                    "contrast": "rgb(var(--color-secondary-contrast) / <alpha-value>)"
                },
                "success": {
                    "DEFAULT": "rgb(var(--color-success-main) / <alpha-value>)",
                    "light": "rgb(var(--color-success-light) / <alpha-value>)",
                    "dark": "rgb(var(--color-success-dark) / <alpha-value>)",
                    "contrast": "rgb(var(--color-success-contrast) / <alpha-value>)"
                },
                "info": {
                    "DEFAULT": "rgb(var(--color-info-main) / <alpha-value>)",
                    "light": "rgb(var(--color-info-light) / <alpha-value>)",
                    "dark": "rgb(var(--color-info-dark) / <alpha-value>)",
                    "contrast": "rgb(var(--color-info-contrast) / <alpha-value>)"
                },
                "warning": {
                    "DEFAULT": "rgb(var(--color-warning-main) / <alpha-value>)",
                    "light": "rgb(var(--color-warning-light) / <alpha-value>)",
                    "dark": "rgb(var(--color-warning-dark) / <alpha-value>)",
                    "contrast": "rgb(var(--color-warning-contrast) / <alpha-value>)"
                },
                "error": {
                    "DEFAULT": "rgb(var(--color-error-main) / <alpha-value>)",
                    "light": "rgb(var(--color-error-light) / <alpha-value>)",
                    "dark": "rgb(var(--color-error-dark) / <alpha-value>)",
                    "contrast": "rgb(var(--color-error-contrast) / <alpha-value>)"
                },
                // Neutral grayscale — same values in light and dark modes
                "neutral": {
                    "50":  "#F9FAFB",
                    "100": "#F3F4F6",
                    "200": "#E5E7EB",
                    "300": "#D1D5DB",
                    "400": "#9CA3AF",
                    "500": "#6B7280",
                    "600": "#4B5563",
                    "700": "#374151",
                    "800": "#1F2937",
                    "900": "#111827",
                    "950": "#030712",
                    "DEFAULT": "#6B7280"
                },
                // Surfaces — auto-swap via CSS variables
                "background": {
                    "DEFAULT": "rgb(var(--color-background-default) / <alpha-value>)",
                    "paper": "rgb(var(--color-background-paper) / <alpha-value>)"
                },
                // Foreground / text tokens named `fg` to avoid colliding with the
                // auto-generated `text-primary` utility from the `primary` color key.
                "fg": "rgb(var(--color-text-primary) / <alpha-value>)",
                "fg-secondary": "rgb(var(--color-text-secondary) / <alpha-value>)",
                "divider": "rgb(var(--color-divider) / <alpha-value>)",
                "white": "#FFFFFF",
                "black": "#000000"
            },
            "boxShadow": {
                // Elevation scale (subset)
                "speedpyui-1": "0px 1px 1px rgba(100, 116, 139, 0.06), 0px 1px 2px rgba(100, 116, 139, 0.1)",
                "speedpyui-3": "0px 1px 4px rgba(100, 116, 139, 0.12)",
                "speedpyui-8": "0px 2px 4px rgba(31, 41, 55, 0.06), 0px 4px 6px rgba(100, 116, 139, 0.12)",
                "speedpyui-12": "0px 6px 15px rgba(100, 116, 139, 0.12)",
                "speedpyui-16": "0px 12px 22px -8px rgba(100, 116, 139, 0.25)",
                "speedpyui-24": "0px 25px 50px rgba(100, 116, 139, 0.25)"
            },
            "backgroundImage": {
                "arrow-down": "url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='%23212529'%3e%3cpath fill-rule='evenodd' d='M1.646 4.646a.5.5 0 0 1 .708 0L8 10.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708z'/%3e%3c/svg%3e\")",
                "caret-down": "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 512'%3E%3Cpath fill='currentFill' d='M31.3 192h257.3c17.8 0 26.7 21.5 14.1 34.1L174.1 354.8c-7.8 7.8-20.5 7.8-28.3 0L17.2 226.1C4.6 213.5 13.5 192 31.3 192z'/%3E%3C/svg%3E\");"
            }
        },
    },
    plugins: [
        require('@tailwindcss/forms'),
        require('@tailwindcss/typography'),
    ],
}
