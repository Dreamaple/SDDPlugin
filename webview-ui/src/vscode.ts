// T003: vscode api 桥（Webview 内 acquireVsCodeApi）
import type { HostToWebview, WebviewToHost } from '../../shared/protocol';

interface VsCodeApi {
  postMessage(msg: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

declare function acquireVsCodeApi(): VsCodeApi;

let api: VsCodeApi | undefined;

export function getVsCodeApi(): VsCodeApi {
  if (!api) {
    api = acquireVsCodeApi();
  }
  return api;
}

export function postToHost(msg: WebviewToHost): void {
  getVsCodeApi().postMessage(msg);
}

/** 订阅宿主下行消息（HostToWebview） */
export function onHostMessage(handler: (msg: HostToWebview) => void): () => void {
  const listener = (event: MessageEvent) => {
    const data = event.data as HostToWebview;
    if (data && typeof data === 'object' && 'type' in data) {
      handler(data);
    }
  };
  window.addEventListener('message', listener);
  return () => window.removeEventListener('message', listener);
}