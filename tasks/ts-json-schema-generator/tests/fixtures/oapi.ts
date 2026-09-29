export interface CardPay { kind: "card"; last4: string; }
export interface CashPay { kind: "cash"; amount: number; }
/**
 * @discriminator kind
 */
export type Pay = CardPay | CashPay;
