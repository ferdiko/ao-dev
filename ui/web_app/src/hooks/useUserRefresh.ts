import { useEffect } from "react";
import { subscribe } from "../serverEvents";

export function useUserRefresh(refreshUser: () => void) {
  useEffect(() => {
    return subscribe("user_changed", () => {
      refreshUser();
    });
  }, [refreshUser]);
}
