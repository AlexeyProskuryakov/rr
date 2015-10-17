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



log_file = os.path.join(module_path(), 'result.log')
logger = logging.getLogger()
logger.setLevel(logging.INFO)
fh = logging.FileHandler(log_file)
ch = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s[%(levelname)s]%(name)s|%(processName)s(%(process)d): %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(ch)




mongo_uri = "mongodb://alesha:sederfes100500@ds035674.mongolab.com:35674/rr"
default_time_min = "PT0H1M30S"