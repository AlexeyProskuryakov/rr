import logging
import random
import string
from multiprocessing import Process
import requests
import time


log = logging.getLogger("wake_up")

class WakeUp(Process):
    def __init__(self, what):
        super(WakeUp, self).__init__()
        self.what = what

    def run(self):
        while 1:
            salt = ''.join(random.choice(string.lowercase) for _ in range(20))
            result = requests.post("%s/wake_up/%s"%(self.what,salt))
            if result.status_code != 200:
                time.sleep(1)
                log.info("not work will trying next times...")
                continue
            else:
                log.info(result.content)
            time.sleep(3600)

if __name__ == '__main__':
    WakeUp("http://127.0.0.1:65010").start()
