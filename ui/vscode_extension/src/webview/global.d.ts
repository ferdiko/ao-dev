declare module '*.module.css' {
  const classes: { [key: string]: string };
  export default classes;
}

interface VscodeApi {
  postMessage(message: any): void;
  getState(): any;
  setState(state: any): void;
}

declare global {
  interface Window {
    vscode?: VscodeApi;
  }
} 