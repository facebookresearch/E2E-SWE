export type Flags = { [K in "read" | "write" | "exec"]: boolean };
export interface Perms { user: string; flags: Flags; }
