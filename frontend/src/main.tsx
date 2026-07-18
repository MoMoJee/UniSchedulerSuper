import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { readFrontendBootstrap } from "./bootstrap";
import "./styles/index.css";
import "./styles/visual-polish.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("未找到 React 挂载节点 #root。");
}

const bootstrap = readFrontendBootstrap();

createRoot(rootElement).render(
  <StrictMode>
    <App bootstrap={bootstrap} />
  </StrictMode>,
);
