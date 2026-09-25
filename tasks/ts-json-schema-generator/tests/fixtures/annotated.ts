export interface Profile {
  /** @minimum 0 @maximum 120 */
  age: number;
  /** @format email */
  email: string;
  /** @pattern ^[A-Z]{3}$ */
  code: string;
}
