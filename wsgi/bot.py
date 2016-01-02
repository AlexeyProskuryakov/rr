from collections import defaultdict
from datetime import datetime
from multiprocessing import Lock, Queue
import praw
from praw.objects import MoreComments
import random
import re
import requests
import time

from wsgi import properties
from wsgi.db import DBHandler
from wsgi.engine import net_tryings

re_url = re.compile("((https?|ftp)://|www\.)[^\s/$.?#].[^\s]*")


log = properties.logger.getChild("reddit-bot")

A_POST = "post"
A_VOTE = "vote"
A_COMMENT = "comment"

DEFAULT_LIMIT = 100

min_copy_count = 2
min_comment_create_time_difference = 3600 * 24 * 30 * 2
min_comment_ups = 20
max_comment_ups = 100000
min_donor_num_comments = 50
min_selection_comments = 10
max_selection_comments = 20

check_comment_text = lambda text: not re_url.match(text) and len(text) > 15 and len(text) < 120
post_info = lambda post: {"fullname": post.fullname, "url": post.url}

db = DBHandler()


def _so_long(created, min_time):
    return (datetime.utcnow() - datetime.fromtimestamp(created)).total_seconds() > min_time


def _get_hot_and_new(subreddit, sort=None):
    hot = list(subreddit.get_hot(limit=DEFAULT_LIMIT))
    new = list(subreddit.get_new(limit=DEFAULT_LIMIT))
    hot_d = dict(map(lambda x: (x.fullname, x), hot))
    new_d = dict(map(lambda x: (x.fullname, x), new))
    hot_d.update(new_d)
    log.info("Will search for dest posts candidates at %s posts" % len(hot_d))
    result = hot_d.values()
    if sort:
        result.sort(cmp=sort)
    return result


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


class loginsProvider(object):
    def __init__(self, login=None, logins_list=None):
        """
        :param login: must be {"time of lat use":{login:<login>, password:<pwd>, User-Agent:<some user agent>}}
        """
        self.last_time = datetime.now()
        self.logins = login or {
            self.last_time: {'login': "4ikist", "password": "sederfes", "User-Agent": "fooo bar baz"}}
        if logins_list and isinstance(logins_list, list):
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
        res = requests.get(
                "http://cors-anywhere.herokuapp.com/www.reddit.com/user/%s/about.json" % self.current_login.get(
                        "login"),
                headers={"origin": "http://www.reddit.com"})
        if res.status_code != 200:
            log.error("Check login is err :( ,%s " % res)


class RedditBot(object):
    def __init__(self, subreddits, user_agent=None):
        self.last_actions = ActionsHandler()

        self.mutex = Lock()
        self.subreddits = subreddits
        self._current_subreddit = None

        self.low_copies_posts = set()

        self.subscribed_subreddits = set()
        self.friends = set()

        self.reddit = praw.Reddit(user_agent=user_agent or "Reddit search bot")

    @property
    def current_subreddit(self):
        self.mutex.acquire()
        result = self._current_subreddit
        self.mutex.release()
        return result

    @current_subreddit.setter
    def current_subreddit(self, new_sbrdt):
        self.mutex.acquire()
        self._current_subreddit = new_sbrdt
        self.mutex.release()

    @property
    def login(self):
        self.mutex.acquire()
        result = self._login.get("login")
        self.mutex.release()
        return result


class RedditReadBot(RedditBot):
    def __init__(self, subreddits, user_agent=None):
        super(RedditReadBot, self).__init__(subreddits, user_agent)

    def find_comment(self, at_subreddit=None):
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

        used_subreddits = set()

        while 1:
            subreddit = at_subreddit or random.choice(self.subreddits)
            if subreddit in used_subreddits:
                continue
            else:
                used_subreddits.add(subreddit)

            self.current_subreddit = subreddit
            all_posts = _get_hot_and_new(self.reddit.get_subreddit(subreddit_name=subreddit), sort=cmp_by_created_utc)
            for post in all_posts:
                if self.last_actions.is_acted(A_COMMENT, post.fullname) or post.url in self.low_copies_posts:
                    continue
                copies = self._get_post_copies(post)
                copies = filter(lambda copy: _so_long(copy.created_utc, min_comment_create_time_difference) and \
                                             copy.num_comments > min_donor_num_comments,
                                copies)
                if len(copies) > min_copy_count:
                    post_comments = set(self._get_all_post_comments(post))
                    post_comments_authors = get_comment_authors(post_comments)
                    copies.sort(cmp=cmp_by_created_utc)
                    for copy in copies:
                        if copy.fullname != post.fullname and copy.subreddit != post.subreddit:
                            comment = self._retrieve_interested_comment(copy, post_comments_authors)
                            if comment and comment not in set(map(
                                    lambda x: x.body if not isinstance(x, MoreComments) else "",
                                    post_comments
                            )):
                                log.info("comment: [%s] \nin post [%s] at subreddit [%s]" % (comment, post, subreddit))
                                return post, comment
                else:
                    self.low_copies_posts.add(post.url)

    def _get_post_copies(self, post):
        copies = list(self.reddit.search("url:'/%s'/" % post.url))
        log.debug("found %s copies by url: %s" % (len(copies), post.url))
        return list(copies)

    def _retrieve_interested_comment(self, copy, post_comment_authors):
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

    def _get_all_post_comments(self, post, filter_func=lambda x: x):
        result = []
        for comment in post.comments:
            if isinstance(comment, MoreComments):
                result.extend(filter(filter_func, comment.comments()))
            else:
                result.append(filter_func(comment))
        return result


