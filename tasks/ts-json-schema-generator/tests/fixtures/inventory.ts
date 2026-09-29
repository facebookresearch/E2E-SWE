export interface Item {
  sku: string;
  qty: number;
  note?: string;
}
export interface Inventory {
  warehouse: string;
  items: Item[];
  locked: boolean;
}
