from functools import partial
import logging
import properties
from youtube import parse_time, to_seconds

from datetime import datetime
import time

import praw
import re
import youtube




log = logging.getLogger("engine")

reddit = praw.Reddit(user_agent="foo")
reddit.login("4ikist", "sederfes", disable_warning=True)
log.info("reddit is connected")


def retrieve_video_id(url):
    rules = {"www.youtube.com": re.compile("v\=(?P<id>[-_a-zA-Z0-9]+)&?"),
             "youtu.be": re.compile("\.be\/(?P<id>[-_a-zA-Z0-9]+)")
             }
    for rule_name, rule_reg in rules.items():
        if rule_name in url:
            for res in rule_reg.findall(url):
                return res


def to_show(el):
    full_name = el.fullname
    result = el.__dict__
    result['fullname'] = full_name
    result["video_id"] = retrieve_video_id(el.url)
    return result


COUNT = 10000


def reddit_get_new(subreddit_name):
    result = []
    sbrdt = reddit.get_subreddit(subreddit_name)

    for el in sbrdt.get_new(limit=COUNT, count=COUNT):
        data = to_show(el)
        result.append(data)

    return result


def get_reposts_count(video_id):
    count = 0
    for _ in reddit.search("url:%s" % video_id):
        count += 1
    return count



def get_current_step(posts):
    dt = datetime.fromtimestamp(posts[0].get("created_utc")) - datetime.fromtimestamp(posts[-1].get("created_utc"))
    return dt.seconds





class Retriever(object):
    def __init__(self):
        self.statistics_cache = {"little_ups": 0, "little_time": 0, "big_reposts_count": 0, "not_video": 0, "big_ups": 0}
        self.bad_cache = set()

    def _add_statistic_inc(self,subreddit, post_id, name_param):
        self.bad_cache.add(post_id)
        stat = self.statistics_cache.get(subreddit)
        if not stat:
            stat = dict(**self.statistics_cache)

        param_val = stat.get(name_param, 0)
        if param_val is None:
            log.error("statistic param not found")
            return
        else:
            stat[name_param] = param_val + 1

        self.statistics_cache[subreddit] = stat


    def process_post(self, post, rp_max, ups_min, ups_max, time_min):
        if post.get("id") in self.bad_cache:
            return
        add_stat = partial(self._add_statistic_inc, post.get("subreddit").display_name, post.get("id"))
        ups_count = int(post.get("ups"))
        if ups_count > ups_min:
            if ups_count < ups_max:
                video_id = post.get("video_id")
                if video_id:
                    video_time = youtube.get_time(video_id)
                    if video_time and to_seconds(parse_time(time_min)) > to_seconds(video_time):
                        try:
                            repost_count = get_reposts_count(video_id)
                            if repost_count < rp_max:
                                post["time"] = video_time
                                post["reposts_count"] = repost_count
                                return post
                            else:
                                add_stat("big_reposts_count")
                        except Exception as e:
                            log.error(e)
                    else:
                        add_stat("little_time")
                else:
                    add_stat("not_video")
            else:
                add_stat("big_ups")
        else:
            add_stat("little_ups")

    def process_subreddit(self, posts, params):
        """
        The params is :
        time_min or None minimal time of video
        shift or 0 for shifting time posts will processed after shifted time
        last_update or 0 since this time will processed posts
        rate_min, _max min max ups
        reposts_max maximum reposts

        :param posts:
        :param params:
        :return:
        """
        time_min = params.get('time_min') or properties.default_time_min
        result_acc = set()
        if not posts:
            log.error("no posts")
            return

        for post in posts:
            create_time = post.get("created_utc")
            if create_time + params.get('shift', 0) < time.time() and create_time > params.get('last_update', 0):
                post = self.process_post(post,
                                    params.get('reposts_max', 0),
                                    params.get('rate_min', 0),
                                    params.get('rate_max', 99999),
                                    time_min)
                if post is not None:
                    post_id = post.get("id")
                    if post_id in result_acc:
                        continue

                    result_acc.add(post_id)
                    yield {"video_id": post.get("video_id"),
                           "video_url": post.get("url"),
                           "title": post.get("title"),
                           "ups": post.get("ups"),
                           "reddit_url": post.get("permalink"),
                           "subreddit": post.get("subreddit").display_name,
                           "fullname": post.get("fullname"),
                           "reposts_count": post.get("reposts_count"),
                           "created_utc": post.get("created_utc"),
                           "created_dt":datetime.fromtimestamp(post.get("created_utc")),

                           }



if __name__ == '__main__':
    pass

