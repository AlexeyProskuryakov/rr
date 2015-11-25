from functools import partial
import logging
from datetime import datetime
import time
import re
import praw
import properties
from youtube import parse_time, to_seconds
import youtube

log = logging.getLogger("engine")

reddit = praw.Reddit(user_agent="foo")
reddit.login("4ikist", "sederfes", disable_warning=True)
log.info("reddit is connected")


def get_interested_fields(source, fields):
    result = {}
    for field in fields:
        result[field] = source.get(field)
    return result


def retrieve_video_id(url):
    rules = {"www.youtube.com": re.compile("v\=(?P<id>[-_a-zA-Z0-9]+)&?"),
             "youtu.be": re.compile("\.be\/(?P<id>[-_a-zA-Z0-9]+)")
             }
    for rule_name, rule_reg in rules.items():
        if rule_name in url:
            for res in rule_reg.findall(url):
                return res


COUNT = 10000


def to_show(el):
    full_name = el.fullname
    result = el.__dict__
    result['fullname'] = full_name
    result["video_id"] = retrieve_video_id(el.url)
    result["created_utc"] = el.created_utc
    result["subreddit"] = el.subreddit.display_name
    result["ups"] = el.ups
    return result


def to_save(post):
    return {"video_id": post.get("video_id"),
            "video_url": post.get("url") or post.get("video_url"),
            "title": post.get("title"),
            "ups": post.get("ups"),
            "reddit_url": post.get("permalink") or post.get("reddit_url") or "http://reddit.com/"+post.get("fullname"),
            "subreddit": post.get("subreddit"),
            "fullname": post.get("fullname"),
            "reposts_count": post.get("reposts_count"),
            "created_dt": datetime.fromtimestamp(post.get("created_utc")),
            "created_utc": post.get("created_utc"),
            "comments_count": post.get("num_comments")
            }


def net_tryings(fn):
    def wrapped(*args, **kwargs):
        count = 0
        while 1:
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                log.exception(e)
                log.warning("can not load data for [%s]\n args: %s, kwargs: %s \n because %s" % (fn, args, kwargs, e))
                if count >= properties.tryings_count:
                    raise e
                time.sleep(properties.step_time_after_trying)
                count += 1

    return wrapped


@net_tryings
def reddit_get_new(subreddit_name):
    result = []
    sbrdt = reddit.get_subreddit(subreddit_name)
    for el in sbrdt.get_new(limit=COUNT, count=COUNT):
        data = to_show(el)
        result.append(data)
    return result


@net_tryings
def get_reposts_count(video_id):
    count = 0
    for _ in reddit.search("url:\'%s\'" % video_id):
        count += 1
    return count


@net_tryings
def reddit_search(query):
    result = []
    for post in reddit.search(query, limit=COUNT, count=COUNT):
        post_info = to_save(to_show(post))
        post_info.pop("reposts_count")
        result.append(post_info)
    return result


@net_tryings
def update_post(full_name):
    information = reddit.get_info(thing_id=full_name)
    if isinstance(information, list):
        return map(to_show, information)
    if information:
        return to_show(information)
    return None


def get_current_step(posts):
    dt = datetime.fromtimestamp(posts[0].get("created_utc")) - datetime.fromtimestamp(posts[-1].get("created_utc"))
    return dt.seconds


def update_posts(fullnames):
    names = []
    for name in fullnames:
        if name.startswith("t1") or name.startswith("t3") or name.startswith("t5"):
            names.append(name)
    return update_post(fullnames)


class Retriever(object):
    def __init__(self, stat=None):
        self.sbrdt_statistic = stat or {}

    def _add_statistic_inc(self, name_subreddit, name_param):
        param_val = self.sbrdt_statistic.get(name_param, 0)
        self.sbrdt_statistic[name_param] = param_val + 1

    def process_post(self, post, rp_max, ups_min, ups_max, time_min):
        add_stat = partial(self._add_statistic_inc, post.get("subreddit"))
        ups_count = int(post.get("ups"))
        if ups_count >= ups_min:
            if ups_count <= ups_max:
                video_id = post.get("video_id")
                if video_id:
                    if time_min and to_seconds(parse_time(time_min)):
                        time_min_seconds = to_seconds(parse_time(time_min))
                        video_time = youtube.get_time(video_id)
                        if video_time and to_seconds(video_time) > time_min_seconds:
                            post["time"] = video_time
                        else:
                            add_stat("little_time")
                            return

                    try:
                        repost_count = get_reposts_count(video_id)
                        if repost_count <= rp_max:
                            post["reposts_count"] = repost_count
                            return post
                        else:
                            add_stat("big_reposts_count")
                    except Exception as e:
                        log.error(e)

                else:
                    add_stat("not_video")
            else:
                add_stat("big_ups")
        else:
            add_stat("little_ups")

    @property
    def statistic(self):
        """
        :return: statistic for current process subreddit. You must get tis every time
        after using process subreddit/
        """
        return self.sbrdt_statistic

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
        time_min = params.get('time_min', None) or properties.default_time_min
        if not posts:
            log.error("no posts")
            return

        for post in posts:
            post = self.process_post(post,
                                     params.get('reposts_max'),
                                     params.get('rate_min'),
                                     params.get('rate_max'),
                                     time_min)
            if post is not None:
                yield to_save(post)


if __name__ == '__main__':
    result = update_post(["t3_3p5q1r", "t3_3p69uw"])
    print result
