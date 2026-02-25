const express = require("express");
const { WebSocketServer } = require("ws");
const net = require("net");
const cors = require("cors");
const path = require("path");


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

  // connect to Python socket server
  const client = net.createConnection({ host: HOST, port: PORT }, () => {
    console.log(`Connected to Python backend at ${HOST}:${PORT}`);
    const handshake = { role: "ui" };
    client.write(JSON.stringify(handshake) + "\n"); // handshake
  });

  client.on("error", (err) => {
    console.error("Error connecting to Python backend:", err);
    ws.close();
  });

  client.on("error", (err) => {
    console.error("Error connecting to Python backend:", err);
    ws.close();
  });

  // forward Python server → browser
  client.on("data", (data) => {
    data
      .toString()
      .split("\n")
      .filter(Boolean)
      .forEach((msg) => ws.send(msg));
  });

  // forward browser → Python server
  ws.on("message", (msg) => {
    client.write(msg.toString() + "\n");
  });

  ws.on("close", () => {
    console.log("Frontend WebSocket closed");
    client.end();
  });

  ws.on("error", (err) => {
    console.error("WebSocket error:", err);
    client.end();
  });
});
