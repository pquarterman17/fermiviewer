import { useEffect, useState } from "react";

import {
  listAfmChannels,
  openAfmChannels,
  type AfmChannelInfo,
  type ImageMeta,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";

const SPM_PARSERS = new Set([
  "nanoscope",
  "gwyddion",
  "asylum",
  "jpk",
  "wsxm",
  "nanosurf",
  "ntmdt",
  "nanonis",
]);

function channelLabel(meta: ImageMeta): string {
  const value = meta.meta.channel_label ?? meta.meta.channel;
  return typeof value === "string" ? value : "Current channel";
}

/** Compact import-time inventory for an active multi-channel AFM scan. */
export default function AfmChannelPicker({ meta }: { meta: ImageMeta | null }) {
  const ingest = useViewer((s) => s.ingest);
  const select = useViewer((s) => s.select);
  const setStatus = useViewer((s) => s.setStatus);
  const [channels, setChannels] = useState<AfmChannelInfo[]>([]);
  const [busy, setBusy] = useState(false);

  const parser = meta?.meta.parser;
  const isSpm = typeof parser === "string" && SPM_PARSERS.has(parser);

  useEffect(() => {
    setChannels([]);
    if (!meta || !isSpm) return;
    const controller = new AbortController();
    void listAfmChannels(meta.id, { signal: controller.signal })
      .then(setChannels)
      .catch((error: Error) => {
        if (error.name !== "AbortError") setStatus(`channels: ${error.message}`);
      });
    return () => controller.abort();
  }, [isSpm, meta, setStatus]);

  if (!meta || channels.length < 2) return null;

  const current = channels.find((item) => item.image_id === meta.id)?.label
    ?? channelLabel(meta);

  const choose = async (label: string) => {
    const known = channels.find((item) => item.label === label);
    if (known?.image_id) {
      select(known.image_id, "single");
      return;
    }
    setBusy(true);
    try {
      const opened = await openAfmChannels(meta.id, [label]);
      if (opened.length) {
        ingest(opened);
        select(opened[0].id, "single");
        setStatus(`opened ${label}`);
      }
    } catch (error) {
      setStatus(`channels: ${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const openRemaining = async () => {
    setBusy(true);
    try {
      const opened = await openAfmChannels(meta.id);
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
      setChannels(await listAfmChannels(meta.id));
    } catch (error) {
      setStatus(`channels: ${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const closed = channels.filter((item) => !item.image_id).length;
  return (
    <section className="fvd-afm-channels" aria-label="AFM scan channels">
      <label htmlFor="fvd-afm-channel-select">
        <span>{channels.length} scan channels</span>
        <select
          id="fvd-afm-channel-select"
          value={current}
          disabled={busy}
          onChange={(event) => void choose(event.target.value)}
        >
          {channels.map((item) => (
            <option key={item.label} value={item.label}>
              {item.label}{item.image_id ? "" : " — closed"}
            </option>
          ))}
        </select>
      </label>
      {closed > 0 && (
        <button type="button" disabled={busy} onClick={() => void openRemaining()}>
          Open remaining {closed}
        </button>
      )}
    </section>
  );
}
