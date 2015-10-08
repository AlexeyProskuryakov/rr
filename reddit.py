__author__ = 'alesha'
import praw
import urllib


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


def to_show(el):
    return {"fullname": el.fullname, "ups": el.ups, "title": el.title,
            "permalink": el.permalink, "url": el.url, "url_encoded": urllib.quote(el.url, "")}


r = praw.Reddit(user_agent="foo")


def get_new(subreddit="video"):
    result = []
    for el in r.get_subreddit(subreddit).get_new():
        result.append(to_show(el))
    return result


def search_url(url_quoted):
    result = []
    for el in r.search("url:%s" % urllib.unquote(url_quoted)):
        result.append(to_show(el))
    return result


if __name__ == '__main__':

    for el in r.get_subreddit("video").get_new():
        print_post(el)
        url = el.media.get("oembed", {}).get("url")
        print "!!!SEARCH by url START:------------------------------------"
        if url:
            for sub_url in r.search("url:%s" % url):
                print_post(sub_url)
        print "!!!SEARCH END ---------------------------------------------\n\n\n"
