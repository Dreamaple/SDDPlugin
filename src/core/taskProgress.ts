// T013: tasks.md 复选框统计（contracts/artifacts.md §2）
export interface TaskStats {
  done: number;
  total: number;
}

const CHECKBOX_LINE = /^\s*[-*] \[( |x|X)\]\s/;

/** 统计 tasks.md 复选框 N/M；M=0 → undefined（进度退化为活动指示） */
export function countTaskCheckboxes(content: string): TaskStats | undefined {
  let done = 0;
  let total = 0;
  for (const line of content.split(/\r?\n/)) {
    const m = CHECKBOX_LINE.exec(line);
    if (m) {
      total++;
      if (m[1].toLowerCase() === 'x') {
        done++;
      }
    }
  }
  if (total === 0) {
    return undefined;
  }
  return { done, total };
}