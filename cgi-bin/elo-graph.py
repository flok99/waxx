#! /usr/bin/python3

import ataxx
import ataxx.pgn

import cgi
import io
import json
import mysql.connector
import os
import sys

from EloPy import elopy

os.environ['HOME'] = '/tmp'

db_host = '192.168.64.1'
db_user = 'user'
db_pass = 'pass'
db_db = 'waxx'

form = cgi.FieldStorage()
user = form.getvalue('user')

conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
c = conn.cursor()

i = elopy.Implementation()

c.execute('SELECT DISTINCT p1 FROM results UNION SELECT DISTINCT p2 FROM results')

for row in c.fetchall():
    i.addPlayer(row[0], rating=1000)

if user:
    c.execute("SELECT UNIX_TIMESTAMP(ts) AS ts, result, p1, p2 FROM results WHERE p1=%s AND result != '*' UNION ALL SELECT UNIX_TIMESTAMP(ts) AS ts, IF(result='1/2-1/2', '1/2-1/2', REVERSE(result)) AS result, p2 AS p1, p1 AS p2 FROM results WHERE p2=%s AND result != '*' ORDER BY ts ASC", (user, user, ))
else:
    c.execute("SELECT UNIX_TIMESTAMP(ts) AS ts, result, p1, p2 FROM results WHERE result != '*' UNION ALL SELECT UNIX_TIMESTAMP(ts) AS ts, IF(result='1/2-1/2', '1/2-1/2', REVERSE(result)) AS result, p2 AS p1, p1 AS p2 FROM results WHERE result != '*' ORDER BY ts ASC")

x_data = []
y_data = []

for row in c.fetchall():
    ts = row[0]
    result = row[1]
    p1 = row[2]
    p2 = row[3]

    if result == '1-0':
        i.recordMatch(p1, p2, winner=p1)
    elif result == '0-1':
        i.recordMatch(p1, p2, winner=p2)
    else:
        i.recordMatch(p1, p2, draw=True)

    rating = None

    if user:
        for entry in i.getRatingList():
            if entry[0] == user:
                rating = entry[1]
                break

    else:
        n = 0
        rating = 0

        for entry in i.getRatingList():
            rating += entry[1]
            n += 1

        rating /= n

    x_data.append(ts)
    y_data.append(rating)

conn.commit()
conn.close()

import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.dates as md
import datetime as dt

print("Content-type: image/svg+xml")
print()

my_dpi = 75
p = plt.figure(figsize=(800 / my_dpi, 480 / my_dpi), dpi=my_dpi)
ax = p.add_subplot(111)
ax.set(xlabel='time')
if user:
    ax.set(ylabel='elo rating')
else:
    ax.set(ylabel='average elo rating')

xfmt = md.DateFormatter('%Y-%m-%d %H:%M:%S')
ax.xaxis.set_major_formatter(xfmt)
dates=[dt.datetime.fromtimestamp(ts) for ts in x_data]
plt.xticks(rotation=30)
plt.subplots_adjust(bottom=0.2)

ax.plot(dates, y_data)

buffer_ = io.BytesIO()
plt.savefig(buffer_, format='svg')
print(buffer_.getvalue().decode('utf-8'))
