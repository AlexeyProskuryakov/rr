import logging
import os
import sys

__author__ = 'alesha'


def module_path():
    if hasattr(sys, "frozen"):
        return os.path.dirname(
                sys.executable
        )
    return os.path.dirname(__file__)


log_file_f = lambda x: os.path.join(module_path(), (x if x else "") + 'result.log')
log_file = os.path.join(module_path(), 'result.log')
cacert_file = os.path.join(module_path(), 'cacert.pem')

logger = logging.getLogger()

logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s[%(levelname)s]%(name)s|%(processName)s(%(process)d): %(message)s')
formatter_process = logging.Formatter('%(asctime)s[%(levelname)s]%(name)s|%(processName)s: %(message)s')
formatter_bot = logging.Formatter('%(asctime)s|%(name)s: %(message)s')

sh = logging.StreamHandler()
sh.setFormatter(formatter)
logger.addHandler(sh)

fh = logging.FileHandler(log_file)
fh.setFormatter(formatter)
logger.addHandler(fh)

fh_process = logging.FileHandler(log_file_f("process_"))
fh.setFormatter(formatter_process)
logger.getChild("process").addHandler(fh)

fh_bot = logging.FileHandler(log_file_f("bot_"))
fh_bot.setFormatter(formatter_bot)
logger.getChild("bot").addHandler(fh_bot)

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

SRC_SEARCH = "search"
SRC_OBSERV = "observation"

mongo_uri = "mongodb://alesha:sederfes100500@ds035674.mongolab.com:35674/rr"
mongo_db_name = "rr"

wake_up_mongo_uri = "mongodb://3030:sederfes100500@ds055525.mongolab.com:55525/reddit_people"
wake_up_mongo_db_name = "reddit_people"

default_time_min = "PT0H1M30S"

min_update_period = 3600 * 24
min_time_step = 10
max_time_step = 3600 * 5

step_time_after_trying = 1
tryings_count = 10

time_step_less_iteration_power = 0.85

test_mode = os.environ.get("RR_TEST", "false").strip().lower() in ("true","1","yes")
print "TEST? ", test_mode

logger.info(
    "RR MANAGEMENT SYSTEM STARTED... \nEnv:%s" % "\n".join(["%s:\t%s" % (k, v) for k, v in os.environ.iteritems()]))
