// endpoints.ts
import axios from "axios";

export interface AtgScrapeResponse {
  ok: boolean;
  message: string;
  orders_count: number;
  order_ids: string[];
  saved_json?: string | null;
  saved_excel?: string | null;
  calendar_changes?: number | null;
}

export const triggerAtgScrape = async (): Promise<AtgScrapeResponse> => {
  const response = await axios.post("/api/atg/scrape", {
    headless: true,
    max_orders: 200,
    sync_calendar: true,
  });

  // Axios throws on non-2xx, so if we’re here it’s 2xx
  return response.data;
};
