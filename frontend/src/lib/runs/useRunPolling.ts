"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { RunPoller, type RunSnapshot } from "./poller";

const EMPTY: RunSnapshot = {
  run: null,
  events: [],
  outputs: null,
  result: null,
  settled: false,
  connectionError: null,
  fatalError: null,
};

/** Live view of one run; polling stops on its own once the run is terminal and loaded. */
export function useRunPolling(runId: string) {
  const [snapshot, setSnapshot] = useState<RunSnapshot>(EMPTY);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const poller = new RunPoller(api, runId, setSnapshot);
    void poller.start();
    return () => poller.stop();
  }, [runId, generation]);

  // Restart after a fatal error, or to pick up a status change right after cancelling.
  const restart = useCallback(() => setGeneration((n) => n + 1), []);
  return { snapshot, restart };
}
