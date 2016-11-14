from praw.objects import MoreComments


def comments_sequence(comments):
    sequence = list(comments)
    position = 0
    while 1:
        to_add = []
        for i in xrange(position, len(sequence)):
            position = i
            comment = sequence[i]
            if isinstance(comment, MoreComments):
                try:
                    to_add = comment.comments()
                except Exception as e:
                    pass
            else:
                yield comment

        if to_add:
            sequence.pop(position)
            for el in reversed(to_add):
                sequence.insert(position, el)

        if position >= len(sequence) - 1:
            break