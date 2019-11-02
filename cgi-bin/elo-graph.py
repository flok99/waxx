#! /usr/bin/python3

import ataxx
import ataxx.pgn

import cgi
import datetime
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

c.execute('SELECT user FROM players')

for row in c.fetchall():
    i.addPlayer(row[0])

c.execute("SELECT UNIX_TIMESTAMP(ts) AS ts, result, p1, p2 FROM results WHERE result != '*' ORDER BY ts")

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
    elif result == '1/2-1/2':
        i.recordMatch(p1, p2, draw=True)
    else:
        continue

    rating = None

    if user:
        rating = i.getPlayerRating(user)

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

ax.xaxis.set_major_formatter(md.DateFormatter('%Y-%m-%d'))
dates=[dt.datetime.fromtimestamp(ts) for ts in x_data]

ax.plot(dates, y_data)

buffer_ = io.BytesIO()
p.autofmt_xdate()
plt.savefig(buffer_, format='svg')
print(buffer_.getvalue().decode('utf-8'))
