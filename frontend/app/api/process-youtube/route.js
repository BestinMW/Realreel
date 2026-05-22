export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PROCESSOR_URL = (process.env.PROCESSOR_URL || "http://localhost:8000").replace(
  /\/$/,
  "",
);

export async function POST(request) {
  let body;

  try {
    body = await request.text();
  } catch {
    return Response.json({ message: "Invalid request body." }, { status: 400 });
  }

  let upstream;

  try {
    upstream = await fetch(`${PROCESSOR_URL}/process-youtube`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch (error) {
    return Response.json(
      {
        message:
          error?.message ||
          `Could not reach processor at ${PROCESSOR_URL}. Start the Python backend or set PROCESSOR_URL.`,
      },
      { status: 502 },
    );
  }

  if (!upstream.ok && !upstream.body) {
    const details = await upstream.text();
    return Response.json(
      { message: details || "Processor request failed." },
      { status: upstream.status },
    );
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Cache-Control": "no-cache, no-transform",
      "Content-Type":
        upstream.headers.get("content-type") || "application/x-ndjson; charset=utf-8",
    },
  });
}
