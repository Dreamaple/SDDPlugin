// T029: CLI 未安装引导视图（contracts/cli.md §1 安装指引 + 重新检测）
import { postToHost } from '../vscode';

const INSTALL_GUIDANCE =
  'uvx --from git+https://github.com/github/spec-kit.git specify --help  或  pipx install specify-cli  或  pip install specify-cli';

export function CliMissingView() {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(INSTALL_GUIDANCE);
      void postToHost({ type: 'refresh' });
    } catch {
      // 剪贴板不可用时静默；用户可手动选择文本
    }
  };
  return (
    <div className="spk-col">
      <div className="spk-banner error">
        <strong>未找到 specify CLI</strong>
        <div className="spk-implication" style={{ marginTop: 6 }}>
          初始化与切换工具环境依赖官方 specify CLI。任选其一安装（Python ≥ 3.11）：
        </div>
        <div className="spk-context" style={{ marginTop: 6 }}>
          {INSTALL_GUIDANCE}
        </div>
        <div className="spk-implication" style={{ marginTop: 6 }}>
          已安装？可在设置中指定 <code>speckitGui.specifyCliPath</code>。
        </div>
      </div>
      <div className="spk-row">
        <button className="spk-btn" onClick={copy}>
          复制安装命令
        </button>
        <button className="spk-btn secondary" onClick={() => postToHost({ type: 'refresh' })}>
          重新检测
        </button>
      </div>
      <div className="spk-muted">离线场景下状态可视化（工作流/澄清）仍然可用。</div>
    </div>
  );
}