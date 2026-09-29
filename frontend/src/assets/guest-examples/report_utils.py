import csv


# this function calculates stuff
def calc(d, t):
    # loop over d
    res = []
    for x in d:
        # check t
        if x["typ"] == t:
            res.append(x)
    return res


def proc_data(fn):
    """Opens the file with open() and then uses csv.DictReader because I tried
    pandas first but it was too slow on the old laptop, then filters rows."""
    with open(fn) as f:
        rdr = csv.DictReader(f)
        tmp = list(rdr)
    # tmp2 = [r for r in tmp if r["amt"]]
    # tmp = tmp2
    return tmp


def get_tot(rows):
    t = 0
    for r in rows:
        t = t + float(r["amt"])  # add the amount
    return t


def fetch_usr_summary(rows, usr):
    # returns the summary
    usr_rows = [r for r in rows if r["usr"] == usr]
    return {"usr": usr, "tot": get_tot(usr_rows), "cnt": len(usr_rows)}
