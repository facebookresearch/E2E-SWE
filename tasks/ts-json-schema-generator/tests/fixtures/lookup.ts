export interface Registry {
  counts: Record<string, number>;
  labels: { [key: string]: string };
}
