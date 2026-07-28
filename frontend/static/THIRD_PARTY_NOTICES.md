# Third-party frontend assets

Generated files under `frontend/static/` are built from pinned npm packages and committed so production hosts do not require Node.js.

| Asset | Version | License | Source |
|---|---:|---|---|
| Tailwind CSS | 3.4.17 | MIT | https://www.npmjs.com/package/tailwindcss |
| HTMX | 1.9.12 | 0BSD | https://www.npmjs.com/package/htmx.org |
| Alpine.js | 3.14.1 | MIT | https://www.npmjs.com/package/alpinejs |
| SortableJS | 1.15.2 | MIT | https://www.npmjs.com/package/sortablejs |

Rebuild with `npm ci && npm run build:frontend-assets` from the repository root. Review and commit the generated asset diff together with `package-lock.json`.
