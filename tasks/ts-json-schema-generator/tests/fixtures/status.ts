export enum Status { Draft = "draft", Live = "live", Archived = "archived" }
export interface Doc { id: string; status: Status; }
