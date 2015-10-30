# coding=utf-8
from flask import Flask, render_template, request, url_for, logging, session, g
from flask_login import LoginManager, login_user, login_required, logout_user
from flask_debugtoolbar import DebugToolbarExtension

from datetime import datetime
from uuid import uuid4
from multiprocessing import Queue
from werkzeug.utils import redirect
from db import DBHandler

from processes import SubredditProcessWorker, SubredditUpdater, PostUpdater
import properties
import os
from properties import min_time_step

__author__ = '4ikist'

log = logging.getLogger("web")
app = Flask("rr")

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

    log.info("Add new subreddit with params: \n%s" % "\n".join(["%s : %s" % (k, v) for k, v in params.iteritems()]))
    db.add_subreddit(name, params, params['lrtime'])
    try:
        tq.put({"name": name})
    except Exception as e:
        log.exception(e)

    return redirect(url_for('main'))


@app.route("/subreddit/add_to_queue/<name>", methods=["GET"])
@login_required
def add_to_queue(name):
    tq.put({"name": name})
    return redirect(url_for('main'))


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
                                                     "sbrdt_info": sbrdt_info})


@app.route("/", methods=["GET"])
@login_required
def main():
    user = g.user
    result = db.get_subreddists_statistic()
    return render_template("main.html", **{"username": user.name,
                                           "result": result})


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
