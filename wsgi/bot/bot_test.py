from wsgi.bot.bot import RedditWriteBot, A_CONSUME, A_VOTE, A_COMMENT
from wsgi.db import DBHandler


def test_bot_actions():
    bot_name = "Shlak2k15"
    db = DBHandler()
    bot = RedditWriteBot(db, bot_name)

    bot.action_function_params = {A_CONSUME: 33, A_VOTE: 33, A_COMMENT: 33}

    for i in range(100):
        assert bot.can_do(A_CONSUME)
        assert bot.can_do(A_VOTE)
        assert bot.can_do(A_COMMENT)

        assert not bot.must_do(A_CONSUME)
        assert not bot.must_do(A_VOTE)
        assert not bot.must_do(A_COMMENT)

        bot.incr_counter(A_CONSUME)
        bot.incr_counter(A_VOTE)
        bot.incr_counter(A_COMMENT)

    bot.action_function_params = {A_CONSUME: 33, A_VOTE: 33, A_COMMENT: 33}

    assert bot.can_do(A_CONSUME)
    assert not bot.must_do(A_CONSUME)
    bot.incr_counter(A_CONSUME)

    assert bot.can_do(A_VOTE)
    assert not bot.must_do(A_VOTE)
    bot.incr_counter(A_VOTE)
    # bot.incr_counter(A_COMMENT)

    assert bot.can_do(A_COMMENT)
    assert bot.must_do(A_COMMENT)
    bot.incr_counter(A_COMMENT)

    assert bot.can_do(A_CONSUME)
    bot.incr_counter(A_CONSUME)

    assert bot.can_do(A_VOTE)
    bot.incr_counter(A_VOTE)

    bot.incr_counter(A_COMMENT)
    bot.incr_counter(A_COMMENT)
    assert not bot.can_do(A_COMMENT)

    assert bot.can_do(A_VOTE)
    bot.incr_counter(A_VOTE)

    assert bot.can_do(A_CONSUME)
    assert bot.must_do(A_CONSUME)