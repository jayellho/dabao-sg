import { NextResponse } from "next/server";

export async function POST() {
  const res = await fetch(
    `${process.env.ATG_INTERNAL_URL}/api/atg/scrape`,
    { method: "POST" }
  );

  const data = await res.json();
  return NextResponse.json(data);
}
