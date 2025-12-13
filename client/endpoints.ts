import axios from 'axios';


export const getScrapeStatus = async () => {
  try {
    const result: any = [];
    const response = await axios.post('/api/atg/scrape');
    const { decoding } = await response.data;
    
    return result;
  } catch (error) {
    console.log(error);
    return [];
  }
};