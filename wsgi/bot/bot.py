# coding=utf-8
import traceback
from collections import defaultdict
from datetime import datetime
from multiprocessing import Lock
from multiprocessing.process import Process

import praw
from praw.objects import MoreComments
import random
import re
import requests
import requests.auth
import time

from wsgi import properties
from wsgi.db import DBHandler
from wsgi.engine import net_tryings

re_url = re.compile("((https?|ftp)://|www\.)[^\s/$.?#].[^\s]*")

log = properties.logger.getChild("bot")

A_POST = "post"
A_VOTE = "vote"
A_COMMENT = "comment"
A_CONSUME = "consume"

A_SUBSCRIBE = "subscribe"
A_FRIEND = "friend"

DEFAULT_LIMIT = 100

min_copy_count = 2
min_comment_create_time_difference = 3600 * 24 * 30 * 2

shift_copy_comments_part = 5  # общее количество комментариев / это число  = сколько будет пропускаться
min_donor_comment_ups = 3
max_donor_comment_ups = 100000
min_donor_num_comments = 50

max_consuming = 90
min_consuming = 70

min_voting = 65
max_voting = 95

check_comment_text = lambda text: not re_url.match(text) and len(text) > 15 and len(text) < 120 and "Edit" not in text
post_info = lambda post: {"fullname": post.fullname, "url": post.url}

db = DBHandler()

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.106 Safari/537.36"

USER_AGENTS = [
    "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; WOW64; Trident/5.0; chromeframe/12.0.742.112)",
    "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; WOW64; Trident/5.0; .NET CLR 3.5.30729; .NET CLR 3.0.30729; .NET CLR 2.0.50727; Media Center PC 6.0)",
    "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Win64; x64; Trident/5.0; .NET CLR 3.5.30729; .NET CLR 3.0.30729; .NET CLR 2.0.50727; Media Center PC 6.0)",
    "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Win64; x64; Trident/5.0; .NET CLR 2.0.50727; SLCC2; .NET CLR 3.5.30729; .NET CLR 3.0.30729; Media Center PC 6.0; Zune 4.0; Tablet PC 2.0; InfoPath.3; .NET4.0C; .NET4.0E)",
    "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Win64; x64; Trident/5.0",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; ru; rv:1.9.1.2) Gecko/20090729 Firefox/3.5.2",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0; SLCC1; .NET CLR 2.0.50727; .NET CLR 3.5.30729; .NET CLR 3.0.30618; In",
    "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 5.1; Trident/4.0; SHC-KIOSK; SHC-Mac-5FE3; SHC-Unit-K0816; SHC-KMT; .NET C",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0; Trident/4.0; SLCC1; .NET CLR 2.0.50727; Media Center PC 5.0; InfoPath",
    "Mozilla/5.0 (iPad; U; CPU OS 3_2 like Mac OS X; en-us) AppleWebKit/531.21.10 (KHTML, like Gecko) Version/4.0.4 Mobile/7B",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0; SLCC1; .NET CLR 2.0.50727; .NET CLR 3.5.30729; .NET CLR 3.0.30618; In",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.1; Trident/4.0; SLCC2; .NET CLR 2.0.50727; .NET CLR 3.5.30729; .NET CLR",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; .NET CLR 2.0.50727)",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0)",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0; SLCC1; .NET CLR 2.0.50727; .NET CLR 3.5.30729; .NET CLR 3.0.30618; In",
    "Mozilla/5.0 (webOS/1.4.3; U; en-US) AppleWebKit/532.2 (KHTML, like Gecko) Version/1.0 Safari/532.2 Pixi/1.1",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0)",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.1; Trident/4.0; SLCC2; .NET CLR 2.0.50727; .NET CLR 3.5.30729; .NET CLR",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0)",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/533.16 (KHTML, like Gecko) Version/5.0 Safari/533.16",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; Trident/4.0; .NET CLR 1.1.4322; .NET CLR 2.0.50727; .NET CLR 3.0.4506",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; Trident/4.0; .NET CLR 1.1.4322; .NET CLR 2.0.50727; .NET CLR 3.0.4506",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.9.2.4) Gecko/20100611 Firefox/3.6.4 GTB7.0",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.1; Trident/4.0; SLCC2; .NET CLR 2.0.50727; .NET CLR 3.5.30729; .NET CLR",
]


def _so_long(created, min_time):
    return (datetime.utcnow() - datetime.fromtimestamp(created)).total_seconds() > min_time


