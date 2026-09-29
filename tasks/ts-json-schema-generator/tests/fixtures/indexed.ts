export interface Book { title: string; meta: { pages: number; isbn: string }; }
export type BookMeta = Book["meta"];
export interface Shelf { m: BookMeta; }
