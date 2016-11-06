__author__ = 'alesha'

from apiclient.discovery import build
from apiclient.errors import HttpError
import re

duration_reg = re.compile(u"PT((?P<hours>\d+)H)?((?P<minutes>\d+)M)?((?P<seconds>\d+)S)?")

DEVELOPER_KEY = "AIzaSyALPCgnpIM6KcJsilUsi1VxO5A7xgLujPQ"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
                developerKey=DEVELOPER_KEY)

to_seconds = lambda x: 3600 * int(x['hours'] or 0) + \
                       60 * int(x['minutes'] or 0) + \
                       int(x['seconds'] or 0)


def parse_time(duration_str):
    for d in duration_reg.finditer(duration_str):
        result = d.groupdict()
        result = dict(map(lambda x: (x[0], int(x[1]) if x[1] else None), result.items()))
        return result


def get_time(video_id):
    video_response = youtube.videos().list(
        id=video_id,
        part='contentDetails'
    ).execute()

    # Add each result to the list, and then display the list of matching videos.
    for video_result in video_response.get("items", []):
        duration_str = video_result["contentDetails"]["duration"]
        d = parse_time(duration_str)
        if d:
            return d
    return None


def get_video_info(video_id):
    video_response = youtube.videos().list(
        id=video_id,
        part='statistics,contentDetails'
    ).execute()
    for video_result in video_response.get("items", []):
        duration_str = video_result["contentDetails"]["duration"]
        statistic_data = video_result["statistics"]
        video_length = parse_time(duration_str)
        if video_length and statistic_data:
            return {"yt_comments": int(statistic_data.get('commentCount', 0)),
                    "yt_likes": int(statistic_data.get('likeCount', 0)),
                    "yt_dislikes": int(statistic_data.get('dislikeCount', 0)),
                    "yt_views": int(statistic_data.get('viewCount', 0)),
                    "yt_favorites": int(statistic_data.get('favoriteCount', 0)),
                    "video_length": to_seconds(video_length)
                    }

    return None


if __name__ == '__main__':
    result = get_video_info("9O5jf3CWTiA")
    print result
