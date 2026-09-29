export type Segment = [start: number, end: number, ...labels: string[]];
export interface Path { name: string; seg: Segment; }
