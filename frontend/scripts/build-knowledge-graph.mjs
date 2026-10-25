import {build} from 'esbuild';
import {readFile, readdir, writeFile} from 'node:fs/promises';
for (const name of ['knowledge-graph', 'action-connections', 'share-graphs', 'agent-fleet']) {
const result = await build({
  entryPoints: [`frontend/src/${name}.jsx`],
  outfile: `frontend/static/js/${name}.js`,
  bundle: true, minify: true, format: 'iife', target: ['es2020'],
  define: {'process.env.NODE_ENV': '"production"'},
  legalComments: 'linked', metafile: true
});
// Preserve complete license texts for every package included in this bundle.
const packages = new Set(Object.keys(result.metafile.inputs)
  .map(file => file.match(/^(.*node_modules\/(?:@[^/]+\/)?[^/]+)\//)?.[1])
  .filter(Boolean));
const notices = [];
for (const directory of [...packages].sort()) {
  const metadata = JSON.parse(await readFile(`${directory}/package.json`, 'utf8'));
  const files = await readdir(directory);
  const license = files.find(name => /^licen[cs]e(?:\.|$)/i.test(name));
  const licensePath = license ? `${directory}/${license}` : ['bezier-js', 'react-force-graph-2d'].includes(metadata.name) ? `frontend/scripts/${metadata.name}.LICENSE.txt` : null;
  if (!licensePath) throw new Error(`Missing license for ${metadata.name}`);
  notices.push(`${metadata.name} ${metadata.version} (${metadata.license})\n${await readFile(licensePath, 'utf8')}`);
}
await writeFile(`frontend/static/js/${name}.LICENSES.txt`, notices.join('\n\n---\n\n'));

}
