import type { ChannelAccountSnapshot } from "openclaw/plugin-sdk/channel-contract";
import type { PluginRuntime } from "openclaw/plugin-sdk/core";

import { getUpdates } from "../api/api.js";
import { WeixinConfigManager } from "../api/config-cache.js";
import { MessageItemType } from "../api/types.js";
import type { WeixinMessage } from "../api/types.js";
import { SESSION_EXPIRED_ERRCODE, pauseSession, getRemainingPauseMs } from "../api/session-guard.js";
import { processOneMessage } from "../messaging/process-message.js";
import { getWeixinRuntime, waitForWeixinRuntime } from "../runtime.js";
import { getSyncBufFilePath, loadGetUpdatesBuf, saveGetUpdatesBuf } from "../storage/sync-buf.js";
import { logger } from "../util/logger.js";
import type { Logger } from "../util/logger.js";
import { redactBody } from "../util/redact.js";

const DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000;
const MAX_CONSECUTIVE_FAILURES = 3;
const BACKOFF_DELAY_MS = 30_000;
const RETRY_DELAY_MS = 2_000;
const BRIDGE_BURST_WINDOW_MS = 7_000;
const BRIDGE_BURST_MAX_MESSAGES = 5;

export type MonitorWeixinOpts = {
  baseUrl: string;
  cdnBaseUrl: string;
  token?: string;
  accountId: string;
  /** When non-empty, only messages whose from_user_id is in this list are processed. */
  allowFrom?: string[];
  config: import("openclaw/plugin-sdk/core").OpenClawConfig;
  runtime?: { log?: (msg: string) => void; error?: (msg: string) => void };
  abortSignal?: AbortSignal;
  longPollTimeoutMs?: number;
  /** Gateway status callback — called on each successful poll and inbound message. */
  setStatus?: (next: ChannelAccountSnapshot) => void;
};

/**
 * Long-poll loop: getUpdates -> normalize -> recordInboundSession -> dispatchReplyFromConfig.
 * Runs until abort.
 */
