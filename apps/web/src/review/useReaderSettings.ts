import { useState } from "react";
import {
  persistReaderSettings,
  readStoredReaderSettings,
  type ReaderSettings,
} from "./readerSettings";

export function useReaderSettings() {
  const [settings, setSettingsState] = useState<ReaderSettings>(readStoredReaderSettings);

  function setSettings(patch: Partial<ReaderSettings>) {
    setSettingsState((current) => {
      const next = { ...current, ...patch };
      persistReaderSettings(next);
      return next;
    });
  }

  return { settings, setSettings };
}
