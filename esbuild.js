// T002: 扩展宿主端打包脚本（esbuild → dist/extension.js，CJS，external vscode）
const esbuild = require('esbuild');

const watch = process.argv.includes('--watch');

/** @type {import('esbuild').BuildOptions} */
const options = {
  entryPoints: ['src/extension.ts'],
  bundle: true,
  outfile: 'dist/extension.js',
  external: ['vscode'],
  format: 'cjs',
  platform: 'node',
  target: 'node18',
  sourcemap: true,
  logLevel: 'info',
  conditions: ['node'],
};

async function main() {
  if (watch) {
    const ctx = await esbuild.context(options);
    await ctx.watch();
    console.log('[esbuild] watching src/extension.ts ...');
  } else {
    await esbuild.build(options);
    console.log('[esbuild] built dist/extension.js');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});