# coding=utf-8
from flask import Flask, render_template, request, url_for, logging, session, g
from flask_login import LoginManager, login_user, login_required, logout_user
from flask_debugtoolbar import DebugToolbarExtension

from datetime import datetime
from uuid import uuid4
from werkzeug.utils import redirect
from engine import reddit_search_url, reddit_get_new

__author__ = '4ikist'

app = Flask("rr")


app.secret_key = 'fooooooo'
app.config['SESSION_TYPE'] = 'filesystem'

# app.config["SECRET_KEY"] = "foooo"
# app.debug = True
# toolbar = DebugToolbarExtension(app)



login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

log = logging.getLogger("web")


class User(object):
    def __init__(self, name, pwd):
        self.id = unicode(uuid4().get_hex())
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

    def get_by_id(self, id):
        return self.users.get(id)

    def auth_user(self, name, pwd):
        id = hash("%s%s" % (name, pwd))
        authed = self.auth_users.get(id)
        if authed:
            user = self.users.get(authed)
            user.auth = True
            user.active = True
            return user

    def logout(self, user):
        user.auth = False
        user.active = False
        self.users[user.id] = user

    def add_user(self, user):
        self.users[user.id] = user
        auth_id = hash("%s%s" % (user.name, user.pwd))
        self.auth_users[auth_id] = user.id


usersHandler = UsersHandler()
usersHandler.add_user(User("3030", "100500"))


@app.before_request
def load_user():
    if session.get("user_id"):
        user = usersHandler.get_by_id(session.get("user_id"))
    else:
        user = {"name": "Guest"}  # Make it better, use an anonymous User instead

    g.user = user


@login_manager.user_loader
def load_user(userid):
    return usersHandler.get_by_id(userid)


@login_manager.unauthorized_handler
def unauthorized_callback():
    print "uauth"
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


@app.route("/", methods=["POST", "GET"])
@login_required
def main():
    user = g.user
    if request.method == "POST":
        subrdt = request.form.get("subreddit_name")
        result = reddit_get_new(subrdt)
        return render_template("main.html", **{"now": datetime.now(),
                                               "username": user.name,
                                               "result": result})
    else:
        return render_template("main.html", **{"now":datetime.now(),
                                               "username":user.name,
                                               "result":[]})

@app.route("/search/<q>")
@login_required
def search(q):
    result = reddit_search_url(q)
    return render_template("search.html", **{"result": result})


if __name__ == '__main__':
    app.run(port=5000)
