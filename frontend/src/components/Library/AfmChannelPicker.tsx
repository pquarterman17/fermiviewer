import { useEffect, useState } from "react";

import {
  listAfmChannels,
  openAfmChannels,
  type AfmChannelInfo,
  type ImageMeta,
} from "../../lib/api";
import { supportsSpmChannels } from "../../lib/spm";
import { useLatestRequest } from "../../hooks/useLatestRequest";
import { useViewer } from "../../store/viewer";

function channelLabel(meta: ImageMeta): string {
  const value = meta.meta.channel_label ?? meta.meta.channel;
  return typeof value === "string" ? value : "Current channel";
}

/** Compact import-time inventory for an active multi-channel AFM scan. */
export default function AfmChannelPicker({ meta }: { meta: ImageMeta | null }) {
  const ingest = useViewer((s) => s.ingest);
  const select = useViewer((s) => s.select);
  const setStatus = useViewer((s) => s.setStatus);
  const images = useViewer((s) => s.images);
  const [channels, setChannels] = useState<AfmChannelInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);
  const channelRequest = useLatestRequest(meta?.id);

  const isSpm = supportsSpmChannels(meta);
  const imageIds = Object.keys(images).sort().join(",");

  useEffect(() => {
    setChannels([]);
    setBusy(false);
    setMessage(null);
  }, [meta?.id]);

  useEffect(() => {
    if (!meta || !isSpm) {
      setChannels([]);
      return;
    }
    const controller = new AbortController();
    void listAfmChannels(meta.id, { signal: controller.signal })
      .then(setChannels)
      .catch((error: Error) => {
        if (error.name !== "AbortError") setStatus(`channels: ${error.message}`);
      });
    return () => controller.abort();
  }, [imageIds, isSpm, meta, setStatus]);

  if (!meta || channels.length < 2) return null;

  const isLive = (
    item: AfmChannelInfo,
  ): item is AfmChannelInfo & { image_id: string } =>
    item.image_id !== null && item.image_id in images;
  const current = channels.find((item) => item.image_id === meta.id)?.label
    ?? channelLabel(meta);

  const choose = async (label: string) => {
    const known = channels.find((item) => item.label === label);
    if (known && isLive(known)) {
      channelRequest.invalidate();
      select(known.image_id, "single");
      return;
    }
    const request = channelRequest.begin();
    setBusy(true);
    setMessage({ error: false, text: `Opening ${label}…` });
    try {
      const opened = await openAfmChannels(meta.id, [label], { signal: request.signal });
      if (!request.isCurrent()) return;
      if (opened.length) {
        ingest(opened);
        select(opened[0].id, "single");
        setStatus(`opened ${label}`);
        setMessage({ error: false, text: `${label} opened` });
      } else {
        // Another surface may have opened it since this inventory response.
        const refreshed = await listAfmChannels(meta.id, { signal: request.signal });
        if (!request.isCurrent()) return;
        setChannels(refreshed);
        const nowOpen = refreshed.find((item) => item.label === label);
        if (nowOpen && isLive(nowOpen)) select(nowOpen.image_id, "single");
      }
    } catch (error) {
      if (request.isCurrent()) {
        const text = `${label}: ${(error as Error).message}`;
        setMessage({ error: true, text });
        setStatus(`channels: ${text}`);
      }
    } finally {
      if (request.isCurrent()) setBusy(false);
    }
  };

  const openRemaining = async () => {
    const request = channelRequest.begin();
    const remaining = channels.filter((item) => !isLive(item)).map((item) => item.label);
    setBusy(true);
    setMessage({
      error: false,
      text: `Opening ${remaining.length} remaining channel${remaining.length === 1 ? "" : "s"}…`,
    });
    try {
      const opened = await openAfmChannels(meta.id, remaining, { signal: request.signal });
      if (!request.isCurrent()) return;
      if (opened.length) {
        ingest(opened);
        // Bulk discovery should not pull the stage away from the channel the
        // user was inspecting. The explicit selector is the navigation path.
        select(meta.id, "single");
      }
      setStatus(
        opened.length
          ? `opened ${opened.length} channel${opened.length === 1 ? "" : "s"}`
          : "all channels of this scan are already open",
      );
      setMessage({
        error: false,
        text: opened.length
          ? `${opened.length} channel${opened.length === 1 ? "" : "s"} opened`
          : "All channels are already open",
      });
      const refreshed = await listAfmChannels(meta.id, { signal: request.signal });
      if (request.isCurrent()) setChannels(refreshed);
    } catch (error) {
      if (request.isCurrent()) {
        const text = `Remaining channels: ${(error as Error).message}`;
        setMessage({ error: true, text });
        setStatus(`channels: ${text}`);
      }
    } finally {
      if (request.isCurrent()) setBusy(false);
    }
  };

  const closed = channels.filter((item) => !isLive(item)).length;
  return (
    <section className="fvd-afm-channels" aria-label="AFM scan channels">
      <label htmlFor="fvd-afm-channel-select">
        <span>{channels.length} scan channels</span>
        <select
          id="fvd-afm-channel-select"
          value={current}
          onChange={(event) => void choose(event.target.value)}
        >
          {channels.map((item) => (
            <option key={item.label} value={item.label}>
              {item.label}{isLive(item) ? "" : " — closed"}
            </option>
          ))}
        </select>
      </label>
      {closed > 0 && (
        <button type="button" disabled={busy} onClick={() => void openRemaining()}>
          Open remaining {closed}
        </button>
      )}
      {message && (
        <span className={message.error ? "error" : ""} role={message.error ? "alert" : "status"}>
          {message.text}
        </span>
      )}
    </section>
  );
}
