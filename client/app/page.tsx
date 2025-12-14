'use client';

import { useState } from 'react';
import { Button, Flex, notification } from 'antd';
import { triggerAtgScrape } from '../endpoints';

const Home = () => {
  const [api, contextHolder] = notification.useNotification();
  const [loading, setLoading] = useState(false);

  const handleUpdateClick = async () => {
    const key = 'atg-scrape';

    setLoading(true);

    // 1) Show "processing" notification (stays until we update it)
    api.open({
      key,
      message: 'Processing catering updates…',
      description: 'We’re scraping AmericaToGo and updating your calendar.',
      duration: 0, // stays open until replaced/closed
    });

    try {
      const res = await triggerAtgScrape();

      // 2) Replace with "success" notification
      api.success({
        key,
        message: 'Catering update succeeded',
        description: `Scraped ${res?.orders_count ?? 0} orders successfully.`,
        duration: 4, // auto-closes after 4 seconds
      });
    } catch (error: any) {
      // 3) Replace with "failed" notification that REQUIRES manual close
      api.error({
        key,
        message: 'Catering update failed',
        description:
          error?.response?.data?.message ??
          error?.message ??
          'Something went wrong while scraping AmericaToGo.',
        duration: 0, // 🔴 stays until user clicks the X
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      {/* Required for notification.useNotification */}
      {contextHolder}
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center justify-between py-32 px-16 bg-white dark:bg-black sm:items-start">
        <Flex gap="small" wrap>
          <Button
            type="primary"
            loading={loading}
            onClick={handleUpdateClick}
          >
            Update Caterings
          </Button>
        </Flex>
      </main>
    </div>
  );
};

export default Home;
