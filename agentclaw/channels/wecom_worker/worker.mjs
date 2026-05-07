import process from "node:process";
import readline from "node:readline";
import { randomUUID } from "node:crypto";

import { WSClient } from "@wecom/aibot-node-sdk";

const botId = (process.env.WECOM_BOT_ID || "").trim();
const secret = (process.env.WECOM_SECRET || "").trim();
const wsUrl = (process.env.WECOM_WS_URL || "wss://openws.work.weixin.qq.com").trim();
const scene = Number.parseInt(process.env.WECOM_SCENE || "1", 10) || 1;

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function log(level, message, ...args) {
  const suffix = args.length ? ` ${args.map((item) => String(item)).join(" ")}` : "";
  process.stderr.write(`[${level}] ${message}${suffix}\n`);
}

if (!botId || !secret) {
  emit({
    type: "status",
    stage: "error",
    fatal: true,
    error: "WECOM_BOT_ID and WECOM_SECRET are required",
  });
  process.exit(2);
}

const frames = new Map();
const streamIds = new Map();
let shuttingDown = false;
let commandQueue = Promise.resolve();

const sdkLogger = {
  debug: (message, ...args) => log("debug", message, ...args),
  info: (message, ...args) => log("info", message, ...args),
  warn: (message, ...args) => log("warn", message, ...args),
  error: (message, ...args) => log("error", message, ...args),
};

const wsClient = new WSClient({
  botId,
  secret,
  wsUrl,
  logger: sdkLogger,
  heartbeatInterval: 20000,
  maxReconnectAttempts: 100,
  maxAuthFailureAttempts: 5,
  scene,
  plug_version: "agentclaw",
});

wsClient.on("connected", () => {
  emit({ type: "status", stage: "connected" });
});

wsClient.on("authenticated", () => {
  emit({ type: "status", stage: "authenticated" });
});

wsClient.on("reconnecting", (attempt) => {
  emit({ type: "status", stage: "reconnecting", attempt });
});

wsClient.on("disconnected", (reason) => {
  emit({ type: "status", stage: "disconnected", reason: reason || "" });
});

wsClient.on("event.disconnected_event", () => {
  emit({
    type: "status",
    stage: "kicked",
    fatal: true,
    error: "connection closed by server because another instance connected",
  });
  if (!shuttingDown) {
    process.exit(1);
  }
});

wsClient.on("error", (error) => {
  emit({
    type: "status",
    stage: "error",
    error: error?.message || String(error),
    name: error?.name || "",
  });
});

wsClient.on("message", (frame) => {
  const reqId = frame?.headers?.req_id || frame?.body?.msgid || randomUUID();
  frames.set(reqId, frame);
  emit({
    type: "message",
    headers: {
      ...(frame?.headers || {}),
      req_id: reqId,
    },
    command: frame?.command || "",
    body: frame?.body || {},
  });
});

async function handleCommand(command) {
  if (!command || typeof command !== "object") {
    throw new Error("invalid command");
  }

  if (command.type === "reply") {
    const reqId = String(command.req_id || "");
    const frame = frames.get(reqId);
    if (!frame) {
      throw new Error(`frame not found for req_id=${reqId}`);
    }

    const streamId = streamIds.get(reqId) || `stream_${randomUUID()}`;
    streamIds.set(reqId, streamId);

    await wsClient.replyStream(
      frame,
      streamId,
      String(command.content || ""),
      Boolean(command.finish),
    );

    if (command.finish) {
      frames.delete(reqId);
      streamIds.delete(reqId);
    }

    emit({ type: "result", op: "reply", ok: true, req_id: reqId });
    return;
  }

  if (command.type === "send") {
    const chatId = String(command.chat_id || "");
    if (!chatId) {
      throw new Error("chat_id is required");
    }

    const result = await wsClient.sendMessage(chatId, {
      msgtype: "markdown",
      markdown: {
        content: String(command.content || ""),
      },
    });

    emit({
      type: "result",
      op: "send",
      ok: true,
      chat_id: chatId,
      errcode: result?.errcode ?? 0,
      errmsg: result?.errmsg || "",
      req_id: result?.headers?.req_id || "",
    });
    return;
  }

  if (command.type === "shutdown") {
    shuttingDown = true;
    emit({ type: "status", stage: "stopping" });
    wsClient.disconnect();
    process.exit(0);
  }

  throw new Error(`unsupported command type: ${String(command.type || "")}`);
}

const rl = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
});

rl.on("line", (line) => {
  const payload = line.trim();
  if (!payload) {
    return;
  }

  commandQueue = commandQueue
    .then(async () => {
      const command = JSON.parse(payload);
      await handleCommand(command);
    })
    .catch((error) => {
      emit({
        type: "result",
        ok: false,
        error: error?.message || String(error),
      });
    });
});

rl.on("close", () => {
  if (!shuttingDown) {
    wsClient.disconnect();
  }
});

process.on("SIGTERM", () => {
  shuttingDown = true;
  wsClient.disconnect();
  process.exit(0);
});

process.on("SIGINT", () => {
  shuttingDown = true;
  wsClient.disconnect();
  process.exit(0);
});

process.on("unhandledRejection", (error) => {
  emit({
    type: "status",
    stage: "error",
    error: error?.message || String(error),
  });
});

process.on("uncaughtException", (error) => {
  emit({
    type: "status",
    stage: "error",
    fatal: true,
    error: error?.message || String(error),
  });
  process.exit(1);
});

wsClient.connect();
