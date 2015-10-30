from datetime import datetime
import hashlib
import logging
import pymongo
import time
from properties import min_time_step

__author__ = 'alesha'
from pymongo import MongoClient
import properties

log = logging.getLogger("DB")


class DBHandler(object):
    def __init__(self):
        log.info("start db handler %s" % properties.mongo_uri)
        client = MongoClient(host=properties.mongo_uri)
        db = client['rr']
        self.posts = db['posts']
        self.posts.create_index([("fullname", pymongo.ASCENDING)])
        self.posts.create_index([("video_id", pymongo.ASCENDING)])
        self.posts.create_index([("fullname", pymongo.ASCENDING), ("video_id", pymongo.DESCENDING)], unique=True)
        self.posts.create_index([("subreddit", pymongo.ASCENDING)])
        self.posts.create_index([("updated", pymongo.ASCENDING)])

        self.subreddits = db['subreddits']
        self.subreddits.create_index([("name", pymongo.ASCENDING)], unique=True)
        self.subreddits.create_index([("next_update", pymongo.ASCENDING)])

        self.statistics_cache = {'last_update': time.time(), 'data': {}}

        self.users = db['users']
        self.users.create_index([("name", pymongo.ASCENDING)], unique=True)
        self.users.create_index([("user_id", pymongo.ASCENDING)], unique=True)

    def add_user(self, name, pwd, uid):
        log.info("add user %s %s %s" % (name, pwd, uid))
        if not self.users.find_one({"$or": [{"user_id": uid}, {"name": name}]}):
            m = hashlib.md5()
            m.update(pwd)
            crupt = m.hexdigest()
            self.users.insert_one({"name": name, "pwd": crupt, "user_id": uid})

    def change_user(self, name, old_p, new_p):
        if self.check_user(name, old_p):
            m = hashlib.md5()
            m.update(new_p)
            crupt = m.hexdigest()
            self.users.insert_one({"name": name, "pwd": crupt})

    def check_user(self, name, pwd):
        found = self.users.find_one({"name": name})
        if found:
            m = hashlib.md5()
            m.update(pwd)
            crupt = m.hexdigest()
            if crupt == found.get("pwd"):
                return found.get("user_id")

    def save_post(self, post):
        if not self.posts.find_one({"fullname": post.get("fullname"), "video_id": post.get("video_id")}):
            post['updated'] = time.time()
            self.posts.insert_one(post)

    def is_post_present(self, post_full_name):
        found = self.posts.find_one({"fullname": post_full_name})
        return found is not None

    def is_post_video_id_present(self, video_id):
        found = self.posts.find_one({"video_id": video_id})
        return found is not None

    def update_post(self, post):
        post['updated'] = time.time()
        self.posts.update_one({"fullname": post.get("fullname"), "video_id": post.get("video_id")}, {"$set": post})

    def delete_post(self, full_name, video_id):
        self.posts.delete_one({"fullname": full_name, "video_id": video_id})

    def get_posts_for_update(self, min_update_period=properties.min_update_period):
        found = self.posts.find(
            {"$or": [{"updated": {"$lt": time.time() - min_update_period}}, {"updated": {"$exists": False}}]})
        return found

    def add_subreddit(self, subreddit_name, retrieve_params, time_step):
        found = self.subreddits.find_one({"name": subreddit_name})
        if found:
            self.update_subreddit_params(subreddit_name, retrieve_params, {"time_step": time_step})
        else:
            _time_step = time_step or min_time_step
            new = {'name': subreddit_name,
                   'params': retrieve_params,
                   "time_step": _time_step,
                   'last_update': time.time(),
                   'next_update': time.time() + _time_step}
            self.subreddits.insert_one(new)

    def get_subreddit(self, name):
        found = self.subreddits.find_one({"name": name})
        return found

    def update_subreddit_params(self, name, subreddit_params, subreddit_info=None):
        set = {"params": subreddit_params}
        if subreddit_info:
            set = dict(set, **subreddit_info)
        self.subreddits.update_one({"name": name}, {"$set":set})

    def update_subreddit_info(self, name, info):
        self.subreddits.update_one({"name": name}, {"$set": info})

    def toggle_subreddit(self, name, next_time_step):
        upd = {}
        upd['last_update'] = time.time()
        upd['next_update'] = time.time() + next_time_step
        upd['time_step'] = next_time_step
        self.update_subreddit_info(name, upd)

    def get_subreddits_to_process(self):
        result = []
        for subreddit in self.subreddits.find({"next_update": {"$lt": time.time()}}, {"name": 1}):
            result.append(subreddit.get("name"))
        return result

    def restart_statistic_cache(self):
        self.statistics_cache['data'] = None

    def get_subreddists_statistic(self):
        if self.statistics_cache['last_update'] + 3.0 > time.time() and self.statistics_cache.get('data'):
            return self.statistics_cache['data']
        else:
            self.statistics_cache['last_update'] = time.time()

        result = {}
        for subreddit in self.subreddits.find({}):
            el = {}
            el['name'] = subreddit.get("name")
            el['count'] = self.posts.find({"subreddit": subreddit.get("name")}).count()
            el['time_window'] = subreddit.get("time_window")
            el['next_time_retrieve'] = datetime.fromtimestamp(subreddit.get('next_update'))
            el['statistics'] = subreddit.get("statistics")
            el.update(subreddit.pop('params', {}))
            el.update(subreddit)
            result[el['name']] = el

        self.statistics_cache['data'] = result

        return result

    def get_posts_of_subreddit(self, name):
        posts = [el for el in self.posts.find({"subreddit": name})]
        return posts
