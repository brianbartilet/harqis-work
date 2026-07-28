/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './frontend/templates/**/*.html',
    './frontend/**/*.py',
  ],
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