class RedditBot(object):
    def __init__(self, user_agent=None):
        self.reddit = praw.Reddit(user_agent=user_agent or random.choice(USER_AGENTS))

    def get_hot_and_new(self, subreddit_name, sort=None):
        try:
            subreddit = self.reddit.get_subreddit(subreddit_name)
            hot = list(subreddit.get_hot(limit=DEFAULT_LIMIT))
            new = list(subreddit.get_new(limit=DEFAULT_LIMIT))
            result_dict = dict(map(lambda x: (x.fullname, x), hot), **dict(map(lambda x: (x.fullname, x), new)))

            log.info("Will search for dest posts candidates at %s posts" % len(result_dict))
            result = result_dict.values()
            if sort:
                result.sort(cmp=sort)
            # log.info("Found hot and new: \n%s" % '\n'.join(
            #         ["%s at %s" % (post.permalink, datetime.fromtimestamp(post.created)) for post in result]))
            return result
        except Exception as e:
            return []

class RedditReadBot(RedditBot):
    def __init__(self, db, user_agent=None, state=None):
        """
        :param user_agent: for reddit non auth and non oauth client
        :param lcp: low copies posts if persisted
        :param cp:  commented posts if persisted
        :return:
        """
        super(RedditReadBot, self).__init__(user_agent)

        self.db = db

        if state is None:
            state = {}

        self.low_copies_posts = state.get("lcp") or set()
        self.commented_posts = state.get("cp") or set()

    @property
    def state(self):
        return {"lcp": list(self.low_copies_posts), "cp": list(self.commented_posts)}

    def find_comment(self, at_subreddit):
        def cmp_by_created_utc(x, y):
            result = x.created_utc - y.created_utc
            if result > 0.5:
                return 1
            elif result < 0.5:
                return -1
            else:
                return 0

        subreddit = at_subreddit
        all_posts = self.get_hot_and_new(subreddit, sort=cmp_by_created_utc)
        for post in all_posts:
            if post.fullname in self.commented_posts or post.url in self.low_copies_posts or db.is_post_commented(
                    post.fullname):
                continue
            try:
                copies = self._get_post_copies(post)
                copies = filter(lambda copy: _so_long(copy.created_utc, min_comment_create_time_difference) and \
                                             copy.num_comments > min_donor_num_comments,
                                copies)
                if len(copies) >= min_copy_count:
                    copies.sort(cmp=cmp_by_created_utc)
                    for copy in copies:
                        if copy.subreddit != post.subreddit and copy.fullname != post.fullname:
                            comment = self._retrieve_interested_comment(copy)
                            if comment and post.author != comment.author:
                                log.info("comment: [%s] \nin post [%s] at subreddit [%s]" % (
                                    comment, post.fullname, subreddit))
                                self.commented_posts.add(post.fullname)
                                return post.fullname, comment.body
                else:
                    self.low_copies_posts.add(post.url)
            except Exception as e:
                log.error(e)

    def _get_post_copies(self, post):
        search_request = "url:\'%s\'" % post.url
        copies = list(self.reddit.search(search_request))
        # log.debug("found %s copies by url: %s [%s] [%s]" % (len(copies), post.url, post.fullname, post.permalink))
        return list(copies)

    def _retrieve_comments(self, comments, parent_id, acc=None):
        if acc is None:
            acc = []
        for comment in comments:
            if isinstance(comment, MoreComments):
                try:
                    self._retrieve_comments(comment.comments(), parent_id, acc)
                except Exception as e:
                    log.debug("Exception in unwind more comments: %s" % e)
                    continue
            else:
                if comment.author and comment.parent_id == parent_id:
                    acc.append(comment)
        return acc

    def _retrieve_interested_comment(self, copy):
        # prepare comments from donor to selection
        comments = self._retrieve_comments(copy.comments, copy.fullname)
        after = len(comments) / shift_copy_comments_part
        for i in range(after, len(comments)):
            comment = comments[i]
            if comment.ups >= min_donor_comment_ups and \
                            comment.ups <= max_donor_comment_ups and \
                    check_comment_text(comment.body):
                return comment

    def _get_all_post_comments(self, post, filter_func=lambda x: x):
        result = self._retrieve_comments(post.comments, post.fullname)
        result = set(map(lambda x: x.body, result))
        return result


@net_tryings
def check_any_login(login):
    res = requests.get(
            "http://www.reddit.com/user/%s/about.json" % login,
            headers={"origin": "http://www.reddit.com",
                     "User-Agent": random.choice(USER_AGENTS)})

    if res.status_code != 200:
        return False
    if res.json().get("error", None):
        return False
    return True


