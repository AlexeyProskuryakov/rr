from wsgi import youtube
from wsgi.db import Storage
from wsgi.engine import to_save

if __name__ == '__main__':
    db = Storage(__file__)
    for post in db.posts.find({"deleted":{"$exists":False}, "yt_views":{"$exists":False}}):
        video_info = youtube.get_video_info(post.get("video_id"))
        if not video_info:
            print "yt none:", post.get("video_url")
            db.delete_post(post.get("fullname"), post.get("video_id"))
            continue
        upd_post = to_save(dict(post, **video_info))
        db.update_post(upd_post)
        print "updated:", upd_post