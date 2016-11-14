from collections import defaultdict

import pymongo

from wsgi.db import DBHandler

DEFAULT_CT = ""

class SCStorage(DBHandler):
    def __init__(self):
        super(SCStorage, self).__init__(name="sub connections")
        self.sub_connections = self.db["sub_connections"]
        self.sub_connections.create_index(
            [("sf", pymongo.DESCENDING), ("st", pymongo.DESCENDING), ("ct", pymongo.DESCENDING)], unique=True)
        self.sub_connections.create_index("sf")
        self.sub_connections.create_index("st")
        self.sub_connections.create_index("ct")

        self.sub_info = self.db["sub_info"]
        self.sub_info.create_index("s")

        self.r_users = self.db["sub_r_users"]
        self.r_users.create_index([("name", pymongo.ASCENDING)], unique=True)


    def add_connection(self, sf, st, on=None, ons=set(), ct=DEFAULT_CT):
        if on:
            ons.add(on)
        found = self.sub_connections.find_one({"sf": sf, "st": st, "ct":ct})
        if found:
            f_ons = set(found.get("ons"))
            to_add = ons.difference(f_ons)
            if to_add:
                self.sub_connections.update_one({"sf": sf, "st": st, "ct":ct}, {"$push":{"ons":{"$each":list(to_add)}}})

        if not found:
            self.sub_connections.insert_one({"sf": sf, "st": st, "ons": list(ons), "ct":ct})

    def get_sub_connections(self, sub, ct = None, back=False):
        q= {"sf":sub}
        if ct:
            q["ct"] = ct
        result = list(self.sub_connections.find(q))
        if back:
            result.extend(list(self.sub_connections.find({"st":sub})))
        return result


    def set_sub_info(self, sub, info):
        self.sub_info.update_one({"s":sub}, {"$set":dict({"s":sub}, **info)}, upsert=True)

    def get_subs_info(self):
        return self.sub_info.find({})

    def u_add(self, u):
        self.r_users.update_one({"name":u}, {"$set":{"name":u}}, upsert=True)

    def is_contains(self, u):
        self.r_users.find_one({"name":u})
