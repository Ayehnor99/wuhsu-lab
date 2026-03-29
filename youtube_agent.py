import logging
import yt_dlp
import os
from typing import Any

logger = logging.getLogger("YouTubeAgent-Utility")

class YouTubeAgent:
    """
    A robust utility for searching YouTube videos.
    Supports both API-based search (with embeddability filtering) and yt-dlp fallback.
    """
    def search(self, query: str, max_results: int = 3, order: str = "relevance", safe_search: str = "moderate", category: str = None, **kwargs) -> list:
        logger.info(f"YOUTUBE_AGENT SEARCH CALLED! category: {category}, kwargs: {kwargs}")
        # Check for YouTube API Key in environment
        api_key = os.getenv("YOUTUBE_API_KEY")
        
        if api_key:
            try:
                from googleapiclient.discovery import build
                youtube = build("youtube", "v3", developerKey=api_key)
                
                params: dict[str, Any] = {
                    "part":       "id,snippet",
                    "q":          query,
                    "type":       "video",
                    "maxResults": min(50, max(1, max_results)),
                    "order":      order,
                    "safeSearch": safe_search,
                    "videoEmbeddable": "true",
                }
                
                logger.info(f"Searching YouTube (API) for: {query}")
                request = youtube.search().list(**params)
                response = request.execute()
                
                results = []
                for item in response.get("items", []):
                    results.append({
                        "video_id": item["id"]["videoId"],
                        "title": item["snippet"]["title"],
                        "channel_title": item["snippet"]["channelTitle"],
                        "duration": ""
                    })
                return results
                
            except Exception as e:
                logger.error(f"YouTube API error: {e}. Falling back to DDGS/yt-dlp.")

        # ==========================================
        # FALLBACK 1: DuckDuckGo Video Search (Anti-Bot Bypass)
        # ==========================================
        try:
            from duckduckgo_search import DDGS
            import re
            logger.info(f"Searching YouTube (via DuckDuckGo) for: {query}")
            
            with DDGS() as ddgs:
                ddg_results = list(ddgs.videos(f"site:youtube.com {query}", max_results=max_results + 2))
                
                results = []
                for r in ddg_results:
                    url = r.get("content", "")
                    vid_match = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
                    if vid_match:
                        results.append({
                            "video_id": vid_match.group(1),
                            "title": r.get("title", "YouTube Video"),
                            "channel_title": r.get("publisher", "YouTube"),
                            "duration": r.get("duration", "")
                        })
                        if len(results) >= max_results:
                            break
                            
                if results:
                    logger.info(f"Found {len(results)} videos via DuckDuckGo.")
                    return results
        except Exception as e:
            logger.warning(f"DuckDuckGo fallback failed: {e}. Proceeding to yt-dlp.")

        # ==========================================
        # FALLBACK 2: yt-dlp Search
        # ==========================================
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'force_generic_extractor': False,
            'noprogress': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'skip_download': True,
        }
        
        search_query = f"ytsearch{max_results}:{query}"
        results = []
        
        try:
            logger.info(f"Searching YouTube (via yt-dlp) for: {query}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                
                if not info or 'entries' not in info:
                    return []
                
                for entry in info['entries']:
                    if not entry:
                        continue
                    results.append({
                        "video_id": entry.get("id"),
                        "title": entry.get("title"),
                        "channel_title": entry.get("uploader") or "Unknown",
                        "duration": self._format_duration(entry.get("duration"))
                    })
                    if len(results) >= max_results:
                        break
            return results
        except Exception as e:
            logger.error(f"Error during yt-dlp search: {e}")
            return []

    def _format_duration(self, seconds: int) -> str:
        """Helper to format duration in seconds to MM:SS or HH:MM:SS."""
        if not seconds:
            return ""
        try:
            m, s = divmod(int(seconds), 60)
            h, m = divmod(m, 60)
            if h > 0:
                return f"{h:d}:{m:02d}:{s:02d}"
            return f"{m:d}:{s:02d}"
        except (ValueError, TypeError):
            return ""
