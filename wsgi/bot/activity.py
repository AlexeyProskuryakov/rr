from collections import defaultdict
import time

from wsgi.engine import MAX_COUNT, reddit, to_save, to_show


def get_interested_posts(sbrdt):
    result = []
    cur = int(time.time())
    before = int(time.time()) - (3600 * 24 * 7 * 2)
    for post in reddit.search("timestamp:%s..%s"%(before, cur), limit=MAX_COUNT, count=MAX_COUNT, subreddit=sbrdt, syntax="cloudsearch"):
        post_info = to_save(to_show(post))
        result.append(post_info)
    return result



def _get_coefficients(posts_clusters, n):
    result = {}
    for dt, posts in posts_clusters.iteritems():
        result[dt] = float(sum(map(lambda post: post.get("ups") + post.get("comments_count"), posts))) / n
    return result


def evaluate_statistics(sbrdt_name):
    """
    Evaluating statistics for input subreddit

    :param sbrdt_name:
    :return: 2 dicts of weights and days and hours at day.
    """
    posts = get_interested_posts(sbrdt_name)

    days = defaultdict(list)
    hours = defaultdict(list)
    for post in posts:
        days[post.get("created_dt").weekday()].append(post)
        hours[post.get("created_dt").hour].append(post)

    n = len(posts)
    print "eval statistic for %s posts"%n
    return _get_coefficients(days, n), _get_coefficients(hours, n)


if __name__ == '__main__':
    days, hours = evaluate_statistics(sbrdt_name="cringe")
    print "\n".join(["%s : %s" % (k, v) for k, v in days.iteritems()])

    h_keys = hours.keys()
    h_keys.sort()

    # print "\n".join(["%s : %s" % (k, hours[k]) for k in h_keys])
