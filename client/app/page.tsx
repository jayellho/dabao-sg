'use client';

import React, { useState } from "react";
import { Button, Flex, message } from "antd";
import { triggerAtgScrape } from "../endpoints";

const Home = () => {
  const [loading, setLoading] = useState(false);

  const handleUpdateClick = async () => {
    const key = "atg-scrape"; // shared key so the message updates instead of stacking

    try {
      setLoading(true);

      // 1) Show "processing..." message (duration: 0 = persist until we replace it)
      message.loading({
        content: "Processing catering update...",
        key,
        duration: 0,
      });

      // 2) Call backend
      const res = await triggerAtgScrape();

      // 3) Show success
      message.success({
        key,
        content: `Success! Synced ${res?.orders_count ?? 0} orders.`,
        duration: 4,
      });

      console.log("ATG scrape result:", res);
    } catch (err: any) {
      console.error("ATG scrape failed:", err);

      // Try to extract a helpful error message
      const backendMessage =
        err?.response?.data?.message ||
        err?.message ||
        "Unknown error occurred";

      // 4) Show failure
      message.error({
        key,
        content: `Failed to update caterings: ${backendMessage}`,
        duration: 6,
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center justify-between py-32 px-16 bg-white dark:bg-black sm:items-start">
        <Flex gap="small" wrap>
          <Button
            type="primary"
            loading={loading}
            onClick={handleUpdateClick}
          >
            {loading ? "Updating..." : "Update Caterings"}
          </Button>
        </Flex>
      </main>
    </div>
  );
};

export default Home;
