import urlparse
from collections import defaultdict
from datetime import datetime
from lxml import html
from multiprocessing import Lock, Queue
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

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.106 Safari/537.36"


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


class loginsProvider(object):
    def __init__(self, login=None, logins_list=None):
        """
        :param login: must be {"time of lat use":{login:<login>, password:<pwd>, User-Agent:<some user agent>}}
        """
        self.last_time = datetime.now()
        self.logins = login or {
            self.last_time: {'login': "4ikist", "password": "sederfes", "User-Agent": DEFAULT_USER_AGENT}}
        if logins_list and isinstance(logins_list, list):
            self.add_logins(logins_list)
        self.ensure_times()
        self.current_login = self.get_early_login()
        db.save_reddit_login(self.current_login.get("login"), self.current_login.get("password"))
        db.update_reddit_login("4ikist", {"User-Agent": DEFAULT_USER_AGENT, "last_use": time.time()})

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

    def get_hot_and_new(self, subreddit_name, sort=None):
        subreddit = self.reddit.get_subreddit(subreddit_name)
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
            all_posts = self.get_hot_and_new(subreddit, sort=cmp_by_created_utc)
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
                                log.info("comment: [%s] \nin post [%s] at subreddit [%s]" % (
                                comment, post.fullname, subreddit))
                                return post.fullname, comment
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


def get_params(doc, xpath, acc):
    for el in doc.xpath(xpath):
        if el.value:
            acc[el.attrib.get("name")] = el.value
    return acc