class RedditWriteBot(RedditBot):
    def __init__(self, subreddits, login=None, logins=None):
        """
        :param logins: list of
        :param subreddits:
        :param login:
        :return:
        """
        super(RedditWriteBot, self).__init__(subreddits)

        self.login_provider = loginsProvider(login, logins)
        if not login:
            self.change_login()
        else:
            self._login = login

        self.comments_queue = Queue()
        self.r_caf = 0
        self.r_cur = 0
        self.ss = 0

        self.c_read_post = 0
        self.c_vote_comment = 0
        self.c_comment_post = 0

        self.action_function_params = {}

    def change_login(self):
        self._login = self.login_provider.get_early_login()
        self.reddit = praw.Reddit(
                user_agent=self._login.get("User-Agent"))
        self.reddit.login(self._login.get("login"), password=self._login.get("password"), disable_warning=True)
        log.info("bot [%s] connected" % self._login.get("login"))

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

    def init_work_cycle(self):
        consuming = random.randint(70, 100)
        production = 100 - consuming

        prod_voting = random.randint(60, 100)
        prod_commenting = 100 - prod_voting

        production_voting = (prod_voting * production) / 100
        production_commenting = (prod_commenting * production) / 100

        self.action_function_params = {"consume": consuming, "vote": production_voting,
                                       "comment": production_commenting}

    def can_do(self, action):
        """
        Action
        :param action: can be: [vote, comment, consume]
        :return:  true or false
        """
        self.mutex.acquire()
        summ = self.c_vote_comment + self.c_comment_post + self.c_read_post
        interested_count = 0
        if action == "vote":
            interested_count = self.c_vote_comment
        elif action == "comment":
            interested_count = self.c_comment_post
        elif action == "consume":
            interested_count = self.c_read_post

        granted_perc = self.action_function_params.get(action)
        current_perc = (summ / interested_count) * 100
        self.mutex.release()
        return current_perc <= granted_perc

    def add_post_to_comment(self, subreddit_name, post_fullname, comment_text):
        self.mutex.acquire()
        self.comments_queue.put(
                {"subreddit_name": subreddit_name, "post_fullname": post_fullname, "comment_text": comment_text})
        self.mutex.release()

    def process_work_cycle(self, subreddit_name, url_for_video):
        pass

    def do_see_post(self, post, subscribe=True, author_friend=True, comments=True, comment_vote=True,
                    comment_friend=True):
        """
        1) go to his url with yours useragent, wait random
        2) random check comments and random check more comments
        3) random go to link in comments
        :param post:
        :return:
        """
        res = requests.get(post.url, headers={"User-Agent": self._login.get("User-Agent")})
        log.info("SEE POST result: %s" % res)
        wt = random.randint(1, 60)
        log.info("wait time: %s" % wt)
        time.sleep(wt)
        if comments and random.randint(0, 10) > 7 and wt > 5:  # go to post comments
            for comment in post.comments:
                if comment_vote and random.randint(0, 10) >= 8 and self.can_do("vote"):  # voting comment
                    vote_count = random.choice[1, -1]
                    comment.vote(vote_count)
                    self.c_vote_comment += 1
                    if comment_friend and random.randint(0, 10) >= 5 and vote_count > 0:  # friend comment author
                        c_author = comment.author
                        if c_author.name not in self.friends:
                            c_author.friend()
                            self.friends.add(c_author.name)

                if random.randint(0, 10) >= 8:  # go to url in comment
                    urls = re_url.findall(comment.body)
                    for url in urls:
                        res = requests.get(url, headers={"User-Agent": self._login.get("User-Agent")})
                        log.info("SEE Comment link result: %s", res)
                        self.r_cur += 1

        if subscribe and random.randint(0,10) >= 9 and \
                        post.subreddit.fullname not in self.subscribed_subreddits:  # subscribe sbrdt
            self.reddit.subscribe(post.subeddit)
            self.subscribed_subreddits.add(post.subreddit.fullname)
            self.ss += 1

        if author_friend and random.randint(0,
                                            10) >= 9 and post.author.fullname not in self.friends:  # friend post author
            post.author.friend()
            self.friends.add(post.author.fullname)
            self.r_caf += 1

        self.c_read_post += 1

    def _get_random_near(self, slice, index):
        count_left = len(slice[0:index])
        count_right = len(slice[index:])
        count_random_left = random.randint(count_left / 5, count_left / 2)
        count_random_right = random.randint(count_right / 5, count_right / 2)

        return [random.choice(slice[0:index]) for _ in xrange(count_random_left)], \
               [random.choice(slice[index:]) for _ in xrange(count_random_right)]

    def do_comment_post(self, post, comment_text):
        sbrdt = post.subreddit
        near_posts = _get_hot_and_new(sbrdt)
        for i, _post in enumerate(near_posts):
            if _post.fullname == post.fullname:
                see_left, see_right = self._get_random_near(near_posts, i)
                for p_ind in see_left:
                    self.do_see_post(p_ind)
                post.comment(comment_text)
                for p_ind in see_right:
                    self.do_see_post(p_ind)

        if random.randint(0, 10) > 7 and sbrdt.fullname not in self.subscribed_subreddits:
            self.reddit.subscribe(sbrdt)

    def is_shadowbanned(self):
        self.mutex.acquire()
        result = self.login_provider.check_current_login()
        self.mutex.release()
        return result


if __name__ == '__main__':
    rbot = RedditReadBot(["videos"])
    wbot = RedditWriteBot(["videos"])

    post, text = rbot.find_comment()
    wbot.do_comment_post(post, text)
