export interface HasId { id: string; }
export interface HasTime { createdAt: number; }
export type Entity = HasId & HasTime;
export interface Store { entity: Entity; }
