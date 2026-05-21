
import cv2
import os
import sys

def extract_frames(video_path):
    try:
        # Get the directory and filename from the video path
        video_dir, video_filename = os.path.split(video_path)
        video_name = os.path.splitext(video_filename)[0]
        
        # Create a directory to store the frames
        frames_dir = os.path.join(video_dir, f'{video_name}_frames')
        if not os.path.exists(frames_dir):
            os.makedirs(frames_dir)

        # Open the video file
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Error: Could not open video file {video_path}", file=sys.stderr)
            sys.exit(1)

        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Save the frame as a JPG file
            frame_filename = os.path.join(frames_dir, f"frame_{frame_count:04d}.jpg")
            cv2.imwrite(frame_filename, frame)
            frame_count += 1

        cap.release()

        # Print the path to the frames directory to stdout
        print(frames_dir)
        sys.exit(0)

    except Exception as e:
        print(f"Error extracting frames: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python frame_extractor.py <video_path>", file=sys.stderr)
        sys.exit(1)
    
    video_path = sys.argv[1]
    extract_frames(video_path)
