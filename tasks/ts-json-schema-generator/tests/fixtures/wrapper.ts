export interface Wrapper<T> { value: T; tag: string; }
export interface Holder {
  s: Wrapper<string>;
  n: Wrapper<number>;
}
