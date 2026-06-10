export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PROCESSOR_URL = (process.env.PROCESSOR_URL || "http://localhost:8000").replace(
  /\/$/,
  "",
);

export async function POST(request) {
  let body;

  try {
    body = await request.json();
  } catch {
    return Response.json(
      { status: "missing_fields", message: "empty feedback" },
      { status: 400 },
    );
  }

  let upstream;

  try {
    upstream = await fetch(`${PROCESSOR_URL}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    return Response.json(
      {
        status: "storage_error",
        message:
          error?.message ||
          `Could not reach processor at ${PROCESSOR_URL}. Start the Python backend or set PROCESSOR_URL.`,
      },
      { status: 502 },
    );
  }

  const data = await upstream.json().catch(() => ({
    status: "storage_error",
    message: "feedback to storage failure",
  }));

  return Response.json(data, { status: upstream.status });
}
