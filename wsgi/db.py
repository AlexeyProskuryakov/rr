from datetime import datetime
import hashlib

import time

import pymongo

from pymongo import MongoClient
from wsgi import get_interested_fields
from wsgi.properties import SRC_SEARCH, min_time_step, min_update_period, logger, mongo_uri, mongo_db_name

__author__ = 'alesha'

log = logger.getChild("DB")


class StatisticsCache(object):
    def __init__(self):
        self.last_update = time.time()
        self.data = {}


class DBHandler(object):
    def __init__(self, name="?", uri=mongo_uri, db_name=mongo_db_name):
        log.info("start db handler for [%s] %s" % (name, uri))
        self.client = MongoClient(host=uri, maxPoolSize=10, connect=False)
        self.db = self.client[db_name]
        self.collection_names = self.db.collection_names(include_system_collections=False)


class Storage(object):
    def __init__(self, name="?", host=mongo_uri):
        log.info("start db handler %s %s" % (name, host))
        client = MongoClient(host=host)
        db = client['rr']
        self.posts = db['posts']
        self.posts.create_index([("fullname", pymongo.ASCENDING)])
        self.posts.create_index([("video_id", pymongo.ASCENDING)])
        self.posts.create_index([("fullname", pymongo.ASCENDING), ("video_id", pymongo.DESCENDING)], unique=True)
        self.posts.create_index([("subreddit", pymongo.ASCENDING)])
        self.posts.create_index([("updated", pymongo.ASCENDING)])
        self.posts.create_index([("source", pymongo.ASCENDING)])

        self.subreddits = db['subreddits']
        self.subreddits.create_index([("name", pymongo.ASCENDING)], unique=True)
        self.subreddits.create_index([("next_update", pymongo.ASCENDING)])

        self.statistics_cache = StatisticsCache()

        self.users = db['users']
        self.users.create_index([("name", pymongo.ASCENDING)], unique=True)
        self.users.create_index([("user_id", pymongo.ASCENDING)], unique=True)

        self.raw_posts = db['raw_posts']
        self.raw_posts.create_index([("subreddit", pymongo.ASCENDING)])

        self.search_params = db['search_result']
        self.search_params.create_index([("subreddit", pymongo.ASCENDING)])

        self.cache = {}
        self.statistics = db.get_collection("statistics") or db.create_collection(
            'statistics',
            capped=True,
            size=1024 * 1024 * 2,  # required
        )

        self.statistics.create_index([("time", pymongo.ASCENDING)])
        self.statistics.create_index([("type", pymongo.ASCENDING)])

        self.bot_log = db.get_collection("bot_log") or db.create_collection(
            "bot_log",
            capped=True,
            size=1024 * 1024 * 256,
        )

        self.bot_log.create_index([("bot_name", pymongo.ASCENDING)])
        self.bot_log.create_index([("time", pymongo.ASCENDING)])
        self.bot_log.create_index([("action", pymongo.ASCENDING)])

        self.bot_config = db.get_collection("bot_config")
        self.bot_config.create_index([("user", pymongo.ASCENDING)], unique=True)

        self.commented_posts = db.get_collection("commented_posts")
        self.commented_posts.create_index([("fullname", pymongo.ASCENDING)], unique=True)
        self.commented_posts.create_index([("low_copies", pymongo.ASCENDING)])
        self.commented_posts.create_index([("time", pymongo.ASCENDING)])

        self.db = db

    def update_bot_access_credentials_info(self, user, info):
        if isinstance(info.get("scope"), set):
            info['scope'] = list(info['scope'])
        self.bot_config.update_one({"user": user}, {"$set": {"info": info, "time": time.time()}})

    def prepare_bot_access_credentials(self, client_id, client_secret, redirect_uri, user, pwd):
        found = self.bot_config.find_one({"user": user})
        if not found:
            self.bot_config.insert_one(
                {"client_id": client_id,
                 "client_secret": client_secret,
                 "redirect_uri": redirect_uri,
                 "user": user,
                 "pwd": pwd
                 })
        else:
            self.bot_config.update_one({"user": user}, {"$set": {"client_id": client_id,
                                                                 "client_secret": client_secret,
                                                                 "redirect_uri": redirect_uri,
                                                                 "pwd": pwd}})

    def get_bot_access_credentials(self, user):
        result = self.bot_config.find_one({"user": user})
        if result.get("info").get("scope"):
            result['info']['scope'] = set(result['info']['scope'])
        return dict(result)

    def set_bot_channel_id(self, name, channel_id):
        self.bot_config.update_one({"user": name}, {"$set": {"channel_id": channel_id}})

    def set_bot_live_state(self, name, state, pid):
        self.bot_config.update_one({"user": name},
                                   {"$set": {"live_state": state, "live_state_time": time.time(), "live_pid": pid}})

    def get_bot_live_state(self, name, pid):
        found = self.bot_config.find_one({"user": name})
        if found:
            state_time = found.get("live_state_time")
            _pid = found.get("live_pid")
            if not state_time or (state_time and time.time() - state_time > 3600) or pid != _pid:
                return "unknown"
            else:
                return found.get("live_state")
        return None

    def get_bots_info(self):
        found = self.bot_config.find({})
        result = []
        for el in found:
            result.append({"name": el.get("user"), "state": el.get("live_state", "unknown")})
        return result

    def set_bot_subs(self, name, subreddits):
        self.bot_config.update_one({"user": name}, {"$set": {"subs": subreddits}})

    def get_bot_subs(self, name):
        found = self.bot_config.find_one({"user": name})
        if found:
            return found.get("subs", None)
        return None

    def update_bot_internal_state(self, name, state):
        update = {}
        if state.get("ss"):
            update["ss"] = {"$each": state['ss']}
        if state.get("frds"):
            update["frds"] = {"$each": state['frds']}
        if update:
            update = {"$addToSet": update}
            result = self.bot_config.update_one({"user": name}, update)

    def get_bot_internal_state(self, name):
        found = self.bot_config.find_one({"user": name})
        if found:
            return {"ss": set(found.get("ss", [])),  # subscribed subreddits
                    "frds": set(found.get("friends", [])),  # friends
                    }

    def set_bot_live_configuration(self, name, configuration):
        self.bot_config.update_one({'user': name}, {"$set": {"live_config": configuration.data}})

    def get_bot_live_configuration(self, name):
        found = self.bot_config.find_one({"user": name})
        if found:
            live_config = found.get("live_config")
            return live_config

    def get_bot_config(self, name):
        return self.bot_config.find_one({"user": name})

    def set_post_commented(self, post_fullname):
        found = self.commented_posts.find_one({"fullname": post_fullname})
        if not found:
            self.commented_posts.insert_one({"fullname": post_fullname, "low_copies": False})
        else:
            self.commented_posts.update_one({"fullname": post_fullname}, {'$unset': {"low_copies": "", "time": ""}})

    def is_post_used(self, post_fullname):
        found = self.commented_posts.find_one({"fullname": post_fullname})
        if found and found.get("low_copies"):
            _time = found.get("time", 0)
            return time.time() - _time < 3600 * 24
        return False

    def set_post_low_copies(self, post_fullname):
        found = self.commented_posts.find_one({"fullname": post_fullname})
        if not found:
            self.commented_posts.insert_one({"fullname": post_fullname, "low_copies": True, "time": time.time()})
        else:
            self.commented_posts.update_one({"fullname": post_fullname},
                                            {'$set': {"low_copies": True, "time": time.time()}})

    def save_log_bot_row(self, bot_name, action_name, info):
        self.bot_log.insert_one(
            {"bot_name": bot_name,
             "action": action_name,
             "time": datetime.utcnow(),
             "info": info})

    def get_log_of_bot(self, bot_name, limit=None):
        res = self.bot_log.find({"bot_name": bot_name}).sort("time", pymongo.DESCENDING)
        if limit:
            res = res.limit(limit)
        return list(res)

    def get_log_of_bot_statistics(self, bot_name):
        pipeline = [
            {"$match": {"bot_name": bot_name}},
            {"$group": {"_id": "$action", "count": {"$sum": 1}}},
        ]
        return list(self.bot_log.aggregate(pipeline))

    def add_search_params(self, sbrdt_name, params, statistic):
        ps = self.get_search_params(sbrdt_name)
        if ps:
            self.search_params.update_one({"subreddit": sbrdt_name},
                                          {"$set": {"params": params, "statistic": statistic}})
        else:
            self.search_params.save({"subreddit": sbrdt_name, "params": params, "statistic": statistic})

    def get_search_params(self, sbrdt_name):
        result = self.search_params.find_one({"subreddit": sbrdt_name})
        if result:
            return result.get("params"), result.get("statistic")
        return None

    def get_search_results_names(self, deleted=False):
        """
        :return: [{_id:<name of subreddit>, count:<count of posts in this subreddit>}]
        """
        pipeline = [
            {"$match": {"source": SRC_SEARCH, "deleted": {"$exists": deleted}}},
            {"$group": {"_id": "$subreddit", "count": {"$sum": 1}}},
        ]
        result = list(self.posts.aggregate(pipeline))
        return result

    def add_raw_posts(self, sbrdt_name, posts):
        found = self.raw_posts.find_one({"name": sbrdt_name})
        if found:
            self.raw_posts.delete_one({"name": sbrdt_name})

        posts_ = map(lambda x: get_interested_fields(x, ["created_utc", "fullname", "video_id", "ups"]), posts)
        self.raw_posts.insert_one({"name": sbrdt_name, "posts": posts_, "time": time.time()})

    def get_raw_posts(self, sbrdt_name):
        found = self.raw_posts.find_one({"name": sbrdt_name})
        if found:
            if (time.time() - found.get("time")) > min_update_period:
                self.raw_posts.delete_one({"name": sbrdt_name})
                return None
            return found.get("posts")

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

    def save_post(self, post, source=None):
        if source:
            post['source'] = source
        if not self.posts.find_one({"fullname": post.get("fullname"), "video_id": post.get("video_id")}):
            post['updated'] = time.time()
            self.posts.insert_one(post)

    def get_post(self, fullname, video_id, projection=None):
        found = self.posts.find_one({"fullname": fullname, "video_id": video_id},
                                    projection={"_id": False} if not projection else projection)
        return found

    def is_post_present(self, post_full_name):
        found = self.posts.find_one({"fullname": post_full_name})
        return found is not None

    def is_post_video_id_present(self, video_id):
        if self.cache.get(video_id):
            return True

        found = self.posts.find_one({"video_id": video_id})
        if found:
            self.cache[video_id] = True
            return True

        return False

    def update_post(self, post):
        post['updated'] = time.time()
        self.posts.update_one({"fullname": post.get("fullname"), "video_id": post.get("video_id")}, {"$set": post})

    def delete_post(self, full_name, video_id):
        self.posts.update_one({"fullname": full_name, "video_id": video_id}, {"$set": {"deleted": time.time()}})

    def get_posts_for_update(self, min_update_period=min_update_period):
        found = self.posts.find(
            {"$or": [{"updated": {"$lt": time.time() - min_update_period}}, {"updated": {"$exists": False}}],
             "deleted": {"$exists": False}})
        return found

    def get_posts_of_subreddit(self, name, source=None):
        params = {"subreddit": name,
                  "deleted": {"$exists": False}}
        if source:
            params['source'] = source
        posts = [el for el in self.posts.find(params)]
        return posts

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
        self.subreddits.update_one({"name": name}, {"$set": set})

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
        self.statistics_cache = StatisticsCache()

    def get_subreddists_statistic(self):
        if self.statistics_cache.last_update + 60.0 > time.time() and self.statistics_cache.data:
            return self.statistics_cache.data
        else:
            self.statistics_cache.last_update = time.time()

        result = {}
        for subreddit in self.subreddits.find({}):
            el = {}
            el['name'] = subreddit.get("name")
            el['count'] = self.posts.find({"subreddit": subreddit.get("name"), "deleted": {"$exists": False}}).count()
            el['time_window'] = subreddit.get("time_window")
            el['next_time_retrieve'] = datetime.fromtimestamp(subreddit.get('next_update'))
            el['statistic'] = subreddit.get("statistic")
            el.update(subreddit.pop('params', {}))
            el.update(subreddit)
            result[el['name']] = el

        self.statistics_cache.data = result

        return result
