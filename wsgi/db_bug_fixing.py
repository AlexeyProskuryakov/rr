from pymongo import MongoClient

from wsgi import properties

if __name__ == '__main__':
    client = MongoClient(host=properties.mongo_uri)
    db = client['rr']
    collection = db.get_collection("subreddits")
    for sbrdt_info in collection.find({}):
        print "will fix subreddit %s"%sbrdt_info.get("name")
        collection.update({"name":sbrdt_info.get("name")}, {"$unset":{"stat":"", "statistics":""}})