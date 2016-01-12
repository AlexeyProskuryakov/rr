# coding=utf-8
import traceback
from collections import defaultdict
from datetime import datetime
from multiprocessing import Lock
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

log = properties.logger.getChild("reddit-bot")

A_POST = "post"
A_VOTE = "vote"
A_COMMENT = "comment"
A_CONSUME = "consume"

DEFAULT_LIMIT = 100

min_copy_count = 2
min_comment_create_time_difference = 3600 * 24 * 30 * 2

shift_copy_comments_part = 5  # общее количество комментариев / это число пропускаются
min_donor_comment_ups = 3
max_donor_comment_ups = 100000
min_donor_num_comments = 50

min_selection_comments = 10
max_selection_comments = 20

max_consuming = 90
min_consuming = 70

min_voting = 65
max_voting = 95

check_comment_text = lambda text: not re_url.match(text) and len(text) > 15 and len(text) < 120
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


class RedditBot(object):
    def __init__(self, subreddits, user_agent=None):
        self.last_actions = ActionsHandler()

        self.mutex = Lock()
        self.subreddits = subreddits
        self._current_subreddit = None

        self.low_copies_posts = set()

        self.subscribed_subreddits = set()
        self.friends = set()

        self.reddit = praw.Reddit(user_agent=user_agent or random.choice(USER_AGENTS))

    def get_hot_and_new(self, subreddit_name, sort=None):
        subreddit = self.reddit.get_subreddit(subreddit_name)
        hot = list(subreddit.get_hot(limit=DEFAULT_LIMIT))
        new = list(subreddit.get_new(limit=DEFAULT_LIMIT))
        result_dict = dict(map(lambda x: (x.fullname, x), hot), **dict(map(lambda x: (x.fullname, x), new)))

        log.info("Will search for dest posts candidates at %s posts" % len(result_dict))
        result = result_dict.values()
        if sort:
            result.sort(cmp=sort)
        log.info("Found hot and new: \n%s" % '\n'.join(
                ["%s at %s" % (post.permalink, datetime.fromtimestamp(post.created)) for post in result]))
        return result

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


class RedditReadBot(RedditBot):
    def __init__(self, subreddits, user_agent=None):
        super(RedditReadBot, self).__init__(subreddits, user_agent)

    def find_comment(self, at_subreddit=None):
        def cmp_by_created_utc(x, y):
            result = x.created_utc - y.created_utc
            if result > 0.5:
                return 1
            elif result < 0.5:
                return -1
            else:
                return 0

        while 1:
            subreddit = at_subreddit or random.choice(self.subreddits)
            self.current_subreddit = subreddit
            all_posts = self.get_hot_and_new(subreddit, sort=cmp_by_created_utc)
            for post in all_posts:
                if self.last_actions.is_acted(A_COMMENT, post.fullname) or post.url in self.low_copies_posts:
                    continue
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
                                return post.fullname, comment.body
                else:
                    self.low_copies_posts.add(post.url)

    def _get_post_copies(self, post):
        search_request = "url:\'%s\'" % post.url
        copies = list(self.reddit.search(search_request))
        log.debug("found %s copies by url: %s [%s] [%s]" % (len(copies), post.url, post.fullname, post.permalink))
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


