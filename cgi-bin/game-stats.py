#! /usr/bin/python3

import ataxx
import ataxx.pgn

import cgi
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

form = cgi.FieldStorage()
user = form.getvalue('user')

conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
c = conn.cursor()

if user and user != '':
    c.execute('select move_nr, avg(took) as avg_took, avg(score) as avg_score, count(*) as n_games from moves, results where results_id=id and (p1=%s or p2=%s) group by move_nr', (user, user,))
else:
    c.execute('select move_nr, avg(took) as avg_took, avg(score) as avg_score, count(*) as n_games from moves group by move_nr')

x_data = []
y_data_took = []
y_data_score = []
y_data_n_games = []

for row in c.fetchall():
    x_data.append(row[0])
    y_data_took.append(row[1])
    y_data_score.append(row[2])
    y_data_n_games.append(row[3])

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
ax.set(xlabel='move nr')

ax.set_ylabel('took (s)', color='b')

ax2 = ax.twinx()
ax2.plot(x_data, y_data_score, 'r')
ax2.set_ylabel('score', color='r')
ax2.tick_params('y', colors='r')

ax2.spines['right'].set_position(('outward', 45)) 

ax3 = ax.twinx()
ax3.plot(x_data, y_data_n_games, 'g')
ax3.set_ylabel('games', color='g')
ax3.tick_params('y', colors='g')

ax.plot(x_data, y_data_took)

buffer_ = io.BytesIO()
plt.tight_layout()
plt.savefig(buffer_, format='svg')
print(buffer_.getvalue().decode('utf-8'))
