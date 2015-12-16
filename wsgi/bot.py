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
from requests import get

from wsgi.engine import net_tryings

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

db = DBHandler()


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


class ActionsHandler(object):
    def __init__(self):
        self.last_actions = {
            A_POST: datetime.utcnow(),
            A_VOTE: datetime.utcnow(),
            A_COMMENT: datetime.utcnow(),
        }
        self.acted = defaultdict(set)
        self.info = {}

    def set_action(self, action_name, identity, info=None):
        self.last_actions[action_name] = datetime.utcnow()
        self.acted[action_name].add(identity)
        if info:
            to_save = {'action': action_name, "r_id": identity}
            to_save.update(info)
            db.bot_log.insert_one(to_save)
            self.info[identity] = info

    def get_last_action(self, action_name):
        res = self.last_actions.get(action_name)
        if not res:
            raise Exception("Action %s is not supported")
        return res

    def is_acted(self, action_name, identity):
        return identity in self.acted[action_name]

    def get_actions(self, action_name=None):
        return self.acted if action_name is None else self.acted.get(action_name)

    def get_action_info(self, identity):
        action_info = self.info.get(identity)
        return action_info


def _so_long(created, min_time):
    (datetime.utcnow() - datetime.fromtimestamp(created)).total_seconds() > min_time


class loginsProvider(object):
    def __init__(self, logins=None, logins_list=None):
        """
        logins must be {"time of lat use":{login:<login>, password:<pwd>}}
        :param logins:
        logins_list list of some dict with keys login and password
        :return:
        """
        self.last_time = datetime.now()
        self.logins = logins or {self.last_time: {'login': "4ikist", "password": "sederfes"}}
        if logins_list:
            self.add_logins(logins_list)
        self.ensure_times()
        self.current_login = self.get_early_login()

    def ensure_times(self):
        self._times = dict(map(lambda el: (el[1]['login'], el[0]), self.logins.items()))

    def get_early_login(self):
        previous_time = self.last_time
        self.last_time = datetime.now()
        next_login = self.logins.pop(previous_time)
        self.logins[self.last_time] = next_login
        self.ensure_times()
        self.current_login = self.logins[min(self.logins.keys())]
        return self.current_login

    def add_logins(self, logins):
        for login in logins:
            self.logins[datetime.now()] = login
        self.ensure_times()

    def get_login_times(self):
        return self._times

    @net_tryings
    def check_current_login(self):
        res = get("http://cors-anywhere.herokuapp.com/www.reddit.com/user/%s/about.json"%self.current_login.get("login"),
                  headers={"origin":"http://www.reddit.com"})
        if res.status_code != 200:
            raise Exception("result code of checking is != 200")


class RedditBot(object):
    def __init__(self, logins):
        self.login_provider = loginsProvider(logins)
        self._login = self.login_provider.get_early_login()
        self.reddit = praw.Reddit(
                user_agent="%s Bot engine.///" % self._login.get("login"))
        self.reddit.login(self._login.get("login"), password=self._login.get("password"), disable_warning=True)
        log.info("bot [%s] connected" % self._login.get("login"))
        self.last_actions = ActionsHandler()
        self.comment_authors = set()

        self.mutex = Lock()

    def populate_stat_object(self):
        self.s_c_s = 0  # count search requests
        self.s_c_rs = 0  # count requests for random subreddit
        self.s_c_aovv = 0  # count requests for author overview

    def change_login(self):
        self._login = self.login_provider.get_early_login()
        self.reddit = praw.Reddit(
                user_agent="%s Bot engine.///" % self._login.get("login"))
        self.reddit.login(self._login.get("login"), password=self._login.get("password"), disable_warning=True)
        log.info("bot [%s] connected" % self._login.get("login"))
        stat_fn(self, "change_login", **{})
        self.populate_stat_object()

    def return_stats(self):
        self.mutex.acquire()
        stat = {"search": self.s_c_s, "random_subreddit": self.s_c_rs, "author_overview": self.s_c_aovv, "votes": s}
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
                    try:
                        activity = author.get_overview().next()
                        self.s_c_aovv += 1
                    except Exception as e:
                        log.exception(e)

                    log.debug(
                            "and activity is: %s at created: %s" % (
                                activity, datetime.fromtimestamp(activity.created_utc)))
                    if _so_long(activity.created_utc, min_redditor_time_disable):
                        self.comment_authors.add(author.name)
                        return comment.body

    def do_comment(self):
        get_comment_authors = lambda post_comments: set(
                map(lambda comment: comment.author.name if not isinstance(comment,
                                                                          MoreComments) and comment.author  else "",
                    post_comments)
        )  # function for retrieving authors from post comments
        while 1:
            subreddit = self.reddit.get_random_subreddit()  # getting random subreddit
            self.s_c_rs += 1  # only for statistic of requests
            new_posts = filter(lambda x: x.num_comments > min_comments_at_post, list(
                    subreddit.get_new()))  # getting interested posts (filtering by comments count of new posts in random subreddit (min_comments count see at start))
            for post in new_posts:  # by post of interested posts
                if self.last_actions.is_acted(A_COMMENT,
                                              post.fullname):  # if this post was comment by me skipping this post
                    continue
                post_comments = set(list(post.comments))  # get comments
                post_comments_authors = get_comment_authors(post_comments)  # getting authors of this comments
                copies = self._get_post_copies(post)  # getting copies of this post
                if len(
                        copies) > min_copy_count:  # if count of copies is grater than min copy count (this value see at start of this file)
                    for copy in copies:  # for each copy of post...
                        if copy.fullname != post.fullname:  # if this copy is not interested post
                            # todo at first you must remove post comments in copy comments
                            comment = self.retrieve_interested_comment(copy.comments,
                                                                       post_comments_authors)  # get some comment from this copy post (comment not deleted, its author not comment original post77)
                            if comment and comment not in set(map(lambda x: x.body,
                                                                  post.comments)):  # this comment is exists and this body not equals to some comment in original post
                                log.info(
                                        "comment: [%s] \nin post [%s] at subreddit [%s]" % (comment, post, subreddit))
                                post.add_comment(comment.body)  # commenting original post
                                self.last_actions.set_action(A_COMMENT, post.fullname, post)  # imply this action...
                                log.info("%s", self.return_stats())
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
                self.last_actions.set_action(A_VOTE, post.fullname, post)
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


class StatWorker(Thread):
    def __init__(self, bot):
        super(StatWorker, self).__init__()
        self.bot = bot

    def run(self):
        count = 0
        while 1:
            count += 1
            stat_fn(self.bot, "at_time", count=count)
            time.sleep(60)


if __name__ == '__main__':
    # bot = None
    # try:
    #     bot = RedditBot("4ikist", "sederfes")
    #     stat_thread = StatWorker(bot)
    #     stat_thread.setDaemon(True)
    #     stat_thread.start()
    #
    #     bot.do_comment()
    #     stat_fn(bot, "comment")
    #
    #     bot = RedditBot("4ikist", "sederfes")
    #     bot.do_vote_post()
    #     stat_fn(bot, "vote_post")
    #
    #     bot = RedditBot("4ikist", "sederfes")
    #     bot.do_vote_comment()
    #     stat_fn(bot, "vote_comment")
    # except Exception as e:
    #     log.exception(e)
    #     stat_fn(bot, "exception", type="error", exception=e.message, stacktrace=traceback.format_exc())
    lp = loginsProvider()
    lp.check_current_login()