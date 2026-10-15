// T041: 任务统计边界测试（US3：无 tasks/M=0/大写 X/嵌套缩进/部分勾选）
import { describe, expect, it } from 'vitest';
import { countTaskCheckboxes } from '../../src/core/taskProgress';

describe('T041 countTaskCheckboxes', () => {
  it('无复选框 → undefined', () => {
    expect(countTaskCheckboxes('# Tasks\n\n- 普通\n条目')).toBeUndefined();
  });

  it('空内容 → undefined', () => {
    expect(countTaskCheckboxes('')).toBeUndefined();
  });

  it('M=0（无有效复选框行）→ undefined', () => {
    // `[]` 空括号不是有效 checkbox 语法（`[-*] [ ]` 才是）
    expect(countTaskCheckboxes('- [] 无效标记（空括号）\n- 普通条目')).toBeUndefined();
  });

  it('小写 [x] 计入完成', () => {
    expect(countTaskCheckboxes('- [x] a\n- [ ] b')).toEqual({ done: 1, total: 2 });
  });

  it('大写 [X] 计入完成', () => {
    expect(countTaskCheckboxes('- [X] a\n- [ ] b\n- [ ] c')).toEqual({ done: 1, total: 3 });
  });

  it('星号列表与嵌套缩进', () => {
    expect(countTaskCheckboxes('* [x] a\n  - [ ] b\n    * [x] c')).toEqual({ done: 2, total: 3 });
  });

  it('部分勾选 3/7', () => {
    const content = [
      '- [x] T001',
      '- [x] T002',
      '- [x] T003',
      '- [ ] T004',
      '- [ ] T005',
      '- [ ] T006',
      '- [ ] T007',
    ].join('\n');
    expect(countTaskCheckboxes(content)).toEqual({ done: 3, total: 7 });
  });
});