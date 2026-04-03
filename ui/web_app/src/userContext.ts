import { createContext, useContext } from "react";
import type { User } from "./userApi";

interface UserContextValue {
  user: User | null | undefined;
  refreshUser: () => void;
}

export const UserContext = createContext<UserContextValue>({
  user: undefined,
  refreshUser: () => {},
});

export function useUser() {
  return useContext(UserContext);
}
