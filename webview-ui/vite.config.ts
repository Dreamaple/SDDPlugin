// T003: Webview 前端构建配置（React 18，单 JS/单 CSS 产物 → webview-ui/dist/）
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  root: __dirname,
  base: './',
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, 'dist'),
    emptyOutDir: true,
    modulePreload: false,
    target: 'es2020',
    rollupOptions: {
      output: {
        // 单 JS 入口（IIFE，兼容 Webview CSP nonce 加载）
        format: 'iife',
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name].[ext]',
      },
    },
  },
});