class RedditWriteBot(RedditBot):
    def __init__(self, subreddits, login_credentials):
        """
        :param subreddits: subbreddits which this bot will comment
        :param login_credentials:  dict object with this attributes: client_id, client_secret, redirect_url, access_token, refresh_token, login and password of user and user_agent 
         user agent can not present it will use some default user agent
        :return:
        """
        super(RedditWriteBot, self).__init__(subreddits)

        self.init_engine(login_credentials)
        self.init_work_cycle()
        log.info("Write bot inited with params \n %s" % (login_credentials))

    @net_tryings
    def check_login(self):
        res = requests.get(
                "http://cors-anywhere.herokuapp.com/www.reddit.com/user/%s/about.json" % self.user_name,
                headers={"origin": "http://www.reddit.com"})
        if res.status_code != 200:
            log.error("Check login is err :( ,%s " % res)
            return False
        return True

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
            self.incr_cnt(A_CONSUME)
        except Exception as e:
            log.warning("Can not see post %s url %s \n EXCEPT [%s] \n %s" % (
                post.fullname, post.url, e, traceback.format_exc()))

        wt = random.randint(1, max_wait_time)
        log.info("wait time: %s" % wt)
        time.sleep(wt)
        if self._is_want_to(post_vote) and self.can_do("vote"):
            vote_count = random.choice([1, -1])
            post.vote(vote_count)
            self.incr_cnt(A_VOTE)

        if self._is_want_to(comments) and wt > 5:  # go to post comments
            for comment in post.comments:
                if self._is_want_to(comment_vote) and self.can_do("vote"):  # voting comment
                    vote_count = random.choice([1, -1])
                    comment.vote(vote_count)
                    self.incr_cnt(A_VOTE)
                    if self._is_want_to(comment_friend) and vote_count > 0:  # friend comment author
                        c_author = comment.author
                        if c_author.name not in self.friends:
                            c_author.friend()
                            self.friends.add(c_author.name)

                if self._is_want_to(comment_url):  # go to url in comment
                    urls = re_url.findall(comment.body)
                    for url in urls:
                        res = requests.get(url, headers={"User-Agent": self.user_agent})
                        log.info("SEE Comment link result: %s", res)
                    self.incr_cnt(A_CONSUME)

        if self._is_want_to(
                subscribe) and post.subreddit.display_name not in self.subscribed_subreddits:  # subscribe sbrdt
            self.reddit.subscribe(post.subreddit.display_name)
            self.subscribed_subreddits.add(post.subreddit.display_name)

        if self._is_want_to(author_friend) and post.author.fullname not in self.friends:  # friend post author
            post.author.friend()
            self.friends.add(post.author.fullname)

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
                for p_ind in see_left:
                    self.do_see_post(p_ind, max_wait_time=max_wait_time, **kwargs)

                for comment in filter(lambda comment: isinstance(comment, MoreComments), _post.comments):
                    etc = comment.comments()
                    print etc
                    if random.randint(0, 10) > 6:
                        break

                _post.add_comment(comment_text)

                for p_ind in see_right:
                    self.do_see_post(p_ind, max_wait_time=max_wait_time, **kwargs)

        if self._is_want_to(subscribe_subreddit) and subreddit_name not in self.subscribed_subreddits:
            self.reddit.subscribe(subreddit_name)

        self.incr_cnt(A_COMMENT)


if __name__ == '__main__':
    db = DBHandler()
    # sbrdt = "videos"
    # rbot = RedditReadBot(["videos"])
    # """client_id: O5AZrYjXI1R-7g
    # """client_secret: LOsmYChS2dcdQIlkMG9peFR6Lns
    wbot = RedditWriteBot(["videos"], db.get_access_credentials("Shlak2k15"))
    db.update_access_credentials_info("Shlak2k15", wbot.access_information)

    # subreddit = "videos"
    # log.info("start found comment...")
    # post_fullname, text = rbot.find_comment(subreddit)
    # # post_fullname, text = "t3_400kke", "[Fade Into You](http://www.youtube.com/watch?v=XucegAHZojc)"#rbot.find_comment(subreddit)
    # log.info("fullname: %s\ntext: %s" % (post_fullname, text))
    # wbot.do_comment_post(post_fullname, subreddit, text, max_wait_time=2, subscribe=0, author_friend=0, comments=0,
    #                      comment_vote=0, comment_friend=0, post_vote=0, comment_mwt=0, comment_url=0)

    for i in range(100):
        print "Can comment? %s Can vote? %s Can consume? %s" % (
            wbot.can_do(A_COMMENT), wbot.can_do(A_VOTE), wbot.can_do(A_CONSUME))

        wbot.incr_cnt(A_CONSUME)
