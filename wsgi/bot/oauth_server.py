
from flask import Flask, request

import praw

app = Flask(__name__)


@app.route('/')
def homepage():
    KeyID = "uniqueKey"
    CLIENT_ID = 'O5AZrYjXI1R-7g'
    CLIENT_SECRET = 'LOsmYChS2dcdQIlkMG9peFR6Lns'
    REDIRECT_URI = 'http://127.0.0.1:65010/authorize_callback'

    r = praw.Reddit('OAuth Webserver example by u/_Daimon_ ver 0.1. See '
                    'https://praw.readthedocs.org/en/latest/'
                    'pages/oauth.html for more info.')

    r.set_oauth_app_info(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)

    link_refresh = r.get_authorize_url(KeyID,'identity,edit,submit,subscribe,vote', refreshable=True)
    link_refresh = "<a href=%s>link</a>" % link_refresh
    print link_refresh
    text = "Push me %s</br></br>" % link_refresh

    state = request.args.get('state', '')
    code = request.args.get('code', '')
    if code and state:
        info = r.get_access_information(code)
        user = r.get_me()
        text += "<br>State=%s, code=%s, info=%s." % (state, code,
                                                          str(info))
        text += '<br>You are %s and have %u link karma.' % (user.name,
                                                       user.link_karma)

    return text

@app.route('/authorize_callback')
def authorized():
    KeyID = "uniqueKey"
    CLIENT_ID = 'O5AZrYjXI1R-7g'
    CLIENT_SECRET = 'LOsmYChS2dcdQIlkMG9peFR6Lns'
    REDIRECT_URI = 'http://127.0.0.1:65010/authorize_callback'

    r = praw.Reddit('OAuth Webserver example by u/_Daimon_ ver 0.1. See '
                    'https://praw.readthedocs.org/en/latest/'
                    'pages/oauth.html for more info.')

    r.set_oauth_app_info(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)

    link_refresh = r.get_authorize_url(KeyID,'identity,edit,submit,subscribe,vote', refreshable=True)
    link_refresh = "<a href=%s>link</a>" % link_refresh
    print link_refresh
    text = "Push me %s</br></br>" % link_refresh

    state = request.args.get('state', '')
    code = request.args.get('code', '')
    if code and state:
        info = r.get_access_information(code)
        user = r.get_me()
        text += "<br>State=%s, code=%s, info=%s." % (state, code,
                                                          str(info))
        text += '<br>You are %s and have %u link karma.' % (user.name,
                                                       user.link_karma)
        info = r.refresh_access_information(info['refresh_token'])
        text += "<br> Refreshed info: %s"%info
    return text

if __name__ == '__main__':

    app.run(debug=True, port=65010)