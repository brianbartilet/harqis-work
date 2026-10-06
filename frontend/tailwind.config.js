/** @type {import('tailwindcss').Config} */
module.exports = {
  // Source paths are declared relative to assets/tailwind.css with @source.
  theme: {
    extend: {
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'spin-slow': 'spin 2s linear infinite',
      },
    },
  },
  plugins: [],
};
