export interface Config { host: string; port: number; secure: boolean; }
export type ConfigKey = keyof Config;
export interface Ref { key: ConfigKey; }
