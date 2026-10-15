// T039: 集成测试——触发/传输层（US2）
// 经 vscode 桩验证 dispatcher 令牌推导与 transports 回执（SC-004 语义：令牌送达）
import { afterAll, beforeEach, describe, expect, it } from 'vitest';
import { dispatchToken } from '../../src/dispatch/transports';
import { tokenForStage } from '../../src/dispatch/dispatcher';
import {
  getRecordedCommands,
  resetStubs,
  getClipboardTexts,
} from '../helpers/vscode-stub';

beforeEach(() => {
  resetStubs();
  delete (globalThis as Record<string, unknown>).__SPK_CONFIG;
});

afterAll(() => {
  delete (globalThis as Record<string, unknown>).__SPK_CONFIG;
});

describe('T039 dispatch × transports（US2 集成）', () => {
  it('tokenForStage：skills/命令模式两种令牌（contracts/dispatch.md §1 映射表）', () => {
    const stages = [
      'constitution',
      'specify',
      'clarify',
      'plan',
      'tasks',
      'analyze',
      'implement',
    ] as const;
    expect(stages.map((s) => tokenForStage(s, true))).toEqual([
      '/speckit-constitution',
      '/speckit-specify',
      '/speckit-clarify',
      '/speckit-plan',
      '/speckit-tasks',
      '/speckit-analyze',
      '/speckit-implement',
    ]);
    expect(stages.map((s) => tokenForStage(s, false))).toEqual([
      '/speckit.constitution',
      '/speckit.specify',
      '/speckit.clarify',
      '/speckit.plan',
      '/speckit.tasks',
      '/speckit.analyze',
      '/speckit.implement',
    ]);
  });

  it('Transport A chat-open → dispatched + 聊天命令被预填令牌（场景 2c）', async () => {
    const outcome = await dispatchToken('/speckit-tasks', 'chat-open');
    expect(outcome).toBe('dispatched');
    const calls = getRecordedCommands().filter((c) => c.command === 'workbench.action.chat.open');
    expect(calls).toHaveLength(1);
    expect(calls[0].args[0]).toBe('/speckit-tasks ');
  });

  it('Transport A 失败 → 回退 clipboard + fallback-clipboard 回执', async () => {
    // 桩中空令牌会抛错；此处直接用 clipboard 传输验证回退路径
    const outcome = await dispatchToken('/speckit-plan', 'clipboard');
    expect(outcome).toBe('fallback-clipboard');
    expect(getClipboardTexts()).toContain('/speckit-plan');
    expect(getRecordedCommands().some((c) => c.command === 'showInformationMessage')).toBe(true);
  });

  it('chat-open 抛错时自动回退剪贴板（contracts/dispatch.md §2）', async () => {
    // 桩对 workbench.action.chat.open 空参抛错；传空令牌触发回退路径
    const outcome = await dispatchToken(' ', 'chat-open');
    expect(outcome).toBe('fallback-clipboard');
    expect(getClipboardTexts()).toContain(' ');
  });
});