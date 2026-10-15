// T038: 特性切换器（FR-012：多特性目录查看与切换当前特性）
import { postToHost } from '../vscode';
import type { Feature } from '../../../shared/protocol';

export function FeatureSwitcher(props: { features: Feature[]; disabled?: boolean }) {
  const { features, disabled } = props;
  if (features.length === 0) {
    return <span className="spk-muted">specs/ 下暂无特性</span>;
  }
  const current = features.find((f) => f.isCurrent);
  return (
    <label className="spk-row" style={{ margin: 0 }}>
      <span className="spk-muted">当前特性</span>
      <select
        className="spk-select"
        style={{ width: 'auto', minWidth: 180 }}
        disabled={disabled}
        value={current?.dirName ?? ''}
        onChange={(e) => {
          const dir = e.target.value;
          if (dir) {
            postToHost({ type: 'selectFeature', dirName: dir });
          }
        }}
      >
        {features.map((f) => (
          <option key={f.dirName} value={f.dirName}>
            {f.dirName}
          </option>
        ))}
      </select>
    </label>
  );
}