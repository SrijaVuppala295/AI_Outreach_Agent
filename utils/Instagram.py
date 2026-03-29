# Instagram.py - Enhanced with Rate Limiting Integration
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

# Import rate limiter
try:
    from utils.rate_limiter import track_instagram_profile, track_instagram_reels
    RATE_LIMITING_ENABLED = True
except ImportError:
    print("Warning: Rate limiter not available, running without rate limits")
    RATE_LIMITING_ENABLED = False
    def track_instagram_profile(): return True
    def track_instagram_reels(count): return True

load_dotenv()

class InstagramScraper:
    PAGE_ID     = os.getenv("META_PAGE_ID")
    PAGE_TOKEN  = os.getenv("META_TOKEN")
    APP_ID      = os.getenv("META_APP_ID")
    APP_SECRET  = os.getenv("META_APP_SECRET")
    API_VERSION = "v23.0"

    def __init__(self):
        if not self.PAGE_TOKEN or not self.APP_ID or not self.APP_SECRET:
            raise RuntimeError("META_TOKEN, APP_ID, and APP_SECRET must be set in the environment")

    def is_token_valid(self) -> bool:
        url = f"https://graph.facebook.com/{self.API_VERSION}/debug_token"
        params = {
            "input_token":  self.PAGE_TOKEN,
            "access_token": f"{self.APP_ID}|{self.APP_SECRET}"
        }
        resp = requests.get(url, params=params)
        try:
            resp.raise_for_status()
            return resp.json().get("data", {}).get("is_valid", False)
        except requests.exceptions.HTTPError:
            return False

    def _get_business_account_id(self) -> str | None:
        url = f"https://graph.facebook.com/{self.API_VERSION}/{self.PAGE_ID}"
        params = {
            "fields":       "instagram_business_account",
            "access_token": self.PAGE_TOKEN
        }
        resp = requests.get(url, params=params)
        try:
            resp.raise_for_status()
            return resp.json()["instagram_business_account"]["id"]
        except Exception:
            return None

    def get_profile_info(self, username: str) -> dict | None:
        """Get Instagram profile information with rate limiting"""
        # Check rate limit
        if RATE_LIMITING_ENABLED:
            if not track_instagram_profile():
                raise Exception("Instagram profile scraping rate limit exceeded (500/day)")
        
        biz_id = self._get_business_account_id()
        if not biz_id:
            return None

        url = f"https://graph.facebook.com/{self.API_VERSION}/{biz_id}"
        fields = (
            f"business_discovery.username({username})"
            "{id,username,name,biography,followers_count,follows_count,"
            "profile_picture_url,website,media_count}"
        )
        resp = requests.get(url, params={
            "fields":        fields,
            "access_token":  self.PAGE_TOKEN
        })
        try:
            resp.raise_for_status()
            bd = resp.json()["business_discovery"]
            return {
                "user_id":             bd["id"],
                "username":            bd["username"],
                "full_name":           bd["name"],
                "biography":           bd["biography"],
                "followers_count":     bd["followers_count"],
                "following_count":     bd["follows_count"],
                "profile_picture_url": bd["profile_picture_url"],
                "external_url":        bd.get("website"),
                "media_count":         bd.get("media_count", 0),
            }
        except Exception as e:
            print(f"Error fetching profile for {username}: {e}")
            return None

    def get_reels_metadata(self, username: str, limit: int = 10) -> list[dict]:
        """Get Instagram reels metadata with rate limiting"""
        # Check rate limit
        if RATE_LIMITING_ENABLED:
            if not track_instagram_reels(limit):
                raise Exception(f"Instagram reels scraping rate limit exceeded (requested {limit} reels)")
        
        biz_id = self._get_business_account_id()
        if not biz_id:
            return []

        fetch_count = limit * 3  # Fetch extra to filter for reels
        url = f"https://graph.facebook.com/{self.API_VERSION}/{biz_id}"
        fields = (
            f"business_discovery.username({username})"
            "{media.limit(" + str(fetch_count) + "){"
            "media_type,permalink,timestamp,caption,"
            "like_count,comments_count,video_view_count,play_count,plays"
            "}}"
        )
        resp = requests.get(url, params={
            "fields":        fields,
            "access_token":  self.PAGE_TOKEN
        })
        try:
            resp.raise_for_status()
            items = (resp.json()
                        .get("business_discovery", {})
                        .get("media", {})
                        .get("data", []))
        except Exception as e:
            print(f"Error fetching reels for {username}: {e}")
            return []

        reels = []
        for item in items:
            if item.get("media_type") not in ("VIDEO", "REELS"):
                continue
            ts = item.get("timestamp")
            if ts:
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00")) \
                                 .strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass
            likes    = item.get("like_count", 0)
            comments = item.get("comments_count", 0)
            views    = (
                item.get("video_view_count")
                or item.get("play_count")
                or item.get("plays")
                or likes * 15  # Estimate if not available
            )
            caption  = item.get("caption") or ""
            hashtags = [w[1:] for w in caption.split() if w.startswith("#")]

            reels.append({
                "id":               item.get("id"),
                "caption":          caption,
                "timestamp":        ts,
                "likes_count":      likes,
                "comments_count":   comments,
                "video_view_count": views,
                "permalink":        item.get("permalink"),
                "hashtags":         hashtags,
                "mentioned_users":  []
            })
            if len(reels) >= limit:
                break

        return reels

    def generate_insights(self, profile_info: dict, reels_data: list[dict]) -> dict:
        """Generate engagement insights from profile and reels data"""
        if not profile_info:
            return {"error": "No profile data"}

        total = len(reels_data)
        if total == 0:
            return {
                "total_reels_analyzed": 0,
                "engagement_metrics": {
                    "total_likes": 0,
                    "total_comments": 0,
                    "total_views": 0,
                    "avg_likes_per_reel": 0,
                    "avg_comments_per_reel": 0,
                    "avg_views_per_reel": 0,
                    "engagement_rate_percentage": 0
                },
                "content_insights": {
                    "top_hashtags": [],
                    "avg_reels_per_unique_day": 0
                },
                "audience_size": {
                    "followers": profile_info.get("followers_count", 0),
                    "following": profile_info.get("following_count", 0)
                }
            }

        likes    = sum(r["likes_count"] for r in reels_data)
        comments = sum(r["comments_count"] for r in reels_data)
        views    = sum(r["video_view_count"] for r in reels_data)

        avg_l = round(likes / total, 2)
        avg_c = round(comments / total, 2)
        avg_v = round(views / total, 2)

        followers = profile_info.get("followers_count", 0)
        rate = (
            round(((likes + comments) / total) / followers * 100, 2)
            if total and followers else 0
        )

        # Get top hashtags
        tags = [tag for r in reels_data for tag in r["hashtags"]]
        from collections import Counter
        tag_counts = Counter(tags)
        top_tags = [tag for tag, count in tag_counts.most_common(5)]

        # Calculate posting frequency
        dates = []
        for r in reels_data:
            if r.get("timestamp"):
                try:
                    date = datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S").date()
                    dates.append(date)
                except:
                    pass
        
        unique_dates = len(set(dates)) if dates else 1
        freq = round(total / unique_dates, 2) if unique_dates > 0 else 0

        return {
            "total_reels_analyzed": total,
            "engagement_metrics": {
                "total_likes": likes,
                "total_comments": comments,
                "total_views": views,
                "avg_likes_per_reel": avg_l,
                "avg_comments_per_reel": avg_c,
                "avg_views_per_reel": avg_v,
                "engagement_rate_percentage": rate
            },
            "content_insights": {
                "top_hashtags": top_tags,
                "avg_reels_per_unique_day": freq
            },
            "audience_size": {
                "followers": followers,
                "following": profile_info.get("following_count", 0)
            }
        }


def test_scraper():
    """Test function to verify the scraper works"""
    scraper = InstagramScraper()
    print("Token valid?", scraper.is_token_valid())
    
    username = "mrbeast"
    print(f"\nTesting with @{username}:")
    
    profile = scraper.get_profile_info(username)
    print(f"Profile: {profile}")
    
    reels = scraper.get_reels_metadata(username, limit=10)
    print(f"Reels: {len(reels) if reels else 0}")
    
    insights = scraper.generate_insights(profile, reels)
    print(f"Insights: {insights}")


if __name__ == "__main__":
    test_scraper()
