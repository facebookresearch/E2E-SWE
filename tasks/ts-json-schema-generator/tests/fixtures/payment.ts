export interface CardPayment { kind: "card"; last4: string; }
export interface CashPayment { kind: "cash"; received: number; }
export interface WirePayment { kind: "wire"; iban: string; }
/**
 * @discriminator kind
 */
export type PaymentMethod = CardPayment | CashPayment | WirePayment;