export async function monitorWeixinProvider(opts: MonitorWeixinOpts): Promise<void> {
  const {
    baseUrl,
    cdnBaseUrl,
    token,
    accountId,
    config,
    abortSignal,
    longPollTimeoutMs,
    setStatus,
  } = opts;
  const log = opts.runtime?.log ?? (() => {});
  const errLog = opts.runtime?.error ?? ((m: string) => log(m));
  const aLog: Logger = logger.withAccount(accountId);

  aLog.info(`waiting for Weixin runtime...`);
  let channelRuntime: PluginRuntime["channel"];
  try {
    const pluginRuntime = await waitForWeixinRuntime();
    channelRuntime = pluginRuntime.channel;
    aLog.info(`Weixin runtime acquired, channelRuntime type: ${typeof channelRuntime}`);
  } catch (err) {
    aLog.error(`waitForWeixinRuntime() failed: ${String(err)}`);
    throw err;
  }

  log(`weixin monitor started (${baseUrl}, account=${accountId})`);
  aLog.info(
    `Monitor started: baseUrl=${baseUrl} timeoutMs=${longPollTimeoutMs ?? DEFAULT_LONG_POLL_TIMEOUT_MS}`,
  );

  const syncFilePath = getSyncBufFilePath(accountId);
  aLog.debug(`syncFilePath: ${syncFilePath}`);

  const previousGetUpdatesBuf = loadGetUpdatesBuf(syncFilePath);
  let getUpdatesBuf = previousGetUpdatesBuf ?? "";

  if (previousGetUpdatesBuf) {
    log(`[weixin] resuming from previous sync buf (${getUpdatesBuf.length} bytes)`);
    aLog.debug(`Using previous get_updates_buf (${getUpdatesBuf.length} bytes)`);
  } else {
    log(`[weixin] no previous sync buf, starting fresh`);
    aLog.info(`No previous get_updates_buf found, starting fresh`);
  }

  const configManager = new WeixinConfigManager({ baseUrl, token }, log);

  let nextTimeoutMs = longPollTimeoutMs ?? DEFAULT_LONG_POLL_TIMEOUT_MS;
  let consecutiveFailures = 0;
  const burstBuffers = new Map<string, WeixinBridgeBurstBuffer>();

  const processFullMessage = async (full: WeixinMessage): Promise<void> => {
    const fromUserId = full.from_user_id ?? "";
    const cachedConfig = await configManager.getForUser(fromUserId, full.context_token);

    await processOneMessage(full, {
      accountId,
      config,
      channelRuntime,
      baseUrl,
      cdnBaseUrl,
      token,
      typingTicket: cachedConfig.typingTicket,
      log: opts.runtime?.log ?? (() => {}),
      errLog,
    });
  };

  const flushBridgeBurst = async (key: string, reason: string): Promise<void> => {
    const buffer = burstBuffers.get(key);
    if (!buffer) return;
    burstBuffers.delete(key);
    clearTimeout(buffer.timer);

    const sortedMessages = sortBridgeBurstMessages(buffer.messages);
    const mergedText = sortedMessages.map((message) => message.text).join("\n");
    const shellFull = sortedMessages[sortedMessages.length - 1]?.full ?? buffer.latestFull;
    const mergedFull = buildMergedWeixinMessage(shellFull, mergedText);
    aLog.info(
      `bridge_burst_flushed from=${maskWeixinId(buffer.fromUserId)} reason=${reason} bridge_burst_merged_count=${buffer.messages.length} mergedLen=${mergedText.length}`,
    );
    aLog.info(
      `bridge_burst_merged_count from=${maskWeixinId(buffer.fromUserId)} bridge_burst_merged_count=${buffer.messages.length}`,
    );
    sortedMessages.forEach((message, sortedIndex) => {
      aLog.info(
        `bridge_burst_flush_item from=${maskWeixinId(buffer.fromUserId)} sortedIndex=${sortedIndex} ${formatBridgeBurstSortFields(message)}`,
      );
    });

    try {
      await processFullMessage(mergedFull);
    } catch (err) {
      errLog(`bridge burst processOneMessage failed: ${String(err)}`);
      aLog.error(
        `bridge_burst_process_error from=${maskWeixinId(buffer.fromUserId)} err=${String(err)}`,
      );
    }
  };

  const submitBridgeBurst = (full: WeixinMessage, text: string): void => {
    const fromUserId = full.from_user_id ?? "";
    const key = buildBridgeBurstKey(accountId, fromUserId);
    const existing = burstBuffers.get(key);

    if (!existing) {
      const burstMessage = buildBridgeBurstMessage(full, text, 0);
      const timer = setTimeout(() => {
        void flushBridgeBurst(key, "window_elapsed");
      }, BRIDGE_BURST_WINDOW_MS);
      burstBuffers.set(key, {
        fromUserId,
        messages: [burstMessage],
        latestFull: full,
        timer,
      });
      aLog.info(
        `bridge_burst_started from=${maskWeixinId(fromUserId)} messageLen=${text.length} windowMs=${BRIDGE_BURST_WINDOW_MS} maxCount=${BRIDGE_BURST_MAX_MESSAGES}`,
      );
      aLog.info(
        `bridge_burst_started_sort_fields from=${maskWeixinId(fromUserId)} ${formatBridgeBurstSortFields(burstMessage)}`,
      );
      return;
    }

    const burstMessage = buildBridgeBurstMessage(full, text, existing.messages.length);
    existing.messages.push(burstMessage);
    existing.latestFull = full;
    aLog.info(
      `bridge_burst_appended from=${maskWeixinId(fromUserId)} messageLen=${text.length} bufferedCount=${existing.messages.length}`,
    );
    aLog.info(
      `bridge_burst_appended_sort_fields from=${maskWeixinId(fromUserId)} bufferedCount=${existing.messages.length} ${formatBridgeBurstSortFields(burstMessage)}`,
    );
    if (existing.messages.length >= BRIDGE_BURST_MAX_MESSAGES) {
      void flushBridgeBurst(key, "max_messages");
    }
  };

  while (!abortSignal?.aborted) {
    try {
      aLog.debug(
        `getUpdates: get_updates_buf=${getUpdatesBuf.substring(0, 50)}..., timeoutMs=${nextTimeoutMs}`,
      );
      const resp = await getUpdates({
        baseUrl,
        token,
        get_updates_buf: getUpdatesBuf,
        timeoutMs: nextTimeoutMs,
      });
      aLog.debug(
        `getUpdates response: ret=${resp.ret}, msgs=${resp.msgs?.length ?? 0}, get_updates_buf_length=${resp.get_updates_buf?.length ?? 0}`,
      );

      if (resp.longpolling_timeout_ms != null && resp.longpolling_timeout_ms > 0) {
        nextTimeoutMs = resp.longpolling_timeout_ms;
        aLog.debug(`Updated next poll timeout: ${nextTimeoutMs}ms`);
      }
      const isApiError =
        (resp.ret !== undefined && resp.ret !== 0) ||
        (resp.errcode !== undefined && resp.errcode !== 0);
      if (isApiError) {
        const isSessionExpired =
          resp.errcode === SESSION_EXPIRED_ERRCODE || resp.ret === SESSION_EXPIRED_ERRCODE;

        if (isSessionExpired) {
          pauseSession(accountId);
          const pauseMs = getRemainingPauseMs(accountId);
          errLog(
            `weixin getUpdates: session expired (errcode ${SESSION_EXPIRED_ERRCODE}), pausing bot for ${Math.ceil(pauseMs / 60_000)} min`,
          );
          aLog.error(
            `getUpdates: session expired (errcode=${resp.errcode} ret=${resp.ret}), pausing all requests for ${Math.ceil(pauseMs / 60_000)} min`,
          );
          consecutiveFailures = 0;
          await sleep(pauseMs, abortSignal);
          continue;
        }

        consecutiveFailures += 1;
        errLog(
          `weixin getUpdates failed: ret=${resp.ret} errcode=${resp.errcode} errmsg=${resp.errmsg ?? ""} (${consecutiveFailures}/${MAX_CONSECUTIVE_FAILURES})`,
        );
        aLog.error(
          `getUpdates failed: ret=${resp.ret} errcode=${resp.errcode} errmsg=${resp.errmsg} response=${redactBody(JSON.stringify(resp))}`,
        );
        if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
          errLog(
            `weixin getUpdates: ${MAX_CONSECUTIVE_FAILURES} consecutive failures, backing off 30s`,
          );
          aLog.error(
            `getUpdates: ${MAX_CONSECUTIVE_FAILURES} consecutive failures, backing off 30s`,
          );
          consecutiveFailures = 0;
          await sleep(BACKOFF_DELAY_MS, abortSignal);
        } else {
          await sleep(RETRY_DELAY_MS, abortSignal);
        }
        continue;
      }
      consecutiveFailures = 0;
      setStatus?.({ accountId, lastEventAt: Date.now() });
      if (resp.get_updates_buf != null && resp.get_updates_buf !== "") {
        saveGetUpdatesBuf(syncFilePath, resp.get_updates_buf);
        getUpdatesBuf = resp.get_updates_buf;
        aLog.debug(`Saved new get_updates_buf (${getUpdatesBuf.length} bytes)`);
      }
      const list = resp.msgs ?? [];
      const orderedList = sortWeixinMessagesForBurst(list);
      for (const full of orderedList) {
        const topKeys = Object.keys(full ?? {}).join(",");
        const itemTypes = full.item_list?.map((i) => i.type).join(",") ?? "none";
        aLog.info(
          `inbound message: from=${maskWeixinId(full.from_user_id ?? "")} messageId=${full.message_id ?? "none"} topKeys=${topKeys || "none"} hasItemList=${Array.isArray(full.item_list)} itemTypes=${itemTypes}`,
        );

        const now = Date.now();
        setStatus?.({ accountId, lastEventAt: now, lastInboundAt: now });

        // allowFrom filtering is delegated to processOneMessage via the framework
        // authorization pipeline (resolveSenderCommandAuthorizationWithRuntime).

        const burstText = getPrivatePureText(full);
        if (burstText) {
          submitBridgeBurst(full, burstText);
          continue;
        }

        await flushBridgeBurst(buildBridgeBurstKey(accountId, full.from_user_id ?? ""), "interrupted");
        await processFullMessage(full);
      }
    } catch (err) {
      if (abortSignal?.aborted) {
        aLog.info(`Monitor stopped (aborted)`);
        return;
      }
      consecutiveFailures += 1;
      errLog(
        `weixin getUpdates error (${consecutiveFailures}/${MAX_CONSECUTIVE_FAILURES}): ${String(err)}`,
      );
      aLog.error(`getUpdates error: ${String(err)}, stack=${(err as Error).stack}`);
      if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
        errLog(
          `weixin getUpdates: ${MAX_CONSECUTIVE_FAILURES} consecutive failures, backing off 30s`,
        );
        aLog.error(
          `getUpdates: ${MAX_CONSECUTIVE_FAILURES} consecutive failures, backing off 30s`,
        );
        consecutiveFailures = 0;
        await sleep(30_000, abortSignal);
      } else {
        await sleep(2000, abortSignal);
      }
    }
  }
  for (const key of burstBuffers.keys()) {
    await flushBridgeBurst(key, "monitor_ended");
  }
  aLog.info(`Monitor ended`);
}

