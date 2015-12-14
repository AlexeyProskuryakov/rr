import logging
import traceback
from collections import defaultdict
from datetime import datetime
import time
import random
from multiprocessing import Lock
from threading import Thread

import praw
from praw.objects import MoreComments

from wsgi import properties
from wsgi.db import DBHandler

MIN_COPY_COUNT = 10

log = properties.logger.getChild("reddit-bot")

A_POST = "post"
A_VOTE = "vote"
A_COMMENT = "comment"

min_copy_count = 2
min_comment_create_time_difference = 3600 * 24 * 60
min_redditor_time_disable = 3600 * 24 * 7
min_comment_ups = 0
max_comment_ups = 100000
min_comments_at_post = 10


class ActionsHandler(object):
    def __init__(self):
        self.last_actions = {
            A_POST: datetime.utcnow(),
            A_VOTE: datetime.utcnow(),
            A_COMMENT: datetime.utcnow(),
        }
        self.acted = defaultdict(set)

    def set_action(self, action_name, identity):
        self.last_actions[action_name] = datetime.utcnow()
        self.acted[action_name].add(identity)

    def get_last_action(self, action_name):
        res = self.last_actions.get(action_name)
        if not res:
            raise Exception("Action %s is not supported")
        return res

    def is_acted(self, action_name, identity):
        return identity in self.acted[action_name]


def _so_long(created, min_time):
    (datetime.utcnow() - datetime.fromtimestamp(created)).total_seconds() > min_time


db = DBHandler()


class RedditBot(object):
    def __init__(self, login, password):
        self.reddit = praw.Reddit(
            user_agent="Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36")
        self.reddit.login(login, password=password, disable_warning=True)
        log.info("bot [%s] connected" % login)
        self.last_actions = ActionsHandler()
        self.comment_authors = set()

        self.s_c_s = 0 #count search requests
        self.s_c_rs = 0 #count requests for random subreddit
        self.s_c_aovv = 1 #count requests for author overview
        self.mutex = Lock()

    def return_stats(self):
        self.mutex.acquire()
        stat = {"search": self.s_c_s, "random_subreddit": self.s_c_rs, "author_overview": self.s_c_aovv}
        log.info("return stat: %s" % stat)
        self.mutex.release()
        return stat

    def _get_post_copies(self, post):
        copies = self.reddit.search("url:'/%s'/" % post.url)
        self.s_c_s += 1
        return list(copies)

    def retrieve_interested_comment(self, comments, post_comment_authors):
        # post.replace_more_comments(limit=32, threshold=0)
        for comment in comments:
            if isinstance(comment, MoreComments):
                log.warn("comment is MoreComment %s" % comment)
                continue
            author = comment.author
            created = comment.created_utc

            if author and author.name not in self.comment_authors and author.name not in post_comment_authors:
                log.info("author found: %s" % author.name)
                if _so_long(created, min_comment_create_time_difference) \
                        and comment.ups >= min_comment_ups \
                        and comment.ups <= max_comment_ups:
                    log.debug("will getting author activity for comment: [%s]\n and author: [%s]" % (comment, author))
                    activity = author.get_overview().next()
                    self.s_c_aovv += 1
                    log.debug(
                        "and activity is: %s at created: %s" % (activity, datetime.fromtimestamp(activity.created_utc)))
                    if _so_long(activity.created_utc, min_redditor_time_disable):
                        self.comment_authors.add(author.name)
                        return comment.body

    def do_comment(self):
        get_comment_authors = lambda post_comments: set(
            map(lambda comment: comment.author.name if not isinstance(comment, MoreComments) and comment.author  else "",
                post_comments)
        )
        while 1:
            subreddit = self.reddit.get_random_subreddit()
            self.s_c_rs += 1
            new_posts = filter(lambda x: x.num_comments > min_comments_at_post, list(subreddit.get_new()))
            for post in new_posts:
                if self.last_actions.is_acted(A_COMMENT, post.fullname):
                    continue
                post_comments = set(list(post.comments))
                post_comments_authors = get_comment_authors(post_comments)
                copies = self._get_post_copies(post)
                if len(copies) > min_copy_count:
                    for copy in copies:
                        if copy.fullname != post.fullname:
                            # todo at first you must remove post comments in copy comments
                            comment = self.retrieve_interested_comment(copy.comments, post_comments_authors)
                            if comment and comment not in set(map(lambda x: x.body, post.comments)):
                                log.info(
                                    "comment: [%s] \nin post [%s] at subreddit [%s]" % (comment, post, subreddit))
                                self.last_actions.set_action(A_COMMENT, post.fullname)
                                return

    def do_vote_post(self):
        while 1:
            subreddit = self.reddit.get_random_subreddit()
            self.s_c_rs += 1
            for post in subreddit.get_hot():
                if self.last_actions.is_acted(A_VOTE, post.fullname):
                    continue
                vote_dir = random.choice([1, -1])
                post.vote(vote_dir)
                log.info("vote %s post: %s subreddit %s" % (vote_dir, post, subreddit))
                self.last_actions.set_action(A_VOTE, post.fullname)
                return

    def do_vote_comment(self, post=None):
        if post:
            comment = random.choice(post.comments)
        else:
            subreddit = self.reddit.get_random_subreddit()
            posts = list(subreddit.get_hot())
            post = random.choice(posts)
            comment = random.choice(post.comments)

        vote_dir = random.choice([1, -1])
        comment.vote(vote_dir)
        log.info("vote %s comment: %s subreddit %s" % (vote_dir, comment, comment.submission))
        self.last_actions.set_action(A_VOTE, comment.fullname)

    def do_posting(self):
        pass


def stat_fn(bot, action, **kwargs):
    stat_obj = {"time": time.time()}

    if bot:
        stat_obj.update(bot.return_stats())
        stat_obj.update({"type": action})
    else:
        stat_obj.update({"type": "bot_is_none"})

    stat_obj.update(kwargs)

    db.statistics.insert_one(stat_obj)
    return stat_obj


class Stat(Thread):
    def __init__(self, bot):
        super(Stat, self).__init__()
        self.bot = bot

    def run(self):
        count = 0
        while 1:
            count += 1
            stat_fn(self.bot, "at_time", count=count)
            time.sleep(60)


if __name__ == '__main__':
    bot = None
    try:
        bot = RedditBot("4ikist", "sederfes")
        stat_thread = Stat(bot)
        stat_thread.setDaemon(True)
        stat_thread.start()

        bot.do_comment()
        stat_fn(bot, "comment")

        bot = RedditBot("4ikist", "sederfes")
        bot.do_vote_post()
        stat_fn(bot, "vote_post")

        bot = RedditBot("4ikist", "sederfes")
        bot.do_vote_comment()
        stat_fn(bot, "vote_comment")
    except Exception as e:
        log.exception(e)
        stat_fn(bot, "exception", type="error", exception=e.message, stacktrace=traceback.format_exc())
