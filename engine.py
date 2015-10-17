from copy import copy
from functools import partial
import logging
from multiprocessing import Queue, Process, JoinableQueue
from db import DBHandler
import properties
from youtube import parse_time, to_seconds

__author__ = 'alesha'
import praw
import re
import youtube

pp_stat_el = {"little_ups": 0, "little_time": 0, "big_reposts_count": 0, "not_video": 0}
pp_statistic = {}

log = logging.getLogger("engine")


def retrieve_video_id(url):
    rules = {"www.youtube.com": re.compile("v\=(?P<id>[-_a-zA-Z0-9]+)&?"),
             "youtu.be": re.compile("\.be\/(?P<id>[-_a-zA-Z0-9]+)")
             }
    for rule_name, rule_reg in rules.items():
        if rule_name in url:
            for res in rule_reg.findall(url):
                return res


def to_show(el):
    result = el.__dict__
    result["video_id"] = retrieve_video_id(el.url)
    return result


reddit = praw.Reddit(user_agent="foo")
reddit.login("4ikist", "sederfes", disable_warning=True)


def reddit_get_new(subreddit="video", limit=5, count=100, before=None, after=None):
    result = []
    for el in reddit.get_subreddit(subreddit).get_new(limit=limit,
                                                      count=count,
                                                      before=before,
                                                      after=after):
        data = to_show(el)
        result.append(data)
    return result


def get_reposts_count(video_id):
    count = 0
    for _ in reddit.search("url:%s" % video_id):
        count += 1
    return count


bad_cache = set()


def _add_statistic_inc(subreddit, post_id, name_param):
    bad_cache.add(post_id)
    stat = pp_statistic.get(subreddit)
    if not stat:
        stat = dict(**pp_stat_el)

    param_val = stat.get(name_param, None)
    if param_val is None:
        log.error("statistic param not found")
        return
    else:
        stat[name_param] = param_val + 1

    pp_statistic[subreddit] = stat


def process_post(post, rp_max, ups_min, time_min, ):
    if post.get("id") in bad_cache:
        return
    add_stat = partial(_add_statistic_inc, post.get("subreddit").display_name, post.get("id"))

    if ups_min > int(post.get("ups")):
        video_id = post.get("video_id")
        if video_id:
            video_time = youtube.get_time(video_id)
            if video_time and to_seconds(parse_time(time_min)) > to_seconds(video_time):
                try:
                    repost_count = get_reposts_count(video_id)
                    if repost_count < rp_max:
                        print(post.get("video_id"), post.get("full_name"), video_time, repost_count, post.get("title"))
                        post["time"] = video_time
                        post["reposts_count"] = repost_count
                        return post
                    else:
                        add_stat("big_reposts_count")
                except Exception as e:
                    log.exception(e)
            else:
                add_stat("little_time")
        else:
            add_stat("not_video")
    else:
        add_stat("little_ups")


class TaskRetrieve(object):
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.args = args
        self.result = []

    def __call__(self):
        log.info("will process: \n %s \n %s" % (self.args, self.kwargs))
        self.result = reddit_get_new(*self.args, **self.kwargs)
        return self.result

    def __repr__(self):
        return "TKW:{%s}\nTA:[%s]\nTResult len:%s" % (
            "; ".join(["%s:%s" % (k, v) for k, v in self.kwargs.items()]),
            ";".join([str(k) for k in self.args]),
            str(len(self.result))
        )


class RedditRetriever(Process):
    def __init__(self, task_queue, result_queue):
        super(RedditRetriever, self).__init__()
        self.tq = task_queue
        self.rq = result_queue
        self.log = properties.logger.getChild("RR")

    def run(self):
        while True:
            task = self.tq.get()
            log.info("get task: %s" % task)

            if task is None:
                self.log.info("MUST STOP")
                self.tq.task_done()
                break

            try:
                self.log.info("will execute task")
                task()
            except Exception as e:
                self.log.exception("AT TASK CALL! %s", e)

            self.log.info("task done...")
            self.tq.task_done()
            self.rq.put(task)


def process_subreddit(name, count, reposts_max, rate_min, time_min=None, shift=0):
    time_min = time_min or properties.default_time_min
    result_acc = set()

    rq = Queue(1)
    tq = JoinableQueue(1)
    rr = RedditRetriever(tq, rq)
    rr.start()
    before = None
    _old_phi = before
    _shift = shift

    _c = 0
    _a = 0

    while 1:
        tq.put(TaskRetrieve(**{"subreddit": name, "limit": _shift + count * 25, "before": before}))
        tq.join()
        result_task = rq.get()
        posts = result_task.result
        if not posts:
            log.warning("not posts...")
            tq.put(None)
            tq.join()
            break

        before = posts[-1].get("name")
        if _old_phi != before:
            _old_phi = before
        else:
            break

        for post in posts:
            if _c >= shift:
                post = process_post(post, reposts_max, rate_min, time_min)
                if post is not None:
                    post_id = post.get("id")
                    if post_id in result_acc:
                        continue
                    log.info("winner! : %s \n%s" % (post, _a))
                    result_acc.add(post_id)
                    _a += 1
                    yield post

            _c += 1

        if _a > count:
            tq.put(None)
            tq.join()
            break

        _shift += count * 25
        log.info("now shift is: %s" % _shift)


if __name__ == '__main__':
    db = DBHandler()
    for post in process_subreddit(name="funny",
                                  count=5,
                                  reposts_max=3,
                                  rate_min=5,
                                  shift=50):
        db.save_post(post)
