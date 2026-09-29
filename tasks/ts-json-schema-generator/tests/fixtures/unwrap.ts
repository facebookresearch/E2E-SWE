export type Unwrap<T> = T extends Promise<infer U> ? U : T;
export interface Box { a: Unwrap<Promise<number>>; b: Unwrap<string>; }
