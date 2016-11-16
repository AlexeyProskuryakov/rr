import logging
from Queue import Empty
from multiprocessing import Process, Event
from multiprocessing import Queue as mQ

from threading import Thread
from Queue import Queue as Q
from time import sleep

import praw

from wsgi.engine import get_reposts_count
from wsgi.scripts import GET_USER_AGENT_R
from wsgi.scripts.subinfo_elements import Users, RelationalElements, all_elements
from wsgi.scripts.utils import comments_sequence
from wsgi.sub_connections import SCStorage

log = logging.getLogger("sub_info_agg")

CMNT = "comment"
ATHR = "author"

r = praw.Reddit(user_agent=GET_USER_AGENT_R())

sc_store = SCStorage()


def load_recommended(sub_name):
    recomended_subs = r.get_subreddit_recommendations(sub_name)
    for r_sub in recomended_subs:
        sc_store.add_connection(sub_name, r_sub.display_name, ct="recommendation")
        rr_subs = r.get_subreddit_recommendations(r_sub.display_name)
        for rr_sub in rr_subs:
            sc_store.add_connection(r_sub.display_name, rr_sub.display_name, ct="recommendation")


def get_sub_users(sub_name, uq):
    log.info("Start getting users from: %s" % sub_name)
    sub = r.get_subreddit(sub_name)
    s_c, c_c = 0, 0
    fsbm, esbm = None, None
    hot = list(sub.get_hot(limit=500))
    log.info("Load %s hot posts in %s" % (len(hot), sub_name))

    for subm in hot:
        if sc_store.is_contains(subm.fullname):
            log.info("%s is contains" % subm.fullname)
            continue

        if fsbm is None:
            fsbm = subm
        esbm = subm
        get_reposts_count(subm.url, {"subreddit": subm.subreddit.display_name, "created_utc": subm.created_utc})

        if not subm.author:
            continue

        su = Users()
        su.add('author', subm.author.name)

        for comment in comments_sequence(subm.comments):
            if comment.author:
                su.add("comment", comment.author.name)
                c_c += 1
        s_c += 1
        log.info("\t%s processed; posts: %s, comments: %s uniques: %s", subm.fullname, s_c, c_c, len(su.all))
        sc_store.u_add(subm.fullname)
        uq.put(su)

    sub_speed = float(s_c) / abs(esbm.created_utc - fsbm.created_utc)
    sc_store.set_sub_info(sub_name, {"speed": sub_speed})


def get_subs_from_users(users_queue, sub_queue, event):
    reddit = praw.Reddit(user_agent=GET_USER_AGENT_R())
    while 1:
        user_name = qget(users_queue)
        if not user_name:
            break

        if sc_store.is_contains(user_name):
            log.info("%s is contains")
            continue
        log.info("Start load subs from comments and posts of %s" % user_name)
        user = reddit.get_redditor(user_name)
        us = RelationalElements()
        c_subs = set(map(lambda x: x.subreddit.display_name, user.get_comments()))
        p_subs = set(map(lambda x: x.subreddit.display_name, user.get_submitted()))
        u_subs = c_subs.union(p_subs)

        us.add_groups(u_subs, user_name)

        sub_queue.put(dict(us))
        log.info("\tloaded %s subs of %s" % (len(u_subs), user_name))
        sc_store.u_add(user_name)

    event.clear()


def generate_subs(users):
    q_in, q_out = mQ(len(users)), mQ(len(users))
    for u in users:
        q_in.put(u)

    te = []
    for _ in range(8):
        e = Event()
        e.set()
        t = Process(target=get_subs_from_users, args=(q_in, q_out, e))
        t.daemon = True
        t.start()
        te.append(e)

    while 1:
        result = qget(q_out)
        if not result:
            for e in te:
                if e.is_set():
                    continue
            break
        result = RelationalElements.create(result)
        yield result


def qget(q):
    max_tryings = 5
    while 1:
        try:
            return q.get()
        except Empty:
            if max_tryings > 0:
                max_tryings -= 1
                sleep(1)
                continue
        except Exception as e:
            log.exception(e)
            return None


def load_sub_users_and_reposts_connections(sub):
    users_queue = Q(500)
    p = Thread(target=get_sub_users, args=(sub, users_queue))
    p.daemon = True
    p.start()

    all_users = set()
    while 1:
        su = qget(users_queue)
        if not su:
            break
        su.compile_subs(generate_subs)
        for r_sub, users in su.subs.iteritems():
            if r_sub != all_elements:
                sc_store.add_connection(r_sub, sub, ons=users, ct="users")

        all_users.union(su.all)

    sc_store.set_sub_info(sub, {"unique_users_count": len(all_users)})


if __name__ == '__main__':
    # load_recommended("cringe")
    load_sub_users_and_reposts_connections("cringe")
    pass
