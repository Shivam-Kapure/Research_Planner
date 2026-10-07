"use client";

import { useEffect } from "react";

/** One liveness request when the landing page opens, so a sleeping backend (Render Free) starts
 * waking before the visitor signs in. The response is ignored. */
export function WakeBackend() {
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/healthz", { cache: "no-store", signal: controller.signal }).catch(() => undefined);
    return () => controller.abort();
  }, []);
  return null;
}
