import logging
from multiprocessing import Process
from time import sleep
from db import DBHandler
from engine import Retriever, reddit_get_new, get_current_step, to_save
from properties import min_update_period, time_step_less_iteration_power

__author__ = 'alesha'

log = logging.getLogger("processes")


class SubredditProcessWorker(Process):
    def __init__(self, tq, rq, db):
        super(SubredditProcessWorker, self).__init__()
        self.tq = tq
        self.rq = rq
        self.db = db
        self.retriever = Retriever()
        log.info("SPW inited...")

    def run(self):
        log.info("SPW will start...")
        while 1:
            try:
                task = self.tq.get()
                name = task.get("name")
                subreddit = self.db.get_subreddit(name)
                if not subreddit:
                    log.error("not subreddit of this name %s", name)
                    raise Exception("not subreddit o name:%s" % name)

                posts = reddit_get_new(name)

                # if part of loaded posts was persisted we skip this part
                interested_posts = []
                for post in posts:
                    subreddit_head_id = subreddit.get("head_post_id")
                    if subreddit_head_id and post.get("fullname") == subreddit_head_id:
                        break

                    if not self.db.is_post_video_id_is_present(post.get("video_id")):
                        interested_posts.append(post)

                params = subreddit.get("params")
                for post in self.retriever.process_subreddit(interested_posts, params):
                    self.db.save_post(post)

                time_window = get_current_step(posts)
                self.db.update_subreddit_info(name, {"time_window": time_window,
                                                     "count_all_posts": len(posts),
                                                     "statistics": self.retriever.statistics_cache[name],
                                                     "head_post_id": posts[0].get("fullname")})

                next_time_step = self.ensure_time_step(subreddit, posts, interested_posts)
                self.db.toggle_subreddit(name, next_time_step=next_time_step)
            except Exception as e:
                log.exception(e)
                sleep(1)
                continue

    def ensure_time_step(self, subreddit, posts, interested_posts):
        name = subreddit.get("name")
        time_step = subreddit.get("time_step")
        len_posts, len_interested_posts = float(len(posts)), float(len(interested_posts))
        if len_posts == len_interested_posts:
            next_time_step = float(time_step) * time_step_less_iteration_power
        else:
            next_time_step = float(time_step) / (len_posts / len_interested_posts)
        log.info("for subreddit [%s] next time step is: %s second\nprevious time step is: %s" % (
            name, next_time_step, time_step))
        return next_time_step


class SubredditUpdater(Process):
    def __init__(self, tq, db):
        super(SubredditUpdater, self).__init__()
        self.tq = tq
        self.db = db
        log.info("WN inited...")

    def run(self):
        log.info("WN will start...")
        while 1:
            subreddits = self.db.get_subreddits_to_process()
            if subreddits:
                log.info("this will be updates %s" % subreddits)
            for subreddit_to_process in subreddits:
                self.tq.put({"name": subreddit_to_process})
            sleep(120)


class PostUpdater(Process):
    def __init__(self, db):
        super(PostUpdater, self).__init__()
        self.db = db
        self.retriever = Retriever()

    def run(self):
        log.info("PU will start...")
        while 1:
            subreddits = {}
            for_update = self.db.get_posts_for_update()
            log.info("will update %s posts...", for_update.count())
            posts_fullnames = []
            if for_update.count() > 0:
                for post in for_update:
                    subreddit = post.get("subreddit")
                    if subreddit not in subreddits:
                        sbrdt = self.db.get_subreddit(subreddit)
                        sbrdt_params = sbrdt.get("params")
                        if sbrdt and sbrdt_params:
                            subreddits[subreddit] = sbrdt_params
                    posts_fullnames.append(post.get("fullname"))

                posts = self.retriever.update_posts(posts_fullnames)
                for post in posts:
                    sbrdt_params = subreddits.get(post.get("subreddit"))
                    processed_post = self.retriever.process_post(post,
                                                                 sbrdt_params.get("reposts_max"),
                                                                 sbrdt_params.get("rate_min"),
                                                                 sbrdt_params.get("rate_max"),
                                                                 None)
                    if processed_post:
                        self.db.update_post(to_save(processed_post))
                    else:
                        self.db.delete_post(post.get("fullname"), post.get("video_id"))
            sleep(min_update_period)


if __name__ == '__main__':
    db = DBHandler()
    pu = PostUpdater(db)
    pu.start()
