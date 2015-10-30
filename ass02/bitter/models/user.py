import itertools
import re
import stringprep

from bitter.db import db
from bitter.model import Model

schema = """
    create table user (
        id integer primary key,

        email text unique not null,
        canonical_username text unique not null,
        username text unique not null,
        password text not null,

        name text,
        profile_image file,
        background_image file,
        description text,
        home_coords coordinates,
        home_suburb text,

        notify_on_mention integer,
        notify_on_reply integer,
        notify_on_listen integer
    );

    create table user_listen (
        by integer not null references user(id) on delete cascade,
        to_ integer not null references user(id) on delete cascade
    );
    create unique index user_listen_by on user_listen(by, to_);
    create index user_listen_to on user_listen(to_);
"""

def canonicaliseUsername(username, ignoreSpaces = False, throws = True):
    # Read stringprep documentation for the meaning of the tables

    chars = list(username)
    for c, char in enumerate(chars):
        if stringprep.in_table_a1(char):
            if throws:
                raise ValueError
            else:
                chars[c] = u""
        elif stringprep.in_table_b1(char):
            chars[c] = u""
        else:
            chars[c] = stringprep.map_table_b2(char)

    chars = list(stringprep.unicodedata.normalize("NFKC", u"".join(chars)))

    for c, char in enumerate(chars):
        if ((not ignoreSpaces and stringprep.in_table_c11_c12(char)) or
            stringprep.in_table_c21_c22(char) or
            stringprep.in_table_c3(char) or
            stringprep.in_table_c4(char) or
            stringprep.in_table_c5(char) or
            stringprep.in_table_c6(char) or
            stringprep.in_table_c7(char) or
            stringprep.in_table_c8(char) or
            stringprep.in_table_c9(char)):
            if throws:
                raise ValueError
            else:
                chars[c] = u""

    chars = u"".join(chars)

    if throws:
        RandAL = map(stringprep.in_table_d1, chars)
        for c in RandAL:
            if c:
                if filter(stringprep.in_table_d2, chars):
                    raise ValueError
                if not RandAL[0] or not RandAL[-1]:
                    raise ValueError

    return chars

class User(Model):
    publicProperties = set((
        "id",
        "username",
        "name",
        "profileImage",
        "backgroundImage",
        "description",
        "homeCoords",
        "homeSuburb",
        "bleats",
        "listeningTo",
        "listenedBy"
    ))

    def populate(self, attribute):
        cur = db.cursor()
        if attribute == "bleats":
            cur.execute("select id from bleat where user = ?", (self.id,))
            setattr(self, "bleats", set(map(lambda row: row["id"], cur.fetchall())))
        elif attribute == "listeningTo":
            cur.execute("select to_ from user_listen where by = ?", (self.id,))
            setattr(self, "listeningTo", set(map(lambda row: row["to_"], cur.fetchall())))
        elif attribute == "listenedBy":
            cur.execute("select by from user_listen where to_ = ?", (self.id,))
            setattr(self, "listenedBy", set(map(lambda row: row["by"], cur.fetchall())))
        else:
            raise LookupError("User models do not contain {0} relations".format(attribute))

    @classmethod
    def _buildWhereClause(cls, where):
        search = where.pop("search", None)

        if "username" in where:
            where["canonicalUsername"] = canonicaliseUsername(where["username"], throws = False)
            del where["username"]

        result = super(User, cls)._buildWhereClause(where)

        if search:
            search = canonicaliseUsername(search, ignoreSpaces = True, throws = False)
            search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            search = "%" + re.sub(re.compile("\s+", re.UNICODE), "%", search) + "%"
            result["(canonical_username || \" \" || ifnull(name, \"\")) like ? escape \"\\\""] = search

        return result

    @classmethod
    def create(cls, properties):
        if "username" in properties:
            properties["canonicalUsername"] = canonicaliseUsername(properties["username"], throws = False)

        return super(User, cls).create(properties)

    @classmethod
    def update(cls, where, update):
        where = cls._buildWhereClause(where)

        cur = db.cursor()
        cur.execute(
            "select id from user where {0}".format(" and ".join(where.keys())),
            where.values()
        )
        ids = map(lambda row: row["id"], cur.fetchall())

        if len(ids) == 0:
            return

        if "username" in update:
            update["canonicalUsername"] = canonicaliseUsername(update["username"], throws = False)

        if "listeningTo" in update:
            cur.execute("delete from user_listen where by in ({0})".format(", ".join(["?"] * len(ids))), ids)
            if update["listeningTo"]:
                cur.execute(
                    "insert into user_listen (by, to_) values {0}".format(", ".join(["(?, ?)"] * len(update["listeningTo"]))),
                    list(itertools.chain.from_iterable(itertools.product(ids, update["listeningTo"])))
                )
            del update["listeningTo"]

        if "listenedBy" in update:
            cur.execute("delete from user_listen where to_ in ({0})".format(", ".join(["?"] * len(ids))), ids)
            if update["listenedBy"]:
                cur.execute(
                    "insert into user_listen (by, to_) values {0}".format(", ".join(["(?, ?)"] * len(update["listenedBy"]))),
                    list(itertools.chain.from_iterable(itertools.product(update["listenedBy"], ids)))
                )
            del update["listenedBy"]

        cur.execute(
            "update user set {0} where id in ({1})".format(
                ", ".join(map(lambda key: cls._toTableName(key) + " = ?", update.keys())),
                ", ".join(["?"] * len(ids)),
            ),
            update.values() + ids
        )

        return cur.rowcount
