import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const assets = [
  ['node_modules/htmx.org/dist/htmx.min.js', 'frontend/static/vendor/htmx-1.9.12.min.js'],
  ['node_modules/alpinejs/dist/cdn.min.js', 'frontend/static/vendor/alpinejs-3.14.1.min.js'],
  ['node_modules/sortablejs/Sortable.min.js', 'frontend/static/vendor/sortablejs-1.15.2.min.js'],
];

for (const [source, destination] of assets) {
  const target = resolve(destination);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(resolve(source), target);
}