type WeixinBridgeBurstBuffer = {
  fromUserId: string;
  messages: WeixinBridgeBurstMessage[];
  latestFull: WeixinMessage;
  timer: ReturnType<typeof setTimeout>;
};

type WeixinBridgeBurstMessage = {
  full: WeixinMessage;
  text: string;
  orderIndex: number;
  createTimeMs?: number;
  createTime?: number;
  seq?: number;
  messageId?: number;
};

function getPrivatePureText(full: WeixinMessage): string {
  if (full.group_id) return "";
  const items = full.item_list ?? [];
  if (items.length !== 1) return "";
  const item = items[0];
  if (!item) return "";
  if (item.type !== MessageItemType.TEXT || item.ref_msg) return "";
  const text = String(item.text_item?.text ?? "").trim();
  return text;
}

function buildBridgeBurstKey(accountId: string, fromUserId: string): string {
  return `${accountId}:${fromUserId}`;
}

function sortWeixinMessagesForBurst(list: WeixinMessage[]): WeixinMessage[] {
  return list
    .map((full, index) => ({ full, index }))
    .sort(compareIndexedWeixinMessage)
    .map(({ full }) => full);
}

function compareIndexedWeixinMessage(
  left: { full: WeixinMessage; index: number },
  right: { full: WeixinMessage; index: number },
): number {
  for (const key of ["create_time_ms", "create_time", "seq", "message_id"]) {
    const leftValue = getWeixinSortableNumber(left.full, key);
    const rightValue = getWeixinSortableNumber(right.full, key);
    if (leftValue == null && rightValue == null) continue;
    if (leftValue == null) return 1;
    if (rightValue == null) return -1;
    if (leftValue !== rightValue) return leftValue - rightValue;
  }
  return left.index - right.index;
}

