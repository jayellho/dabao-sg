import axios from 'axios';


export const triggerAtgScrape = async () => {
  const response = await axios.post("/api/atg/scrape", {
    headless: true,
    max_orders: 200,
    sync_calendar: true,
  });
  return response.data;
};