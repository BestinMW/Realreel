import { NextResponse } from "next/server";
import path from "path";
import fs from "fs";
import os from "os";
import YTDlpWrap from "yt-dlp-wrap";
import ffmpeg from "fluent-ffmpeg";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ONE_FRAME_PER_SECOND = 1;
const STORAGE_BUCKETS = {
  rawVideos: process.env.RAW_VIDEOS_BUCKET || "raw-videos",
  audio: process.env.AUDIO_BUCKET || "audio",
};

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

async function listFiles(directory) {
  const entries = await fs.promises.readdir(directory);
  return entries
    .filter((entry) => !entry.startsWith("."))
    .sort((a, b) => a.localeCompare(b))
    .map((entry) => path.join(directory, entry));
}

function getSupabaseConfig() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error(
      "Supabase storage is not configured. Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to frontend/.env.local.",
    );
  }

  return {
    supabaseUrl: supabaseUrl.replace(/\/$/, ""),
    serviceRoleKey,
  };
}

async function uploadToSupabaseStorage({
  bucket,
  storagePath,
  localPath,
  contentType,
}) {
  const { supabaseUrl, serviceRoleKey } = getSupabaseConfig();
  const stats = await fs.promises.stat(localPath);
  const uploadUrl = `${supabaseUrl}/storage/v1/object/${bucket}/${storagePath
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;

  const response = await fetch(uploadUrl, {
    method: "POST",
    headers: {
      apikey: serviceRoleKey,
      Authorization: `Bearer ${serviceRoleKey}`,
      "Content-Type": contentType,
      "Content-Length": String(stats.size),
      "x-upsert": "true",
    },
    body: fs.createReadStream(localPath),
    duplex: "half",
  });

  if (!response.ok) {
    const details = await response.text();
    throw new Error(
      `Failed to upload ${storagePath} to Supabase Storage: ${details}`,
    );
  }

  return storagePath;
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

async function removeJobDirectory(jobDir) {
  await fs.promises.rm(jobDir, { recursive: true, force: true });
}

export async function POST(request) {
  let jobDir;

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
    const storagePrefix = `videos/${jobId}`;
    jobDir = path.join(process.cwd(), "..", "tmp", "uploads", jobId);
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

    const framePaths = await listFiles(framesDir);
    const rawVideoStoragePath = `${storagePrefix}/raw/original${path.extname(videoPath) || ".mp4"}`;
    const audioStoragePath = `${storagePrefix}/audio/audio.wav`;

    await uploadToSupabaseStorage({
      bucket: STORAGE_BUCKETS.rawVideos,
      storagePath: rawVideoStoragePath,
      localPath: videoPath,
      contentType: "video/mp4",
    });

    await uploadToSupabaseStorage({
      bucket: STORAGE_BUCKETS.audio,
      storagePath: audioStoragePath,
      localPath: audioPath,
      contentType: "audio/wav",
    });

    await removeJobDirectory(jobDir);
    jobDir = null;

    return NextResponse.json({
      success: true,
      rawVideoPath: rawVideoStoragePath,
      audioPath: audioStoragePath,
      buckets: STORAGE_BUCKETS,
      frameCount: framePaths.length,
      frameRate: ONE_FRAME_PER_SECOND,
      message:
        "YouTube video processed. Raw video and audio were uploaded; local frames were deleted after processing.",
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
  } finally {
    if (jobDir) {
      await removeJobDirectory(jobDir);
    }
  }
}
