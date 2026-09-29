export interface Full { a: number; b: string; c: boolean; }
export type MaybeFull = Partial<Full>;
export interface Wrap { data: MaybeFull; }
