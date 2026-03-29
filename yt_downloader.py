import os
import yt_dlp
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yt_downloader")

def download(url: str, output_dir: str = None, extra_opts: dict = None):
    """
    Downloads a YouTube video.
    If output_dir is provided, saves there. Otherwise defaults to ~/Downloads/YouTube.
    """
    if output_dir:
        download_path = output_dir
    else:
        download_path = os.path.expanduser("~/Downloads/YouTube")
        
    if not os.path.exists(download_path):
        os.makedirs(download_path, exist_ok=True)

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(str(download_path), '%(title)s.%(ext)s'),
        'noplaylist': True,
        'quiet': False,
        'no_warnings': False,
        'progress_hooks': [lambda d: logger.info(f"Downloading: {d.get('_percent_str', '0.0%')} of {d.get('_total_bytes_str', 'unknown')}")],
    }

    if extra_opts:
        ydl_opts.update(extra_opts)
        # Ensure outtmpl is re-applied if extra_opts didn't override it but we have a download_path
        if 'outtmpl' not in extra_opts:
            ydl_opts['outtmpl'] = os.path.join(str(download_path), '%(title)s.%(ext)s')

    try:
        logger.info(f"Starting download for: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        logger.info(f"Download completed successfully. Saved to {download_path}")
        return True
    except Exception as e:
        logger.error(f"Error during download: {e}")
        raise e

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        download(sys.argv[1])
    else:
        print("Usage: python yt_downloader.py [URL]")
