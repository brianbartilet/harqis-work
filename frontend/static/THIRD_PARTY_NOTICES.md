# Third-party frontend assets

Generated files under `frontend/static/` are built from pinned npm packages and committed so production hosts do not require Node.js.

| Asset | Version | License | Source |
|---|---:|---|---|
| Tailwind CSS | 3.4.17 | MIT | https://www.npmjs.com/package/tailwindcss |
| HTMX | 1.9.12 | 0BSD | https://www.npmjs.com/package/htmx.org |
| Alpine.js | 3.14.1 | MIT | https://www.npmjs.com/package/alpinejs |
| SortableJS | 1.15.2 | MIT | https://www.npmjs.com/package/sortablejs |

Rebuild with `npm ci && npm run build:frontend-assets` from the repository root. Review and commit the generated asset diff together with `package-lock.json`.

The connected knowledge graph bundles React/React DOM 19.3.0 (MIT),
react-force-graph-2d 1.29.1 (MIT), and d3-force-3d 3.0.6 (MIT), with their
runtime dependencies. Complete bundled package versions and license texts are in
`js/knowledge-graph.LICENSES.txt`; retained source notices are in
`js/knowledge-graph.js.LEGAL.txt`. Rebuild just this bundle with
`npm run build:knowledge-graph` from `frontend/src/knowledge-graph.jsx`.
