import { NextResponse } from "next/server";
import path from "path";
import fs from "fs";
import os from "os";
import YTDlpWrap from "yt-dlp-wrap";
import ffmpeg from "fluent-ffmpeg";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ONE_FRAME_PER_SECOND = 1;

function getFfmpegPath() {
  const binaryName = os.platform() === "win32" ? "ffmpeg.exe" : "ffmpeg";
  return path.join(
    getFfmpegDirectory(),
    binaryName,
  );
}

function getFfmpegDirectory() {
  return path.join(
    process.cwd(),
    "node_modules",
    "@ffmpeg-installer",
    `${os.platform()}-${os.arch()}`,
  );
}

ffmpeg.setFfmpegPath(getFfmpegPath());

function parseYouTubeUrl(value) {
  if (!value || typeof value !== "string") {
    return null;
  }

  let url;
  try {
    url = new URL(value.trim());
  } catch {
    return null;
  }

  const host = url.hostname.replace(/^www\./, "");
  const isYouTubeHost =
    host === "youtube.com" ||
    host === "m.youtube.com" ||
    host === "music.youtube.com" ||
    host === "youtu.be";

  if (!isYouTubeHost) {
    return null;
  }

  if (host === "youtu.be") {
    return url.pathname.split("/").filter(Boolean)[0] || null;
  }

  if (url.pathname === "/watch") {
    return url.searchParams.get("v");
  }

  const [kind, id] = url.pathname.split("/").filter(Boolean);
  if (["embed", "shorts", "live"].includes(kind)) {
    return id || null;
  }

  return null;
}

function safeSegment(value) {
  return value.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function runFfmpeg(command) {
  return new Promise((resolve, reject) => {
    command.on("error", reject).on("end", resolve).run();
  });
}

async function getYtDlp() {
  const binaryName = os.platform() === "win32" ? "yt-dlp.exe" : "yt-dlp";
  const binaryPath = path.join(process.cwd(), ".cache", "yt-dlp", binaryName);

  if (!fs.existsSync(binaryPath)) {
    fs.mkdirSync(path.dirname(binaryPath), { recursive: true });
    await YTDlpWrap.downloadFromGithub(binaryPath);

    if (os.platform() !== "win32") {
      fs.chmodSync(binaryPath, 0o755);
    }
  }

  return new YTDlpWrap(binaryPath);
}

async function countFiles(directory) {
  const entries = await fs.promises.readdir(directory);
  return entries.length;
}

async function findDownloadedVideo(jobDir) {
  const entries = await fs.promises.readdir(jobDir);
  const videos = entries
    .filter((entry) => /\.(mp4|mkv|webm|mov)$/i.test(entry))
    .sort((a, b) => {
      const aLooksMerged = !/\.f\d+\./i.test(a);
      const bLooksMerged = !/\.f\d+\./i.test(b);

      if (aLooksMerged === bLooksMerged) {
        return a.localeCompare(b);
      }

      return aLooksMerged ? -1 : 1;
    })
    .map((entry) => path.join(jobDir, entry));

  if (videos.length === 0) {
    throw new Error("yt-dlp finished, but no downloaded video file was found.");
  }

  return videos[0];
}

export async function POST(request) {
  try {
    const { youtubeUrl } = await request.json();
    const videoId = parseYouTubeUrl(youtubeUrl);

    if (!videoId) {
      return NextResponse.json(
        { success: false, message: "Paste a valid YouTube video URL." },
        { status: 400 },
      );
    }

    const jobId = `${safeSegment(videoId)}-${Date.now()}`;
    const jobDir = path.join(process.cwd(), "..", "tmp", "uploads", jobId);
    const videoOutputTemplate = path.join(jobDir, "source.%(ext)s");
    const audioPath = path.join(jobDir, "audio.wav");
    const framesDir = path.join(jobDir, "frames");

    fs.mkdirSync(framesDir, { recursive: true });

    const ytDlp = await getYtDlp();
    await ytDlp.execPromise([
      youtubeUrl.trim(),
      "--no-playlist",
      "--ffmpeg-location",
      getFfmpegDirectory(),
      "-f",
      "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
      "--merge-output-format",
      "mp4",
      "-o",
      videoOutputTemplate,
    ]);

    const videoPath = await findDownloadedVideo(jobDir);

    await runFfmpeg(
      ffmpeg(videoPath)
        .noVideo()
        .audioChannels(1)
        .audioFrequency(16000)
        .format("wav")
        .output(audioPath),
    );

    await runFfmpeg(
      ffmpeg(videoPath)
        .outputOptions(["-vf", `fps=${ONE_FRAME_PER_SECOND}`, "-q:v", "2"])
        .output(path.join(framesDir, "frame_%05d.jpg")),
    );

    fs.unlinkSync(videoPath);

    const frameCount = await countFiles(framesDir);

    return NextResponse.json({
      success: true,
      audioPath,
      framesPath: framesDir,
      frameCount,
      frameRate: ONE_FRAME_PER_SECOND,
      message: "YouTube video processed successfully.",
    });
  } catch (error) {
    console.error("Error processing YouTube video:", error);
    return NextResponse.json(
      {
        success: false,
        message: error?.message || "Failed to process YouTube video.",
      },
      { status: 500 },
    );
  }
}
