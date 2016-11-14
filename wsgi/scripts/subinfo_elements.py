import logging
from collections import defaultdict

import praw

log = logging.getLogger("si_elts")
all_elements = '$ALL$'

class RelationalElements(defaultdict):
    def __new__(cls, *args, **kwargs):
        result = super(RelationalElements, cls).__new__(cls)
        return result

    def __init__(self):
        super(RelationalElements, self).__init__(set)
        self[all_elements] = set()

    def add(self, group, user):
        self[group].add(user)
        if group != all_elements:
            self[all_elements].add(user)

    def add_groups(self, groups, user):
        for g in groups:
            self[g].add(user)
        self[all_elements].add(user)

    def __add__(self, other):
        for k, v in self.iteritems():
            if k in other:
                self[k] = v.union(other[k])

        for k, v in other.iteritems():
            if k not in self:
                self[k] = v
        return self

    def __repr__(self):
        return "\n".join(["%s\t%s" % (k, len(v)) for k, v in self.iteritems()])

    @property
    def all(self):
        return self[all_elements]

class Users(object):
    def __new__(cls, *args, **kwargs):
        result = super(Users, cls).__new__(cls)
        return result

    def __init__(self):
        self.users = RelationalElements()
        self.subs = RelationalElements()

    def compile_subs(self, sub_generator):
        log.info("Compile subs of %s users..." % (len(self.users.all)))
        for subs in sub_generator(self.users.all):
                self.subs += subs
        return self.subs

    def add(self, group, user):
        self.users.add(group, user)

    @property
    def all(self):
        return self.users.all