function getWeixinSortableNumber(full: WeixinMessage, key: string): number | undefined {
  const value = (full as Record<string, unknown>)[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function buildBridgeBurstMessage(
  full: WeixinMessage,
  text: string,
  orderIndex: number,
): WeixinBridgeBurstMessage {
  return {
    full,
    text,
    orderIndex,
    createTimeMs: getWeixinSortableNumber(full, "create_time_ms"),
    createTime: getWeixinSortableNumber(full, "create_time"),
    seq: getWeixinSortableNumber(full, "seq"),
    messageId: getWeixinSortableNumber(full, "message_id"),
  };
}

function sortBridgeBurstMessages(messages: WeixinBridgeBurstMessage[]): WeixinBridgeBurstMessage[] {
  return [...messages].sort(compareBridgeBurstMessage);
}

function compareBridgeBurstMessage(
  left: WeixinBridgeBurstMessage,
  right: WeixinBridgeBurstMessage,
): number {
  for (const key of ["createTimeMs", "createTime", "seq", "messageId"] as const) {
    const leftValue = left[key];
    const rightValue = right[key];
    if (leftValue == null && rightValue == null) continue;
    if (leftValue == null) return 1;
    if (rightValue == null) return -1;
    if (leftValue !== rightValue) return leftValue - rightValue;
  }
  return left.orderIndex - right.orderIndex;
}

function formatBridgeBurstSortFields(message: WeixinBridgeBurstMessage): string {
  const preview = JSON.stringify(message.text.slice(0, 32));
  return [
    `orderIndex=${message.orderIndex}`,
    `createTimeMs=${formatSortableNumber(message.createTimeMs)}`,
    `createTime=${formatSortableNumber(message.createTime)}`,
    `seq=${formatSortableNumber(message.seq)}`,
    `messageId=${formatSortableNumber(message.messageId)}`,
    `textLen=${message.text.length}`,
    `textPreview=${preview}`,
  ].join(" ");
}

function formatSortableNumber(value?: number): string {
  return value == null ? "none" : String(value);
}

function buildMergedWeixinMessage(latestFull: WeixinMessage, mergedText: string): WeixinMessage {
  const items = latestFull.item_list ?? [];
  const mergedItems = items.map((item) => {
    if (item.type !== MessageItemType.TEXT) return item;
    return {
      ...item,
      text_item: {
        ...(item.text_item ?? {}),
        text: mergedText,
      },
    };
  });

  return {
    ...latestFull,
    item_list: mergedItems.length > 0 ? mergedItems : [{
      type: MessageItemType.TEXT,
      text_item: { text: mergedText },
    }],
  };
}

function maskWeixinId(value: string): string {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.length <= 8) return "***";
  return `${text.slice(0, 4)}...${text.slice(-4)}`;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(new Error("aborted"));
      },
      { once: true },
    );
  });
}
