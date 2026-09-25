export interface Dog { bark: boolean; }
export interface Cat { meow: boolean; }
export type Pet = Dog | Cat;
export interface Owner { pet: Pet; name: string; }
