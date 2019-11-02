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

os.environ['HOME'] = '/tmp'

db_host = '192.168.64.1'
db_user = 'user'
db_pass = 'pass'
db_db = 'waxx'

conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
c = conn.cursor()

c.execute('select unix_timestamp(ts), count(*), avg(score) from results group by date(ts)')

x_data = []
y_data_count = []
y_data_score = []

for row in c.fetchall():
    x_data.append(row[0] * 1.0)
    y_data_count.append(row[1])
    y_data_score.append(row[2])

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

ax.xaxis.set_major_formatter(md.DateFormatter('%Y-%m-%d'))
dates=[dt.datetime.fromtimestamp(ts) for ts in x_data]
plt.subplots_adjust(bottom=0.2)

ax.plot(dates, y_data_count, 'b')
ax.set_ylabel('count', color='b')

ax2 = ax.twinx()
ax2.plot(dates, y_data_score, 'r')
ax2.set_ylabel('avg score', color='r')
ax2.tick_params('y', colors='r')

buffer_ = io.BytesIO()
p.autofmt_xdate()
plt.savefig(buffer_, format='svg')
print(buffer_.getvalue().decode('utf-8'))
