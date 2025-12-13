import Image from "next/image";
import { Button, Flex } from 'antd';
import { triggerAtgScrape } from "../endpoints"


const Home = () => {

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center justify-between py-32 px-16 bg-white dark:bg-black sm:items-start">
        <Flex gap="small" wrap>
          <Button
            type="primary"
            onClick={async () => {
              const res = await triggerAtgScrape();
              console.log(res);
            }}
          >
            Update Caterings
          </Button>
        </Flex>
      </main>
    </div>
  );
}

export default Home;
