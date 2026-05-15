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
  transcripts: process.env.TRANSCRIPTS_BUCKET || "transcripts",
};
const OPENAI_TRANSCRIPTION_MODEL =
  process.env.OPENAI_TRANSCRIPTION_MODEL || "whisper-1";
const OPENAI_AUDIO_FILE_LIMIT_BYTES = 25 * 1024 * 1024;
const TRANSCRIPTION_LEAD_IN_SECONDS = 1;
const REPO_ROOT = path.resolve(process.cwd(), "..");
const UPLOADS_ROOT = path.join(REPO_ROOT, "tmp", "uploads");

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

async function createAudioWithLeadIn(sourcePath, outputPath) {
  await runFfmpeg(
    ffmpeg()
      .input(`anullsrc=channel_layout=mono:sample_rate=16000`)
      .inputOptions(["-f", "lavfi", "-t", String(TRANSCRIPTION_LEAD_IN_SECONDS)])
      .input(sourcePath)
      .complexFilter("[0:a][1:a]concat=n=2:v=0:a=1[outa]")
      .outputOptions(["-map", "[outa]"])
      .audioChannels(1)
      .audioFrequency(16000)
      .format("wav")
      .output(outputPath),
  );
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

async function transcribeAudioWithOpenAI(audioPath) {
  const apiKey = process.env.OPENAI_API_KEY;

  if (!apiKey) {
    throw new Error(
      "OpenAI transcription is not configured. Add OPENAI_API_KEY to frontend/.env.local.",
    );
  }

  const stats = await fs.promises.stat(audioPath);
  if (stats.size > OPENAI_AUDIO_FILE_LIMIT_BYTES) {
    throw new Error(
      "The extracted audio is larger than OpenAI's 25 MB transcription upload limit.",
    );
  }

  const audioBytes = await fs.promises.readFile(audioPath);
  const formData = new FormData();
  formData.append(
    "file",
    new Blob([audioBytes], { type: "audio/wav" }),
    "audio.wav",
  );
  formData.append("model", OPENAI_TRANSCRIPTION_MODEL);
  formData.append("response_format", "verbose_json");

  const response = await fetch("https://api.openai.com/v1/audio/transcriptions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
    },
    body: formData,
  });

  if (!response.ok) {
    const details = await response.text();
    throw new Error(`Failed to transcribe audio with OpenAI: ${details}`);
  }

  return response.json();
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
  const encoder = new TextEncoder();

  return new Response(
    new ReadableStream({
      async start(controller) {
        let jobDir;

        function send(event) {
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
        }

        try {
          send({ type: "progress", progress: 3, stage: "Reading request" });
          const { youtubeUrl } = await request.json();
          const videoId = parseYouTubeUrl(youtubeUrl);

          if (!videoId) {
            send({
              type: "error",
              message: "Paste a valid YouTube video URL.",
            });
            return;
          }

          const jobId = `${safeSegment(videoId)}-${Date.now()}`;
          const storagePrefix = `videos/${jobId}`;
          jobDir = path.join(UPLOADS_ROOT, jobId);
          const videoOutputTemplate = path.join(jobDir, "source.%(ext)s");
          const audioPath = path.join(jobDir, "audio.wav");
          const transcriptionAudioPath = path.join(
            jobDir,
            "audio-for-transcript.wav",
          );
          const transcriptPath = path.join(jobDir, "transcript.json");
          const framesDir = path.join(jobDir, "frames");

          send({ type: "progress", progress: 8, stage: "Preparing workspace" });
          fs.mkdirSync(framesDir, { recursive: true });

          send({ type: "progress", progress: 12, stage: "Preparing downloader" });
          const ytDlp = await getYtDlp();
          send({ type: "progress", progress: 18, stage: "Downloading video" });
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

          send({ type: "progress", progress: 35, stage: "Extracting audio" });
          await runFfmpeg(
            ffmpeg(videoPath)
              .noVideo()
              .audioChannels(1)
              .audioFrequency(16000)
              .format("wav")
              .output(audioPath),
          );

          send({
            type: "progress",
            progress: 43,
            stage: "Preparing audio for transcription",
          });
          await createAudioWithLeadIn(audioPath, transcriptionAudioPath);

          send({ type: "progress", progress: 50, stage: "Extracting frames" });
          await runFfmpeg(
            ffmpeg(videoPath)
              .outputOptions(["-vf", `fps=${ONE_FRAME_PER_SECOND}`, "-q:v", "2"])
              .output(path.join(framesDir, "frame_%05d.jpg")),
          );

          const framePaths = await listFiles(framesDir);
          const rawVideoStoragePath = `${storagePrefix}/raw/original${path.extname(videoPath) || ".mp4"}`;
          const audioStoragePath = `${storagePrefix}/audio/audio.wav`;
          const transcriptStoragePath = `${storagePrefix}/transcripts/transcript-und.json`;

          send({ type: "progress", progress: 62, stage: "Transcribing audio" });
          const transcript = await transcribeAudioWithOpenAI(
            transcriptionAudioPath,
          );
          transcript.source = {
            youtubeUrl: youtubeUrl.trim(),
            audioPath: audioStoragePath,
            transcriptionLeadInSeconds: TRANSCRIPTION_LEAD_IN_SECONDS,
          };
          await fs.promises.writeFile(
            transcriptPath,
            JSON.stringify(transcript, null, 2),
            "utf-8",
          );

          send({ type: "progress", progress: 78, stage: "Uploading raw video" });
          await uploadToSupabaseStorage({
            bucket: STORAGE_BUCKETS.rawVideos,
            storagePath: rawVideoStoragePath,
            localPath: videoPath,
            contentType: "video/mp4",
          });

          send({ type: "progress", progress: 86, stage: "Uploading audio" });
          await uploadToSupabaseStorage({
            bucket: STORAGE_BUCKETS.audio,
            storagePath: audioStoragePath,
            localPath: audioPath,
            contentType: "audio/wav",
          });

          send({ type: "progress", progress: 92, stage: "Uploading transcript" });
          await uploadToSupabaseStorage({
            bucket: STORAGE_BUCKETS.transcripts,
            storagePath: transcriptStoragePath,
            localPath: transcriptPath,
            contentType: "application/json",
          });

          send({ type: "progress", progress: 97, stage: "Cleaning temporary files" });
          await removeJobDirectory(jobDir);
          jobDir = null;

          send({
            type: "complete",
            progress: 100,
            stage: "Complete",
            result: {
              success: true,
              rawVideoPath: rawVideoStoragePath,
              audioPath: audioStoragePath,
              transcriptPath: transcriptStoragePath,
              transcriptText: transcript.text || "",
              buckets: STORAGE_BUCKETS,
              frameCount: framePaths.length,
              frameRate: ONE_FRAME_PER_SECOND,
              message:
                "YouTube video processed. Raw video, audio, and transcript were uploaded; local frames were deleted after processing.",
            },
          });
        } catch (error) {
          console.error("Error processing YouTube video:", error);
          send({
            type: "error",
            message: error?.message || "Failed to process YouTube video.",
          });
        } finally {
          if (jobDir) {
            await removeJobDirectory(jobDir);
          }
          controller.close();
        }
      },
    }),
    {
      headers: {
        "Cache-Control": "no-cache, no-transform",
        "Content-Type": "application/x-ndjson; charset=utf-8",
      },
    },
  );
}
