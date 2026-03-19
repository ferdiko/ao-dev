const express = require("express");
const { WebSocketServer, WebSocket } = require("ws");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");
const cors = require("cors");

const HOST = process.env.PYTHON_HOST || "127.0.0.1";
const PORT = process.env.PYTHON_PORT ? parseInt(process.env.PYTHON_PORT) : 5959;
const WS_PORT = process.env.WS_PORT ? parseInt(process.env.WS_PORT) : 4000;
const MAX_RETRIES = 10;
const RETRY_DELAY_MS = 1500;

const app = express();
app.use(cors());

const server = app.listen(WS_PORT, "0.0.0.0", () =>
  console.log(`Web proxy running on ws://0.0.0.0:${WS_PORT}`)
);

function getConfigPath() {
  const aoHome = process.env.AO_HOME || path.join(os.homedir(), ".ao");
  return process.env.AO_CONFIG || path.join(aoHome, "config.yaml");
}

function getPythonPath() {
  try {
    const content = fs.readFileSync(getConfigPath(), "utf8");
    const match = content.match(/python_executable:\s*(.+)/);
    if (match && match[1]) return match[1].trim();
  } catch {}
  return "python3";
}

function startServer() {
  const pythonPath = getPythonPath();
  console.log(`Starting ao server with: ${pythonPath}`);
  const proc = spawn(pythonPath, ["-m", "ao.cli.ao_server", "start"], {
    detached: true,
    stdio: "pipe",
  });
  proc.stdout?.on("data", (d) => console.log("ao-server:", d.toString().trim()));
  proc.stderr?.on("data", (d) => console.error("ao-server:", d.toString().trim()));
  proc.on("error", (err) => console.error("Failed to start ao server:", err.message));
  proc.unref();
}

function connectToBackend(ws, attempt = 0) {
  const backend = new WebSocket(`ws://${HOST}:${PORT}/ws`);

  backend.on("open", () => {
    console.log(`Connected to Python backend at ${HOST}:${PORT}`);

    // Forward Python server → browser
    backend.on("message", (data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data.toString());
      }
    });

    // Forward browser → Python server
    ws.on("message", (msg) => {
      if (backend.readyState === WebSocket.OPEN) {
        backend.send(msg.toString());
      }
    });

    ws.on("close", () => {
      console.log("Frontend WebSocket closed");
      backend.close();
    });

    ws.on("error", (err) => {
      console.error("WebSocket error:", err.message);
      backend.close();
    });
  });

  backend.on("error", (err) => {
    if (attempt === 0) {
      startServer();
    }
    if (attempt < MAX_RETRIES) {
      console.log(`Backend not ready, retrying (${attempt + 1}/${MAX_RETRIES})...`);
      setTimeout(() => connectToBackend(ws, attempt + 1), RETRY_DELAY_MS);
    } else {
      console.error("Could not connect to Python backend:", err.message);
      ws.close();
    }
  });
}

const wss = new WebSocketServer({ server, path: "/ws" });

wss.on("connection", (ws) => {
  console.log("Frontend connected via WebSocket");
  connectToBackend(ws);
});
