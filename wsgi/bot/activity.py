import datetime

from wsgi.engine import reddit_search


def cmp_by_created_utc(x, y):
    result = x.get("created_utc") - y.get("created_utc")
    if result > 0.5:
        return 1
    elif result < 0.5:
        return -1
    else:
        return 0


def get_interested_posts(sbrdt, count=100):
    interested = reddit_search("subreddit:\'%s\'" % sbrdt, count)
    interested.sort(cmp_by_created_utc)
    return interested


if __name__ == '__main__':
    t = 3600
    posts = get_interested_posts("woahdude")
    for post in posts:
        print post.get("created_dt")

    print len(posts)