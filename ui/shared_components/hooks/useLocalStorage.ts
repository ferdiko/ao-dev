import { useState, useEffect } from "react";

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    const item = localStorage.getItem(key);
    if (!item) return initialValue;
    try {
      return JSON.parse(item);
    } catch {
      // If not JSON, return as string
      return item as unknown as T;
    }
  });

  useEffect(() => {
    if (typeof value === "string") {
      localStorage.setItem(key, value as string);
    } else {
      localStorage.setItem(key, JSON.stringify(value));
    }
  }, [key, value]);

  return [value, setValue] as const;
}