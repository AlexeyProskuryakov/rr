# coding=utf-8
import logging
from multiprocessing import Process
from time import sleep
from db import DBHandler
from engine import Retriever, reddit_get_new, get_current_step, to_save, update_posts
from properties import min_update_period, time_step_less_iteration_power, min_time_step, max_time_step

__author__ = 'alesha'

log = logging.getLogger("processes")


class SubredditProcessWorker(Process):
    def __init__(self, tq, rq, db):
        super(SubredditProcessWorker, self).__init__()
        self.tq = tq
        self.rq = rq
        self.db = db

        log.info("SPW inited...")

    def run(self):
        log.info("SPW will start...")
        while 1:
            task = self.tq.get()
            name = task.get("name")
            try:
                self.db.update_subreddit_info(name, {"error": "All ok"})
                subreddit = self.db.get_subreddit(name)
                if not subreddit:
                    log.error("not subreddit of this name %s", name)
                    raise Exception("not subreddit o name:%s" % name)

                try:
                    posts = reddit_get_new(name)
                    self.db.add_raw_posts(name, posts)
                    if not posts:
                        raise Exception("no posts :( ")
                except Exception as e:
                    self.db.update_subreddit_info(name, {"error": str(e)})
                    log.error("can not find any posts for %s" % name)
                    continue

                interested_posts = []
                interested_posts_ids = []

                params = subreddit.get("params")
                lrtime = params.get("lrtime")
                first_post_created = posts[-1].get("created_utc")
                # отсеиваем посты, те которые более новые и те виде_ид которые уже есть
                for post in reversed(posts):
                    created_time = post.get("created_utc")
                    if (created_time - first_post_created) < lrtime:
                        if not self.db.is_post_video_id_present(post.get("video_id")):
                            interested_posts.append(post)

                        interested_posts_ids.append(post.get("fullname"))
                    else:
                        break

                count = 0
                retriever = Retriever()
                for post in retriever.process_subreddit(interested_posts, params):
                    count += 1
                    self.db.save_post(post, "observation")

                log.info("SPW for %s retrieved: %s posts \n interested posts: (%s) \n added: %s" % (
                    name, len(posts), len(interested_posts), count))

                time_window = get_current_step(posts)
                self.db.update_subreddit_info(name, {"time_window": time_window,
                                                     "count_all_posts": len(posts),
                                                     "count_interested_posts": len(interested_posts),
                                                     "statistic": retriever.statistic,
                                                     "head_post_id": interested_posts_ids[0]})

                next_time_step = ensure_time_step(subreddit.get("head_post_id"),
                                                  first_post_created,
                                                  lrtime,
                                                  interested_posts_ids,
                                                  posts)

                log.info("SPW for %s next time step will be: %s" % (name, next_time_step))
                self.db.toggle_subreddit(name, next_time_step)

            except Exception as e:
                log.exception("exception with task for subreddit: {%s}\n%s", name, e)
                sleep(1)
                continue


def ensure_time_step(head_post_id, first_post_created, lrtime, interested_posts_ids, posts):
    # уменьшаем время следующей загрузки если идентификатор последнего поста в заданном
    # интервале выгрузки. Иначе увеличиваем
    next_time_step = lrtime
    if head_post_id in interested_posts_ids:
        # getting time = first_post <-> post with previous head_id
        for post in posts:
            if post.get("fullname") == head_post_id:
                time_to_increase = post.get("created_utc") - first_post_created
                next_time_step += time_to_increase
                break
    else:
        next_time_step -= next_time_step / 4

    # crop this time between min and max
    if next_time_step < min_time_step:
        next_time_step = min_time_step
    elif next_time_step > max_time_step:
        next_time_step = max_time_step

    return next_time_step


class SubredditUpdater(Process):
    def __init__(self, tq, db):
        super(SubredditUpdater, self).__init__()
        self.tq = tq
        self.db = db
        log.info("SU inited...")

    def run(self):
        log.info("SU will start...")
        while 1:
            subreddits = self.db.get_subreddits_to_process()
            if subreddits:
                log.info("this will be updates %s" % subreddits)
            for subreddit_to_process in subreddits:
                self.tq.put({"name": subreddit_to_process})
            sleep(120)


def update_stored_posts(db, posts):
    posts_fullnames = []
    subreddits = {}
    for post in posts:
        subreddit = post.get("subreddit")
        if subreddit not in subreddits:
            sbrdt = db.get_subreddit(subreddit)
            if sbrdt and sbrdt.get("params"):
                sbrdt_params = sbrdt.get("params")
                subreddits[subreddit] = sbrdt_params
        posts_fullnames.append(post.get("fullname"))

    posts = update_posts(posts_fullnames)

    for post in posts:
        sbrdt_params = subreddits.get(post.get("subreddit"))
        if sbrdt_params:
            retriever = Retriever()
            processed_post = retriever.process_post(post,
                                                    sbrdt_params.get("reposts_max"),
                                                    sbrdt_params.get("rate_min"),
                                                    sbrdt_params.get("rate_max"),
                                                    None)
            if processed_post:
                db.update_post(to_save(processed_post))
            else:
                db.delete_post(post.get("fullname"), post.get("video_id"))


class PostUpdater(Process):
    def __init__(self, db):
        super(PostUpdater, self).__init__()
        self.db = db

    def run(self):
        log.info("PU will start...")
        while 1:
            for_update = self.db.get_posts_for_update()
            count = for_update.count()
            if count > 0:
                log.info("will update %s posts...", count)
                update_stored_posts(self.db, for_update)
            sleep(min_update_period)


if __name__ == '__main__':
    db = DBHandler()
    pu = PostUpdater(db)
    pu.start()
