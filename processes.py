from datetime import timedelta
import logging
from multiprocessing import Process
from time import sleep
from engine import Retriever, reddit_get_new, get_current_step

__author__ = 'alesha'

log = logging.getLogger("processes")


class SubredditProcessWorker(Process):
    def __init__(self, tq, rq, db):
        super(SubredditProcessWorker, self).__init__()
        self.tq = tq
        self.rq = rq
        self.db = db
        self.retriever = Retriever()

    def run(self):
        while 1:
            try:
                task = self.tq.get()
                name = task.get("name")
                posts = reddit_get_new(name)
                subreddit = self.db.get_subreddit(name)
                if not subreddit:
                    print "PW: not params.. bad..."
                    raise Exception
                params = subreddit.get("params")
                # params['last_update'] = subreddit.get("last_update", 0) - timedelta(hours=10).total_seconds()
                for post in self.retriever.process_subreddit(posts, params):
                    self.db.save_post(post)

                step = get_current_step(posts)
                self.db.update_subreddit_info(name, {"time_window": step,
                                                     "count_all_posts": len(posts),
                                                     "statistics": self.retriever.statistics_cache[name]})
            except Exception as e:
                print "PW:", e
                sleep(1)
                continue


class WorkNotifier(Process):
    def __init__(self, tq, db):
        super(WorkNotifier, self).__init__()
        self.tq = tq
        self.db = db

    def run(self):
        while 1:
            subreddits = self.db.get_subreddits_to_process()
            log.info("this will be updates!:%s" % subreddits)
            for subreddit_to_process in subreddits:
                self.tq.put({"name": subreddit_to_process})
                self.db.toggle_subreddit(subreddit_to_process)
            sleep(120)
