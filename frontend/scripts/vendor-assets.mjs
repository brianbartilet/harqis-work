import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const assets = [
  ['node_modules/swagger-ui-dist/swagger-ui-bundle.js', 'frontend/static/vendor/swagger-ui-bundle-5.35.0.js'],
  ['node_modules/swagger-ui-dist/swagger-ui.css', 'frontend/static/vendor/swagger-ui-5.35.0.css'],
  ['node_modules/swagger-ui-dist/LICENSE', 'frontend/static/vendor/swagger-ui-LICENSE.txt'],
  ['node_modules/swagger-ui-dist/NOTICE', 'frontend/static/vendor/swagger-ui-NOTICE.txt'],
  ['node_modules/swagger-ui-dist/swagger-ui-bundle.js.LICENSE.txt', 'frontend/static/vendor/swagger-ui-bundle-5.35.0.js.LICENSE.txt'],
  ['node_modules/htmx.org/dist/htmx.min.js', 'frontend/static/vendor/htmx-1.9.12.min.js'],
  ['node_modules/alpinejs/dist/cdn.min.js', 'frontend/static/vendor/alpinejs-3.17.5.min.js'],
  ['node_modules/sortablejs/Sortable.min.js', 'frontend/static/vendor/sortablejs-1.15.7.min.js'],
];

for (const [source, destination] of assets) {
  const target = resolve(destination);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(resolve(source), target);
}