class RedditWriteBot(RedditBot):
    def __init__(self, subreddits, login=None, logins=None, client_id=None, client_secret=None, redirect_uri=None):
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
        self.init_work_cycle()

        if client_id and client_secret:
            self.reddit.set_oauth_app_info(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
            url = self.reddit.get_authorize_url('uniqueKey', 'identity,edit,submit,subscribe,vote', refreshable=True)

            # client_auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
            # post_data = {"grant_type": "password", "username": "Shlak2k15", "password": "sederfes100500"}
            # headers = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"}
            # response = requests.post("https://www.reddit.com/api/v1/access_token", auth=client_auth, data=post_data, headers=headers)
            # result = response.json()

            s = requests.Session()
            s.verify = properties.cacert_file
            s.headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"
            }
            #code down is emulate of browser
            result = s.get(url)
            if result.status_code == 200:
                doc = html.document_fromstring(result.content)
                # checking if user not auth
                if "sign up or log in" in doc.xpath("//title")[0].text:
                    form_login_params = get_params(doc, "//form[@id='login-form']/input", {})
                    form_login_params = get_params(doc, "//form[@id='login-form']//input", form_login_params)
                    form_login_params["user"] = "Shlak2k15"
                    form_login_params["passwd"] = "sederfes100500"
                    form_login_params["rem"] = ""

                    form_url = doc.xpath('//form[@id="login-form"]')[0].attrib.get('action')
                    result_login = s.post(form_url, form_login_params)
                    s.cookies = result_login.cookies
                    doc = html.document_fromstring(result_login.content)
                    # url = result_login.url

                form_access_params = get_params(doc, '//form[@class="pretty-form"]/input', {})
                form_access_params = get_params(doc, '//form[@class="pretty-form"]//input', form_access_params)

                form_url = doc.xpath('//form[@class="pretty-form"]')[0].attrib.get('action')
                result = s.post("https://www.reddit.com"+form_url, form_access_params)

            access_credentials = self.reddit.get_access_information(result.get("access_token"))
            self.reddit.set_access_credentials(**access_credentials)
            authenticated_user = self.reddit.get_me()

            print authenticated_user.name, authenticated_user.link_karma

            self.reddit.refresh_access_information("oGeBJexroWdeAco1yhDZnCSj8kQ")

        log.info("Write bot [%s] inited \n %s" % (self._login, self.action_function_params))

    def __auth(self, vk_login):
        """
        authenticate in vk with dirty hacks
        :return: access token
        """
        # process first page
        s = requests.Session()
        s.verify = properties.certs_path
        result = s.get('https://oauth.vk.com/authorize', params=properties.vk_access_credentials)
        doc = html.document_fromstring(result.content)
        inputs = doc.xpath('//form[@class="pretty-form"]/input')
        form_params = {}
        for el in inputs:
            form_params[el.attrib.get('name')] = el.value
        form_params['email'] = vk_login
        form_params['pass'] = properties.vk_pass
        form_url = doc.xpath('//form')[0].attrib.get('action')
        # process second page
        result = s.post(form_url, form_params)
        doc = html.document_fromstring(result.content)
        # if already login
        if 'OAuth Blank' not in doc.xpath('//title')[0].text:
            submit_url = doc.xpath('//form')[0].attrib.get('action')
            result = s.post(submit_url, cookies=result.cookies)

        # retrieving access token from url
        parsed_url = urlparse.urlparse(result.url)
        if 'error' in parsed_url.query:
            log.error('error in authenticate \n%s' % parsed_url.query)
            raise Exception(dict([el.split('=') for el in parsed_url.query.split('&')]))

        fragment = parsed_url.fragment
        access_token = dict([el.split('=') for el in fragment.split('&')])
        access_token['init_time'] = datetime.datetime.now()
        access_token['expires_in'] = float(access_token['expires_in'])
        access_token['login'] = vk_login
        # self.log.info('get access token: \n%s' % access_token)
        self.log.info('vkontakte authenticate for %s' % vk_login)
        return access_token

    def change_login(self):
        self._login = self.login_provider.get_early_login()
        self.reddit = praw.Reddit(
                user_agent=self._login.get("User-Agent"))
        self.reddit.login(self._login.get("login"), password=self._login.get("password"), disable_warning=True)
        log.info("bot [%s] connected" % self._login.get("login"))

    def do_posting(self):
        pass

    def init_work_cycle(self):
        consuming = random.randint(70, 90)
        production = 100 - consuming

        prod_voting = random.randint(60, 95)
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

        summ = self.c_vote_comment + self.c_comment_post + self.c_read_post
        interested_count = 0
        if action == "vote":
            interested_count = self.c_vote_comment
        elif action == "comment":
            interested_count = self.c_comment_post
        elif action == "consume":
            interested_count = self.c_read_post

        granted_perc = self.action_function_params.get(action)
        current_perc = int(((float(summ) if summ else 1.0) / (interested_count if interested_count else 100.0)) * 100)

        return current_perc <= granted_perc

    def add_post_to_comment(self, subreddit_name, post_fullname, comment_text):
        self.mutex.acquire()
        self.comments_queue.put(
                {"subreddit_name": subreddit_name, "post_fullname": post_fullname, "comment_text": comment_text})
        self.mutex.release()

    def process_work_cycle(self, subreddit_name, url_for_video):
        pass

    def do_see_post(self, post, subscribe=9, author_friend=9, comments=7, comment_vote=8,
                    comment_friend=7, post_vote=6, max_wait_time=30):
        """
        1) go to his url with yours useragent, wait random
        2) random check comments and random check more comments
        3) random go to link in comments
        :param post:
        :return:
        """
        try:
            res = requests.get(post.url, headers={"User-Agent": self._login.get("User-Agent")})
            log.info("SEE POST result: %s" % res)
        except Exception as e:
            log.warning("Can not see post %s url %s \n:(" % (post.fullname, post.url))
        wt = random.randint(1, max_wait_time)
        log.info("wait time: %s" % wt)
        time.sleep(wt)
        if post_vote and random.randint(0, 10) > post_vote and self.can_do("vote"):
            vote_count = random.choice([1, -1])
            post.vote(vote_count)

        if comments and random.randint(0, 10) > comments and wt > 5:  # go to post comments
            for comment in post.comments:
                if comment_vote and random.randint(0, 10) >= comment_vote and self.can_do("vote"):  # voting comment
                    vote_count = random.choice([1, -1])
                    comment.vote(vote_count)
                    self.c_vote_comment += 1
                    if comment_friend and random.randint(0,
                                                         10) >= comment_friend and vote_count > 0:  # friend comment author
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

        if subscribe and random.randint(0, 10) >= subscribe and \
                        post.subreddit.display_name not in self.subscribed_subreddits:  # subscribe sbrdt
            self.reddit.subscribe(post.subreddit.display_name)
            self.subscribed_subreddits.add(post.subreddit.display_name)
            self.ss += 1

        if author_friend and random.randint(0,
                                            10) >= author_friend and post.author.fullname not in self.friends:  # friend post author
            post.author.friend()
            self.friends.add(post.author.fullname)
            self.r_caf += 1

        self.c_read_post += 1

    def _get_random_near(self, slice, index, max):
        rnd = lambda x: random.randint(x / 10, x / 2) or 1
        max_ = lambda x: x if x < max and max_ != -1  else max
        count_random_left = max_(rnd(len(slice[0:index])))
        count_random_right = max_(rnd(len(slice[index:])))

        return [random.choice(slice[0:index]) for _ in xrange(count_random_left)], \
               [random.choice(slice[index:]) for _ in xrange(count_random_right)]

    def do_comment_post(self, post_fullname, subreddit_name, comment_text, max_post_near=3, max_wait_time=20, **kwargs):
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

                _post.comment(comment_text)

                for p_ind in see_right:
                    self.do_see_post(p_ind, max_wait_time=max_wait_time, **kwargs)

        if random.randint(0, 10) > 7 and subreddit_name not in self.subscribed_subreddits:
            self.reddit.subscribe(subreddit_name)

    def is_shadowbanned(self):
        self.mutex.acquire()
        result = self.login_provider.check_current_login()
        self.mutex.release()
        return result


if __name__ == '__main__':
    sbrdt = "videos"
    rbot = RedditReadBot(["videos"])
    # """client_id: O5AZrYjXI1R-7g
    # """client_secret: LOsmYChS2dcdQIlkMG9peFR6Lns
    wbot = RedditWriteBot(["videos"], client_id="O5AZrYjXI1R-7g", client_secret="LOsmYChS2dcdQIlkMG9peFR6Lns",
                          redirect_uri="http://127.0.0.1:65010/authorize_callback")

    subreddit = "videos"
    post_fullname, text = rbot.find_comment(subreddit)
    wbot.do_comment_post(post_fullname, subreddit, text, max_wait_time=2, subscribe=1, author_friend=1, comments=1,
                         comment_vote=1, comment_friend=1, post_vote=1, )
