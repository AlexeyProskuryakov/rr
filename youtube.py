__author__ = 'alesha'

from apiclient.discovery import build
from apiclient.errors import HttpError
import re

duration_reg = re.compile(u"PT((?P<hours>\d+)H)?((?P<minutes>\d+)M)?((?P<seconds>\d+)S)?")


# Set DEVELOPER_KEY to the API key value from the APIs & auth > Registered apps
# tab of
#   https://cloud.google.com/console
# Please ensure that you have enabled the YouTube Data API for your project.
DEVELOPER_KEY = "AIzaSyCYF4GPkVpdYjZ5RpDaSMcbpRpfkavnUzc"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

to_seconds = lambda x: 3600 * int(x['hours'] or 0) + \
                       60 * int(x['minutes'] or 0) + \
                       int(x['seconds'] or 0)

def parse_time(duration_str):
    for d in duration_reg.finditer(duration_str):
        result = d.groupdict()
        result = dict(map(lambda x: (x[0], int(x[1]) if x[1] else None), result.items()))
        return result


def get_time(video_id):
    youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
                    developerKey=DEVELOPER_KEY)

    # Call the videos.list method to retrieve location details for each video.
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

