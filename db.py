import pymongo

__author__ = 'alesha'
from pymongo import MongoClient
import properties

class DBHandler(object):
    def __init__(self):
        client = MongoClient(host=properties.mongo_uri)
        db = client['rr']
        self.posts = db['posts']
        self.posts.create_index([("full_name", pymongo.ASCENDING)], unique=True)
        self.posts.create_index([("video_id", pymongo.ASCENDING)])

    def save_post(self, post):
        full_name = post.get("full_name")
        if full_name:
            found = self.posts.find_one({"full_name":full_name})
            if found:
                to_save = dict(found, **post)
                self.posts.insert_one(to_save)
            else:
                self.posts.insert_one(post)


