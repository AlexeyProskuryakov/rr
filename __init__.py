__author__ = '4ikist'

import praw


def print_post(el):
    print "[%s] %s ups: %s; comments: %s; created_at: %s link: %s \ncontent_url:%s" % (
        el.fullname,
        el.title,
        el.ups,
        len(el.comments),
        el.created,
        el.permalink,
        el.media.get("oembed", {}).get("url")
    )


if __name__ == '__main__':
    r = praw.Reddit(user_agent="foo")

    for el in r.get_subreddit("video").get_new():
        print_post(el)
        url = el.media.get("oembed", {}).get("url")
        print "!!!SEARCH by url START:------------------------------------"
        if url:
            for sub_url in r.search("url:%s" % url):
                print_post(sub_url)
        print "!!!SEARCH END ---------------------------------------------\n\n\n"
