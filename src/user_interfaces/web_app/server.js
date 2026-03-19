const express = require("express");
const { WebSocketServer, WebSocket } = require("ws");
const cors = require("cors");

const HOST = process.env.PYTHON_HOST || "127.0.0.1";
const PORT = process.env.PYTHON_PORT ? parseInt(process.env.PYTHON_PORT) : 5959;
const WS_PORT = process.env.WS_PORT ? parseInt(process.env.WS_PORT) : 4000;

const app = express();
app.use(cors());

const server = app.listen(WS_PORT, "0.0.0.0", () =>
  console.log(`Web proxy running on ws://0.0.0.0:${WS_PORT}`)
);

const wss = new WebSocketServer({ server, path: "/ws" });

wss.on("connection", (ws) => {
  console.log("Frontend connected via WebSocket");

  // Connect to Python backend via WebSocket
  const backend = new WebSocket(`ws://${HOST}:${PORT}/ws`);

  backend.on("open", () => {
    console.log(`Connected to Python backend at ${HOST}:${PORT}`);
  });

  backend.on("error", (err) => {
    console.error("Error connecting to Python backend:", err.message);
    ws.close();
  });

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
