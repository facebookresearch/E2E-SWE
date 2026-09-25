export interface Secret { token: string; scope: string; expiresAt: number; }
export type SafeSecret = Omit<Secret, "token">;
export interface Vault { safe: SafeSecret; }