class RedditWriteBot(RedditBot):
    def __init__(self, db, login="Shlak2k15", state=None):
        """
        :param subreddits: subbreddits which this bot will comment
        :param login_credentials:  dict object with this attributes: client_id, client_secret, redirect_url, access_token, refresh_token, login and password of user and user_agent 
         user agent can not present it will use some default user agent
        :return:
        """
        super(RedditWriteBot, self).__init__()

        if state is None:
            state = {}
        self.subscribed_subreddits = state.get("ss") or set()
        self.friends = state.get("frds") or set()

        self.db = db
        login_credentials = db.get_bot_access_credentials(login)

        self.init_engine(login_credentials)
        self.init_work_cycle()

        log.info("Write bot inited with params \n %s" % (login_credentials))

    def init_engine(self, login_credentials):
        self.user_agent = login_credentials.get("user_agent", random.choice(USER_AGENTS))
        self.user_name = login_credentials["user"]

        r = praw.Reddit(self.user_agent)
        r.set_oauth_app_info(login_credentials['client_id'], login_credentials['client_secret'],
                             login_credentials['redirect_uri'])
        r.set_access_credentials(**login_credentials.get("info"))
        r.login(login_credentials["user"], login_credentials["pwd"])

        self.access_information = login_credentials.get("info")
        self.reddit = r
        self.refresh_token()

    def refresh_token(self):
        self.access_information = self.reddit.refresh_access_information(self.access_information['refresh_token'])
        self.db.update_bot_access_credentials_info(self.user_name, self.access_information)

    def incr_cnt(self, name):
        self.counters[name] += 1

    def init_work_cycle(self):
        self.counters = {A_CONSUME: 0, A_VOTE: 0, A_COMMENT: 0, A_POST: 0}

        self.action_function_params = {}

        consuming = random.randint(min_consuming, max_consuming)
        production = 100 - consuming

        prod_voting = random.randint(min_voting, max_voting)
        prod_commenting = 100 - prod_voting

        production_voting = (prod_voting * production) / 100
        production_commenting = (prod_commenting * production) / 100

        self.action_function_params = {A_CONSUME: consuming,
                                       A_VOTE: production_voting,
                                       A_COMMENT: production_commenting}
        log.info("MY [%s] WORK CYCLE: %s" % (self.user_name, self.action_function_params))

    def can_do(self, action):
        """
        Action
        :param action: can be: [vote, comment, consume]
        :return:  true or false
        """
        summ = sum(self.counters.values())
        interested_count = self.counters[action]
        granted_perc = self.action_function_params.get(action)
        current_perc = int((float(interested_count if interested_count else 1) / (summ if summ else 100)) * 100)

        return current_perc <= granted_perc

    def _is_want_to(self, coefficient):
        return coefficient >= 0 and random.randint(0, 10) > coefficient

    def register_step(self, step_type, info=None):
        if step_type in self.counters:
            self.incr_cnt(step_type)

        self.db.save_log_bot_row(self.user_name, step_type, info or {})
        self.persist_state()

    @property
    def state(self):
        return {"ss": list(self.subscribed_subreddits),
                "frds": list(self.friends)}

    def persist_state(self):
        self.db.update_bot_state(self.user_name, state=self.state)

    def do_see_post(self, post,
                    subscribe=9,
                    author_friend=9,
                    comments=7,
                    comment_mwt=5,
                    comment_vote=8,
                    comment_friend=7,
                    comment_url=8,
                    post_vote=6,
                    max_wait_time=30):
        """
        1) go to his url with yours useragent, wait random
        2) random check comments and random check more comments
        3) random go to link in comments
        #todo refactor action want to normal function
        :param post:
        :return:
        """
        try:
            res = requests.get(post.url, headers={"User-Agent": self.user_agent})
            log.info("SEE POST result: %s" % res)
            self.register_step(A_CONSUME, info={"url": post.url})
        except Exception as e:
            log.warning("Can not see post %s url %s \n EXCEPT [%s] \n %s" % (
                post.fullname, post.url, e, traceback.format_exc()))

        wt = self.wait(max_wait_time)

        if self._is_want_to(post_vote) and self.can_do("vote"):
            try:
                vote_count = random.choice([1, -1])
                post.vote(vote_count)
                self.register_step(A_VOTE, info={"post": post.fullname, "vote": vote_count})
                self.wait(max_wait_time / 2)
            except Exception as e:
                log.error(e)
        if self._is_want_to(comments) and wt > 5:  # go to post comments
            for comment in post.comments:
                try:
                    if self._is_want_to(comment_vote) and self.can_do("vote"):  # voting comment
                        vote_count = random.choice([1, -1])
                        comment.vote(vote_count)
                        self.register_step(A_VOTE, info={"post": comment.fullname, "vote": vote_count})
                        self.wait(max_wait_time / 10)
                        if self._is_want_to(comment_friend) and vote_count > 0:  # friend comment author
                            c_author = comment.author
                            if c_author.fullname not in self.friends:
                                c_author.friend()
                                self.friends.add(c_author.fullname)
                                self.register_step(A_FRIEND, info={"friend": c_author.fullname})
                                self.wait(max_wait_time / 10)

                    if self._is_want_to(comment_url):  # go to url in comment
                        urls = re_url.findall(comment.body)
                        for url in urls:
                            res = requests.get(url, headers={"User-Agent": self.user_agent})
                            log.info("SEE Comment link result: %s", res)
                        if urls:
                            self.register_step(A_CONSUME, info={"urls": urls})
                except Exception as e:
                    log.error(e)
            self.wait(max_wait_time / 5)

        if self._is_want_to(
                subscribe) and post.subreddit.display_name not in self.subscribed_subreddits:  # subscribe sbrdt
            try:
                self.reddit.subscribe(post.subreddit.display_name)
                self.subscribed_subreddits.add(post.subreddit.display_name)
                self.register_step(A_SUBSCRIBE, info={"sub": post.subreddit.display_name})
                self.wait(max_wait_time / 5)
            except Exception as e:
                log.error(e)
        if self._is_want_to(author_friend) and post.author.fullname not in self.friends:  # friend post author
            post.author.friend()
            try:
                self.friends.add(post.author.fullname)
                self.register_step(A_FRIEND, info={"friend": post.author.fullname})
                self.wait(max_wait_time / 5)
            except Exception as e:
                log.error(e)

    def wait(self, max_wait_time):
        wt = random.randint(1, max_wait_time)
        time.sleep(wt)
        return wt

    def _get_random_near(self, slice, index, max):
        rnd = lambda x: random.randint(x / 10, x / 2) or 1
        max_ = lambda x: x if x < max and max_ != -1  else max
        count_random_left = max_(rnd(len(slice[0:index])))
        count_random_right = max_(rnd(len(slice[index:])))

        return [random.choice(slice[0:index]) for _ in xrange(count_random_left)], \
               [random.choice(slice[index:]) for _ in xrange(count_random_right)]

    def do_comment_post(self, post_fullname, subreddit_name, comment_text, max_post_near=3, max_wait_time=20,
                        subscribe_subreddit=7, **kwargs):
        near_posts = self.get_hot_and_new(subreddit_name)
        for i, _post in enumerate(near_posts):
            if _post.fullname == post_fullname:
                see_left, see_right = self._get_random_near(near_posts, i, random.randint(1, 4))
                try:
                    for p_ind in see_left:
                        self.do_see_post(p_ind, max_wait_time=max_wait_time, **kwargs)
                except Exception as e:
                    log.error(e)

                try:
                    for comment in filter(lambda comment: isinstance(comment, MoreComments), _post.comments):
                        etc = comment.comments()
                        print etc
                        if random.randint(0, 10) > 6:
                            break
                except Exception as e:
                    log.error(e)

                try:
                    _post.add_comment(comment_text)
                except Exception as e:
                    log.error(e)

                try:
                    for p_ind in see_right:
                        self.do_see_post(p_ind, max_wait_time=max_wait_time, **kwargs)
                except Exception as e:
                    log.error(e)

        try:
            if self._is_want_to(subscribe_subreddit) and subreddit_name not in self.subscribed_subreddits:
                self.reddit.subscribe(subreddit_name)
                self.register_step(A_SUBSCRIBE, info={"sub": subreddit_name})
        except Exception as e:
            log.error(e)

        self.register_step(A_COMMENT, info={"post": post_fullname, "text": comment_text, "sub": subreddit_name})


class BotKapellmeister(Process):
    def __init__(self, wb_name, db, ):
        super(BotKapellmeister, self).__init__()
        self.db = db
        state = db.get_bot_state(wb_name)
        self.bot_name = wb_name

        self.r_bot = RedditReadBot(db, state=state)
        self.w_bot = RedditWriteBot(db, login=wb_name, state=state)

        self.must_stop = False

    def bot_check(self):
        ok = check_any_login(self.bot_name)
        if not ok:
            self.db.set_bot_banned(self.bot_name)
        return ok

    def will_must_stop(self):
        self.must_stop = True

    def run(self):
        while 1:
            try:
                if self.must_stop:
                    break
                if not self.bot_check():
                    break
                for subreddit in self.db.get_bot_subs(self.bot_name):
                    found = self.r_bot.find_comment(subreddit)
                    if not found: continue
                    post_fullname, comment_text = found
                    self.db.update_bot_state(self.bot_name, self.r_bot.state)
                    self.db.set_posts_commented(self.r_bot.state.get("cp"))

                    self.w_bot.do_comment_post(post_fullname, subreddit, comment_text, max_post_near=100)

                self.w_bot.wait(3600)
            except Exception as e:
                time.sleep(10)
                log.exception(e)
