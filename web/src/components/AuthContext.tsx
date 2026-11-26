import { createContext, useContext } from "react";
import type { AuthUser } from "../types";

export const AuthContext = createContext<AuthUser | null>(null);

export function useAuthUser(): AuthUser | null {
  return useContext(AuthContext);
}
