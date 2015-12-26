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

import re

re_url = re.compile("((https?|ftp)://|www\.)[^\s/$.?#].[^\s]*")

MIN_COPY_COUNT = 10

log = properties.logger.getChild("reddit-bot")

A_POST = "post"
A_VOTE = "vote"
A_COMMENT = "comment"

min_copy_count = 2
min_comment_create_time_difference = 3600 * 24 * 30 * 2

min_comment_ups = 20
max_comment_ups = 100000

min_donor_num_comments = 100

min_selection_comments = 10
max_selection_comments = 20

check_comment_text = lambda text: not re_url.match(text) and len(text) > 15 and len(text) < 120

post_info = lambda post: {"fullname": post.fullname, "url": post.url}
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
            to_save = {'action': action_name, "r_id": identity, "info": info}
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
    return (datetime.utcnow() - datetime.fromtimestamp(created)).total_seconds() > min_time


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
        res = get(
                "http://cors-anywhere.herokuapp.com/www.reddit.com/user/%s/about.json" % self.current_login.get(
                        "login"),
                headers={"origin": "http://www.reddit.com"})
        if res.status_code != 200:
            raise Exception("result code of checking is != 200")


class RedditBot(object):
    def __init__(self, logins, subreddits):
        self.login_provider = loginsProvider(logins)
        self.populate_stat_object()
        self.change_login()

        self.last_actions = ActionsHandler()
        self.comment_authors = set()

        self.mutex = Lock()
        self.subreddits = subreddits
        self.low_copies_posts = set()

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

    def return_stats(self):
        self.mutex.acquire()
        stat = {"search": self.s_c_s, "random_subreddit": self.s_c_rs, "author_overview": self.s_c_aovv}
        log.info("return stat: %s" % stat)
        self.mutex.release()
        return stat

    def _get_post_copies(self, post):
        copies = list(self.reddit.search("url:'/%s'/" % post.url))
        log.debug("found %s copies by url: %s" % (len(copies), post.url))
        self.s_c_s += 1
        return list(copies)

    def retrieve_interested_comment(self, copy, post_comment_authors):
        if copy.num_comments < min_donor_num_comments:
            return

        # prepare comments from donor to selection
        comments = []
        for i, comment in enumerate(copy.comments):
            if isinstance(comment, MoreComments):
                try:
                    comments.extend(comment.comments())
                except Exception as e:
                    log.exception(e)
                    log.warning("Fuck. Some error. More comment were not unwind. ")
            if i < random.randint(min_selection_comments, max_selection_comments):
                continue
            comments.append(comment)

        for comment in comments:
            author = comment.author
            if author and comment.ups >= min_comment_ups and comment.ups <= max_comment_ups and check_comment_text(
                    comment.body):
                return comment.body

    def get_all_post_comments(self, post, filter_func=lambda x: x):
        result = []
        for comment in post.comments:
            if isinstance(comment, MoreComments):
                result.extend(filter(filter_func, comment.comments()))
            else:
                result.append(filter_func(comment))
        return result

    def do_comment(self):
        get_comment_authors = lambda post_comments: set(
                map(lambda comment: comment.author.name if not isinstance(comment,
                                                                          MoreComments) and comment.author else "",
                    post_comments)
        )  # function for retrieving authors from post comments

        def cmp_by_created_utc(x, y):
            result = x.created_utc - y.created_utc
            if result > 0.5:
                return 1
            elif result < 0.5:
                return -1
            else:
                return 0

        def get_hot_and_new(subreddit):
            hot = list(subreddit.get_hot(limit=100))
            new = list(subreddit.get_new(limit=100))
            hot_d = dict(map(lambda x: (x.fullname, x), hot))
            new_d = dict(map(lambda x: (x.fullname, x), new))
            hot_d.update(new_d)
            log.info("Will search for dest posts candidates at %s posts" % len(hot_d))
            result = hot_d.values()
            result.sort(cmp=cmp_by_created_utc)
            return result

        used_subreddits = set()

        while 1:
            subreddit = random.choice(self.subreddits)
            if subreddit in used_subreddits:
                continue
            else:
                used_subreddits.add(subreddit)

            self.s_c_rs += 1
            all_posts = get_hot_and_new(self.reddit.get_subreddit(subreddit_name=subreddit))
            for post in all_posts:
                if self.last_actions.is_acted(A_COMMENT, post.fullname) or post.url in self.low_copies_posts:
                    continue
                copies = self._get_post_copies(post)
                copies = filter(lambda copy: _so_long(copy.created_utc, min_comment_create_time_difference), copies)
                if len(copies) > min_copy_count:
                    post_comments = set(self.get_all_post_comments(post))
                    post_comments_authors = get_comment_authors(post_comments)

                    copies.sort(cmp=cmp_by_created_utc)
                    for copy in copies:
                        if copy.fullname != post.fullname:
                            comment = self.retrieve_interested_comment(copy, post_comments_authors)
                            if comment and comment not in set(map(
                                    lambda x: x.body if not isinstance(x, MoreComments) else "",
                                    post_comments
                            )):
                                log.info("comment: [%s] \nin post [%s] at subreddit [%s]" % (comment, post, subreddit))
                                post.add_comment(comment)  # commenting original post
                                self.last_actions.set_action(A_COMMENT, post.fullname,
                                                             post_info(post))  # imply this action...
                                log.info("%s", self.return_stats())
                                return
                else:
                    self.low_copies_posts.add(post.url)

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
                self.last_actions.set_action(A_VOTE, post.fullname, post_info(post))
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
    bot = None
    try:
        bot = RedditBot(logins=None, subreddits=["videos"])
        # stat_thread = StatWorker(bot)
        # stat_thread.setDaemon(True)
        # stat_thread.start()

        bot.do_comment()
        stat_fn(bot, "comment")

        bot.do_vote_post()
        stat_fn(bot, "vote_post")

        bot.do_vote_comment()
        stat_fn(bot, "vote_comment")

    except Exception as e:
        log.exception(e)
        stat_fn(bot, "exception", type="error", exception=e.message, stacktrace=traceback.format_exc())

        # lp = loginsProvider()
        # lp.check_current_login()
