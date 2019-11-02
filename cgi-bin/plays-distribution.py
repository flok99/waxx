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

conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
c = conn.cursor()

c.execute('select unix_timestamp(dt), avg(c), stddev(c) from (select date(ts) as dt, p, count(*) as c from (select p1 as p, ts from results union all select p2 as p, ts from results) as bla group by date(ts), p) as bla2 group by dt')

x_data = []
y_data_avg = []
y_data_sd = []

for row in c.fetchall():
    x_data.append(row[0])
    y_data_avg.append(row[1])
    y_data_sd.append(row[2])

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
#ax.set(ylabel='avg count')
ax.set_ylabel('avg count', color='b')

xfmt = md.DateFormatter('%Y-%m-%d')
ax.xaxis.set_major_formatter(xfmt)
dates=[dt.datetime.fromtimestamp(ts) for ts in x_data]
plt.xticks(rotation=30)
plt.subplots_adjust(bottom=0.2)

ax.plot(dates, y_data_avg, 'b')

ax2 = ax.twinx()
ax2.plot(dates, y_data_sd, 'r')
ax2.set_ylabel('sd count', color='r')
ax2.tick_params('y', colors='r')

#ax2.spines['right'].set_position(('outward', 60)) 

buffer_ = io.BytesIO()
plt.savefig(buffer_, format='svg')
print(buffer_.getvalue().decode('utf-8'))
