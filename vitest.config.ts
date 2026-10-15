// T004: Vitest 配置（node 环境；integration 测试在无 VS Code 二进制时自行跳过）
// 'vscode' 模块在 vitest 中别名为轻量桩（tests/helpers/vscode-stub.ts），
// 使 vscode 依赖的编排逻辑（initRunner/transports/specWriter）可在 Node 测试。
import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      vscode: path.resolve(__dirname, 'tests/helpers/vscode-stub.ts'),
    },
  },
  test: {
    environment: 'node',
    include: ['tests/unit/**/*.test.ts', 'tests/integration/**/*.test.ts'],
    testTimeout: 30000,
  },
});