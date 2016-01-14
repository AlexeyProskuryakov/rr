from collections import defaultdict
from wsgi.engine import reddit_search, MAX_COUNT


def get_interested_posts(sbrdt):
    interested = reddit_search("subreddit:\'%s\'" % sbrdt)
    return interested


def _get_coefficients(posts_clusters, n):
    result = {}
    for dt, posts in posts_clusters.iteritems():
        result[dt] = float(sum(map(lambda post: post.get("ups") + post.get("comments_count"), posts))) / n
    return result


def evaluate_statistics(sbrdt_name):
    posts = get_interested_posts(sbrdt_name)

    days = defaultdict(list)
    hours = defaultdict(list)
    for post in posts:
        days[post.get("created_dt").weekday()].append(post)
        hours["%s_%s" % (post.get("created_dt").weekday(), post.get("created_dt").hour)].append(post)

    n = len(posts)
    return _get_coefficients(days, n), _get_coefficients(hours, n)


if __name__ == '__main__':
    days, hours = evaluate_statistics(sbrdt_name="woahdude")
    print "\n".join(["%s : %s" % (k, v) for k, v in days.iteritems()])

    h_keys = hours.keys()
    h_keys.sort()

    print "\n".join(["%s : %s" % (k, hours[k]) for k in h_keys])
