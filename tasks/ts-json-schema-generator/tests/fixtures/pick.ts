export interface Member { id: string; handle: string; joined: number; }
export type PublicMember = Pick<Member, "handle" | "joined">;
export interface Directory { entry: PublicMember; }
