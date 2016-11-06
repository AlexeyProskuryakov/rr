import pymongo

from wsgi.db import DBHandler


class SCStorage(DBHandler):
    def __init__(self):
        super(SCStorage, self).__init__(name="sub connections")
        self.sub_connections = self.db["sub_connections"]
        self.sub_connections.create_index(
            [("sl", pymongo.ASCENDING), ("sr", pymongo.DESCENDING), ("on", pymongo.ASCENDING)], unique=True)
        self.sub_connections.create_index("sr")
        self.sub_connections.create_index("sl")

    def add_connection(self, sub1, sub2, on):
        found = self.sub_connections.find_one({"$or": [{"sl": sub1, "sr": sub2}, {"sl": sub2, "sr": sub1}], "on": on})
        if not found:
            self.sub_connections.insert_one({"sl": sub1, "sr": sub2, "on": on})

    def get_sub_connections(self, sub):
        pass
