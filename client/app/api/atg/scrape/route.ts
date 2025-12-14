// app/api/atg/scrape/route.ts
import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));

  const upstream = await fetch(`${process.env.ATG_INTERNAL_URL}/api/atg/scrape`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    // optional: avoid caching surprises
    cache: "no-store",
  });

  const text = await upstream.text();

  // pass through status + body
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
