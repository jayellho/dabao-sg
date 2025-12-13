import axios from 'axios';


const BACKEND_URL = process.env.BACKEND_URL; // e.g. "https://your-ec2-domain.com"
console.log(BACKEND_URL)
export const triggerAtgScrape = async () => {
  const response = await axios.post(`${BACKEND_URL}/api/atg/scrape`, {
    headless: true,
    max_orders: 200,
    sync_calendar: true,
  });
  return response.data;
};