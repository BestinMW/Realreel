
import { NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import YTDlpWrap from 'yt-dlp-wrap';
import ffmpeg from 'fluent-ffmpeg';
import ffmpegPath from '@ffmpeg-installer/ffmpeg';

ffmpeg.setFfmpegPath(ffmpegPath.path);

const Dlp = new YTDlpWrap();

export async function POST(request) {
  const { youtubeUrl } = await request.json();

  // 1. Validate YouTube URL
  const youtubeRegex = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+$/;
  if (!youtubeUrl || !youtubeRegex.test(youtubeUrl)) {
    return NextResponse.json({ success: false, message: 'Invalid YouTube URL provided.' }, { status: 400 });
  }

  const uploadsDir = path.join(process.cwd(), '..', 'tmp', 'uploads');
  if (!fs.existsSync(uploadsDir)) {
    fs.mkdirSync(uploadsDir, { recursive: true });
  }

  try {
    // 2. Download YouTube video using yt-dlp
    // YouTube processing starts here
    const videoId = new URL(youtubeUrl).searchParams.get('v') || youtubeUrl.split('/').pop();
    const rawAudioPath = path.join(uploadsDir, `${videoId}_raw.mp3`);
    
    await Dlp.execPromise([
        youtubeUrl,
        '-x',
        '--audio-format', 'mp3',
        '-o', rawAudioPath,
    ]);

    // 3. Convert to WAV using ffmpeg
    const convertedFilePath = path.join(uploadsDir, `${videoId}.wav`);
    await new Promise((resolve, reject) => {
      ffmpeg(rawAudioPath)
        .toFormat('wav')
        .on('error', (err) => reject(err))
        .on('end', () => resolve())
        .save(convertedFilePath);
    });

    // Clean up the raw downloaded file
    fs.unlinkSync(rawAudioPath);
    // YouTube processing ends here, converted output is saved

    // 4. Return the path to the converted file
    return NextResponse.json({
      success: true,
      filePath: convertedFilePath,
      message: 'YouTube video processed successfully.',
    });

  } catch (error) {
    console.error('Error processing YouTube video:', error);
    return NextResponse.json({ success: false, message: 'Failed to process YouTube video.', error: error.message }, { status: 500 });
  }
}
