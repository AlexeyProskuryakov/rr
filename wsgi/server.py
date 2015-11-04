# coding=utf-8
from uuid import uuid4
from multiprocessing import Queue
import os

from flask import Flask, render_template, request, url_for, logging, session, g
from flask.json import jsonify
from flask_login import LoginManager, login_user, login_required, logout_user
from flask_debugtoolbar import DebugToolbarExtension
from werkzeug.utils import redirect

from db import DBHandler
from engine import reddit_get_new
from processes import SubredditProcessWorker, SubredditUpdater, PostUpdater, update_stored_posts
import properties

__author__ = '4ikist'

log = logging.getLogger("web")
cur_dir = os.path.curdir
print cur_dir
app = Flask("rr", template_folder=cur_dir+"/templates")

app.secret_key = 'fooooooo'
app.config['SESSION_TYPE'] = 'filesystem'

if os.environ.get("test", False):
    log.info("will run at test mode")
    app.config["SECRET_KEY"] = "foooo"
    app.debug = True
    app.config['DEBUG_TB_INTERCEPT_REDIRECTS'] = False
    toolbar = DebugToolbarExtension(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

db = DBHandler()


class User(object):
    def __init__(self, name, pwd):
        self.id = str(uuid4().get_hex())
        self.auth = False
        self.active = False
        self.anonymous = False
        self.name = name
        self.pwd = pwd

    def is_authenticated(self):
        return self.auth

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return self.id


class UsersHandler(object):
    def __init__(self):
        self.users = {}
        self.auth_users = {}

    def get_guest(self):
        user = User("Guest", "")
        self.users[user.id] = user
        return user

    def get_by_id(self, id):
        found = self.users.get(id)
        if not found:
            found = db.users.find_one({"user_id": id})
            if found:
                user = User(found.get('name'), found.get("pwd"))
                user.id = found.get("user_id")
                self.users[user.id] = user
                found = user
        return found

    def auth_user(self, name, pwd):
        authed = db.check_user(name, pwd)
        if authed:
            user = self.get_by_id(authed)
            if not user:
                user = User(name, pwd)
                user.id = authed
            user.auth = True
            user.active = True
            self.users[user.id] = user
            return user

    def logout(self, user):
        user.auth = False
        user.active = False
        self.users[user.id] = user

    def add_user(self, user):
        self.users[user.id] = user
        db.add_user(user.name, user.pwd, user.id)


usersHandler = UsersHandler()
log.info("users handler was initted")
usersHandler.add_user(User("3030", "1"))


@app.before_request
def load_user():
    if session.get("user_id"):
        user = usersHandler.get_by_id(session.get("user_id"))
    else:
        user = usersHandler.get_guest()
    g.user = user


@login_manager.user_loader
def load_user(userid):
    return usersHandler.get_by_id(userid)


@login_manager.unauthorized_handler
def unauthorized_callback():
    return redirect(url_for('login'))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login = request.form.get("name")
        password = request.form.get("password")
        remember_me = request.form.get("remember") == u"on"
        user = usersHandler.auth_user(login, password)
        if user:
            try:
                login_user(user, remember=remember_me)

                return redirect(url_for("main"))
            except Exception as e:
                log.exception(e)
                return render_template("login.html")

    return render_template("login.html")


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


rq = Queue()
tq = Queue()


@app.route("/subreddit/add", methods=['POST'])
@login_required
def add_subreddit():
    name = request.form.get("name") or "funny"
    params = {}
    params['rate_min'] = int(request.form.get("rate_min") or 0)
    params['rate_max'] = int(request.form.get("rate_max") or 99999)
    params['reposts_max'] = int(request.form.get("reposts_max") or 10)
    params['lrtime'] = int(request.form.get("lrtime") or 1800)
    params['time_min'] = request.form.get("time_min") or properties.default_time_min

    log.info("Add %s with params: \n%s" % (name, "\n".join(["%s : %s" % (k, v) for k, v in params.iteritems()])))
    db.add_subreddit(name, params, params['lrtime'])
    try:
        tq.put({"name": name})
    except Exception as e:
        log.exception(e)

    return redirect(url_for('main'))


@app.route("/subreddit/add_to_queue/<name>", methods=["POST"])
@login_required
def add_to_queue(name):
    tq.put({"name": name})
    return jsonify(**{"ok": True})


@app.route("/subreddit/del", methods=["POST"])
@login_required
def del_subreddit():
    name = request.form.get("name")
    db.subreddits.delete_one({'name': name})
    db.restart_statistic_cache()
    return redirect(url_for('main'))


@app.route("/subbredit/info/<name>", methods=["GET"])
@login_required
def info_subreddit(name):
    user = g.user
    posts = db.get_posts_of_subreddit(name)
    sbrdt_info = db.get_subreddists_statistic()[name]
    return render_template("subbredit_info.html", **{"username": user.name,
                                                     "posts": posts,
                                                     "el": sbrdt_info, })


@app.route("/post/del/<fullname>/<video_id>", methods=["GET"])
@login_required
def del_post(fullname, video_id):
    db.delete_post(fullname, video_id)
    return jsonify(**{"ok": True})


@app.route("/post/update/<fullname>/<video_id>", methods=["GET"])
@login_required
def update_post(fullname, video_id):
    found = db.get_post(fullname, video_id)
    if found:
        update_stored_posts(db, [found])
        return jsonify(**{"ok": True})
    return jsonify(**{"ok": False, "detail": "Post %s %s not found" % (fullname, video_id)})


@app.route("/", methods=["GET"])
@login_required
def main():
    user = g.user
    result = db.get_subreddists_statistic()
    return render_template("main.html", **{"username": user.name,
                                           "result": result,
                                           "go": True})


@app.route("/chart/<name>", methods=["GET"])
@login_required
def get_chart_data(name):
    loaded = db.get_posts_of_subreddit(name)
    loaded_fns = set(map(lambda x: x.get("fullname"), loaded))
    all = db.get_raw_posts(name)
    if not all:
        all = reddit_get_new(name)
        db.add_raw_posts(name, all)

    first_element = all[-1]
    fe_time = first_element.get("created_utc")

    sbrdt = db.get_subreddit(name)
    sbrdt_params = sbrdt.get("params")

    all = filter(lambda x: x.get("video_id") is not None, all)
    all = filter(lambda x: x.get("ups") >= sbrdt_params.get("rate_min") and x.get("ups") <= sbrdt_params.get("rate_max"), all)
    all = filter(lambda x: x.get("fullname") not in loaded_fns, all)

    def post_chart_data(post):
        return [int(post.get("created_utc") - fe_time), post.get("ups")]

    def get_info(posts):
        return [(int(post.get("created_utc") - fe_time), "%s\n%s" % (post.get("fullname"), post.get("video_id"))) for
                post in posts if post.get("created_utc")]

    info = dict(get_info(all), **dict(get_info(loaded)))

    data = {"series": [
        {"label": "loaded", "data": [post_chart_data(post) for post in loaded]},
        {"label": "all", "data": [post_chart_data(post) for post in all]},
    ],
        "info": info}
    return jsonify(**data)


spw = SubredditProcessWorker(tq, rq, db)
spw.daemon = True
spw.start()

su = SubredditUpdater(tq, db)
su.daemon = True
su.start()

pu = PostUpdater(db)
pu.daemon = True
pu.start()

if __name__ == '__main__':
    app.run(port=5000)
